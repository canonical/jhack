import json
import shlex
import subprocess
from collections import namedtuple
from subprocess import getoutput, check_call, CalledProcessError, check_output
from typing import Optional, List, NamedTuple

import typer
from PIL.ImageOps import contain

from jhack.conf.conf import check_destructive_commands_allowed
from jhack.helpers import (
    ColorOption,
    Target,
    RichSupportedColorOptions,
    JPopen,
    check_command_available,
)
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("kill")


def _get_running_hook(
    target: Target,
    model: str,
    dry_run: bool = False,
) -> Optional[str]:
    model_arg = f" -m {model}" if model else ""
    cmd = f"juju show-status-log{model_arg} {target.unit_name} --days 2 --format json"
    if dry_run:
        print("would attempt to get the currently running hook name with:", cmd)
        return "<some-event>"

    out = json.loads(getoutput(cmd))
    execs = [a for a in out if a["status"] == "executing"]
    if not execs:
        return None
    last_exec = execs[-1]["message"]
    parts = last_exec.split()
    if not len(parts) == 3:
        logger.debug(f"executing hook set an unexpected message: {last_exec!r}")
        return None
    return parts[1]


def _eval_cmd(target: Target, model: str, eval: str):
    model_arg = f" -m {model}" if model else ""
    return f'juju ssh{model_arg} {target.unit_name} eval "{eval}"'


def _install_dependencies(
    deps: List[str],
    target: Target,
    model: Optional[str],
    dry_run: bool = False,
):
    cmd = _eval_cmd(target, model, f"apt update && apt install -y {' '.join(deps)}")

    if dry_run:
        print("would run:", cmd)
        return
    else:
        print("Installing dependencies...")

    try:
        check_call(
            shlex.split(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
        )
    except CalledProcessError:
        logger.exception(f"failed to install procps and gdb on {target.unit_name}")
        exit(1)


class ParseFailure(RuntimeError):
    """Raised when we cannot parse a line."""


class _ProcInfo(NamedTuple):
    # wrapper for ps -aux output columns
    owner: str
    pid: str
    pcpu: str
    pmem: str
    vsz: str
    rss: str
    tty: str
    stat: str
    start: str
    time: str
    command: str

    @staticmethod
    def parse(val):
        """Build from ps-aux output line."""
        args = tuple(word.strip() for word in val.split())
        if len(args) < 10:
            raise ParseFailure(val)
        command = " ".join(args[10:])
        return _ProcInfo(*args[:10], command)

    def safe_compare(self, other: "_ProcInfo"):
        """Compare outside cgroup boundary."""
        return (
            self.vsz == other.vsz
            and self.time == other.time
            and self.command == other.command
        )


def _get_running_process_info(
    target: Target,
    model: Optional[str] = None,
    dry_run: bool = False,
) -> List[_ProcInfo]:
    cmd = _eval_cmd(target, model, "ps -aux | grep ./src/charm.py | grep -v grep")
    if dry_run:
        print("would run:", cmd)
        return [
            _ProcInfo.parse(
                "root 7007 0.2 0.1 65280 56368 ? S 10:22 0:00 python3 ./src/charm.py"
            )
        ]
    else:
        print("Searching for charm process...")

    try:
        out = getoutput(cmd)
    except CalledProcessError:
        logger.exception(f"failed to run ps -aux on {target.unit_name}")
        exit(1)
    return [_ProcInfo.parse(line) for line in out.splitlines()]


def _kill_running_process(
    pid: int,
    target: Target,
    model: Optional[str],
    dry_run: bool = False,
    host: bool = False,
    exit_code: int = 0,
):
    kill_cmd = f"gdb --batch --eval-command 'call exit({exit_code})' --pid {pid}"

    if host:
        cmd = kill_cmd

    else:
        cmd = _eval_cmd(
            target,
            model,
            f"gdb --batch --eval-command 'call exit({exit_code})' --pid {pid}",
        )

    if dry_run:
        print(
            f"would try to force-exit the {'host' if host else 'container'} process running the charm with: "
            f"{cmd} (actual PID may differ)"
        )
        return
    else:
        print("Sniping charm process...")

    try:
        check_output(shlex.split(cmd))
    except CalledProcessError:
        logger.exception(f"failed to kill charm process with {cmd!r}")
        exit("could not terminate charm process")


def _get_host_pid(container_proc_info: _ProcInfo, dry_run: bool = False) -> int:
    """Get the host PID of the process running in a container."""
    cmd = f'ps -aux | grep "{container_proc_info.command}"'
    if dry_run:
        print(
            f"would attempt to find the host's PID for the container PID {container_proc_info.pid} with:",
            cmd,
        )
        return 42
    else:
        print("Remapping charm process onto host...")

    found = []
    full_psaux = getoutput(cmd)
    for line in full_psaux.splitlines():
        local_procinfo = _ProcInfo.parse(line)
        if local_procinfo.safe_compare(container_proc_info):
            found.append(local_procinfo.pid)

    if not found:
        exit(f"unable to find host PID for container process {container_proc_info!r}")

    if len(found) > 1:
        exit(
            f"cannot find unique host PID for container process {container_proc_info!r}"
        )
    return int(found[0])


def _kill(
    target: str,
    model: Optional[str] = None,
    dry_run: bool = False,
    host_kill: bool = False,
    exit_code: int = 0,
):
    if not dry_run:
        check_destructive_commands_allowed("kill", "juju ssh")

    target = Target.from_name(target)
    running_hook = _get_running_hook(target, model=model, dry_run=dry_run)
    if not running_hook and not dry_run:
        logger.error(
            "The charm isn't running any hook right now. We'll go on though..."
        )

    print(f"Preparing to interrupt the {running_hook} hook.")

    deps = ["procps"]
    if not host_kill:
        deps.append("gdb")

    _install_dependencies(deps, target, model, dry_run=dry_run)
    pinfo = _get_running_process_info(target, model, dry_run=dry_run)

    if not pinfo:
        exit(f"no charm process appears to be running on {target.unit_name}")
    if len(pinfo) > 1:
        exit(
            f"cannot identify a unique charm process running on {target.unit_name}: too many pythons in this box."
        )

    if host_kill:
        host_pid = _get_host_pid(pinfo[0], dry_run=dry_run)
        _kill_running_process(
            host_pid,
            target,
            host=True,
            model=model,
            exit_code=exit_code,
            dry_run=dry_run,
        )
    else:
        _kill_running_process(
            int(pinfo[0].pid),
            target,
            host=False,
            model=model,
            exit_code=exit_code,
            dry_run=dry_run,
        )
    print("All done! Charm interrupted.")


def kill(
    target: str = typer.Argument(
        ..., help="Unit whose charm process should be murdered."
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Model in which to apply this command."
    ),
    exit_code: Optional[int] = typer.Option(
        0, "--exit-code", "-e", help="Exit code for the charm process."
    ),
    host_kill: bool = typer.Option(
        0,
        "--host-kill",
        "-H",
        help="Attempts to remap the charm process onto the host and kill it from the host.",
    ),
    dry_run: bool = typer.Option(
        False,
        is_flag=True,
        help="Don't actually do anything, just print what would have happened.",
    ),
):
    """Forcefully interrupt a charm's hook execution."""
    _kill(
        target=target,
        model=model,
        host_kill=host_kill,
        dry_run=dry_run,
        exit_code=exit_code,
    )


if __name__ == "__main__":
    _kill("tempo-worker-k8s/0")
