import json
import shlex
import subprocess
from json import JSONDecodeError
from subprocess import getoutput, check_call, CalledProcessError, check_output
from typing import Optional, List, NamedTuple

import typer

from jhack.conf.conf import check_destructive_commands_allowed
from jhack.helpers import (
    Target,
    InvalidUnitNameError,
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
    try:
        out = json.loads(getoutput(cmd))
    except JSONDecodeError:
        logger.debug(f"{cmd} didn't yield valid JSON, probably the unit doesn't exist.")
        exit(
            f"Failure retrieving running hook for {target.unit_name}; does the unit exist?"
        )

    juju_unit_changes = [e for e in out if e["type"] == "juju-unit"]
    # ignore workload-set statuses
    last_change = juju_unit_changes[-1]
    if not last_change["status"] == "executing":
        logger.error(
            "charm doesn't appear to be executing anything ATM; we'll try anyway."
        )
        return "<whatever>"

    parts = last_change["message"].split()
    if not len(parts) == 3:
        logger.debug(f"executing hook set an unexpected message: {last_change!r}")
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
    command_name: str = "./src/charm.py",
    dry_run: bool = False,
) -> List[_ProcInfo]:
    cmd = _eval_cmd(target, model, f"ps -aux | grep {command_name} | grep -v grep")
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

    if out.startswith("ERROR"):
        ps_aux = getoutput(_eval_cmd(target, model, "ps -aux"))
        logger.error(f"no charm process found in")
        print(ps_aux)
        exit(
            f"cannot retrieve charm process on {target.unit_name}. Is the charm really executing?"
        )

    return [_ProcInfo.parse(line) for line in out.splitlines()]


def _kill_running_process(
    pid: int,
    target: Target,
    model: Optional[str],
    dry_run: bool = False,
    host: bool = False,
    exit_code: int = 0,  # type: ignore
):
    # FIXME would be cool if this worked, but we get an odd error.
    # kill_cmd = f"gdb --batch --eval-command 'call exit({exit_code})' --pid {pid}"
    kill_cmd = f"kill -9 {pid}"

    if host:
        cmd = kill_cmd

    else:
        cmd = _eval_cmd(
            target,
            model,
            kill_cmd,
        )

    if dry_run:
        print(
            f"would try to force-exit the {'host' if host else 'container'} process running the charm with: "
            f"{cmd} (actual PID may differ)"
        )
        return
    else:
        print("Sniping charm process...")

    if host:
        print("jhack doesn't have super cow powers (yet)")
        print(f"run this as sudo to terminate the charm process: \nsudo {kill_cmd}")
        exit(0)
    else:
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
    exit_code: int = 1,
    command_name: str = "./src/charm.py",
):
    if not dry_run:
        check_destructive_commands_allowed("kill", "juju ssh")
    try:
        target = Target.from_name(target)
    except InvalidUnitNameError:
        exit(
            f"This command only works on units. Please pass a unit name, not {target!r}"
        )

    running_hook = _get_running_hook(target, model=model, dry_run=dry_run)
    if not running_hook and not dry_run:
        logger.error(
            "The charm isn't running any hook right now. We'll go on though..."
        )

    print(f"Preparing to interrupt the {running_hook} hook.")

    deps = ["procps"]
    # if not host_kill:
    #     deps.append("gdb")

    _install_dependencies(deps, target, model, dry_run=dry_run)
    pinfo = _get_running_process_info(
        target, model, command_name=command_name, dry_run=dry_run
    )

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
    # exit_code: Optional[int] = typer.Option(
    #     0, "--exit-code", "-e", help="Exit code for the charm process. Currently no"
    # ),
    host_kill: bool = typer.Option(
        0,
        "--host-kill",
        "-H",
        help="Attempts to remap the charm process onto the host and kill it from the host.",
    ),
    command_name: str = typer.Option(
        "./src/charm.py",
        "--command-name",
        "-c",
        help="The command to match when searching for the charm process.",
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
        # exit_code=exit_code,
        command_name=command_name,
    )


if __name__ == "__main__":
    _kill("worker/0")
