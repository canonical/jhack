import contextlib
import json
import json as jsn
import os
import re
import shlex
import subprocess
import tempfile
from collections import namedtuple
from dataclasses import dataclass
from functools import lru_cache
from itertools import chain
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_call, check_output
from typing import Callable, List, Literal, Optional, Sequence, Tuple

import typer

from jhack.config import IS_SNAPPED
from jhack.logger import logger

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class Format(StrEnum):
    auto = "auto"
    json = "json"


FormatOption = typer.Option(Format.auto, "-f", "--format", help="Output format.")


class FormatUnavailable(NotImplementedError):
    """Raised when a command cannot comply with a format parameter."""


RichSupportedColorOptions = Optional[
    Literal["auto", "standard", "256", "truecolor", "windows", "no"]
]
ColorOption = typer.Option(
    "auto",
    "-c",
    "--color",
    help="Color scheme to adopt. Supported options: "
    "['auto', 'standard', '256', 'truecolor', 'windows', 'no'] "
    "no: disable colors entirely.",
)


def check_command_available(cmd: str):
    try:
        proc = JPopen(f"which {cmd}".split())
        proc.wait()
    except Exception as e:
        logger.error(e, exc_info=True)
        return False
    if err := proc.stderr.read():
        logger.error(err.decode("utf-8"))
    return proc.returncode == 0


def get_substrate(model: str = None) -> Literal["k8s", "machine"]:
    """Attempts to guess whether we're talking k8s or machine."""
    cmd = f'juju show-model{f" {model}" if model else ""} --format=json'
    proc = JPopen(cmd.split())
    raw = proc.stdout.read().decode("utf-8")
    model_info = jsn.loads(raw)

    if not model:
        model = list(model_info)[0]

    model_type = model_info[model]["model-type"]
    if model_type == "iaas":
        return "machine"
    elif model_type == "caas":
        return "k8s"
    else:
        raise ValueError(f"unrecognized model type: {model_type}")


def get_local_charm() -> Path:
    cwd = Path(os.getcwd())
    try:
        return next(cwd.glob("*.charm"))
    except StopIteration:
        raise FileNotFoundError(f"could not find a .charm file in {cwd}")


def JPopen(args: List[str], wait=False, **kwargs):  # noqa
    return _JPopen(tuple(args), wait, **kwargs)


def _JPopen(args: Tuple[str], wait: bool, silent_fail: bool = False, **kwargs):  # noqa
    # Env-passing-down Popen
    proc = subprocess.Popen(
        args,
        env=kwargs.pop("env", os.environ),
        stderr=kwargs.pop("stderr", PIPE),
        stdout=kwargs.pop("stdout", PIPE),
        **kwargs,
    )
    if wait:
        proc.wait()

    # this will presumably only ever branch if wait==True
    if proc.returncode not in {0, None}:
        msg = f"failed to invoke command ({args}, {kwargs})"
        if IS_SNAPPED and "ssh client keys" in proc.stderr.read().decode("utf-8"):
            msg += (
                " If you see an ERROR above saying something like "
                "'open ~/.local/share/juju/ssh: permission denied',"
                "you might have forgotten to "
                "'sudo snap connect jhack:dot-local-share-juju snapd'"
            )
            logger.error(msg)
        elif not silent_fail:
            logger.error(msg)

    return proc


def juju_log(unit: str, msg: str, model: str = None, debug=True):
    m = f" -m {model}" if model else ""
    d = " --debug" if debug else ""
    JPopen(f"juju exec -u {unit}{m} -- juju-log{d}".split() + [msg])


def juju_status(app_name=None, model: str = None, json: bool = False):
    cmd = f'juju status{" " + app_name if app_name else ""} --relations'
    if model:
        cmd += f" -m {model}"
    if json:
        cmd += " --format json"
    proc = JPopen(cmd.split())
    raw = proc.stdout.read().decode("utf-8")
    if json:
        return jsn.loads(raw)
    return raw


@lru_cache
def cached_juju_status(app_name=None, model: str = None, json: bool = False):
    return juju_status(
        app_name=app_name,
        model=model,
        json=json,
    )


def is_k8s_model(status):
    """Determine if this is a k8s model from a juju status."""

    if status["applications"]:
        # no machines = k8s model
        if not status.get("machines"):
            return True
        else:
            return False

    cloud_name = status["model"]["cloud"]
    logger.warning(
        "unable to determine with certainty if the current model is a k8s model or not;"
        f"guessing it based on the cloud name ({cloud_name})"
    )
    return "k8s" in cloud_name


@lru_cache
def juju_client_version() -> Tuple[int, ...]:
    proc = JPopen("juju version".split())
    raw = proc.stdout.read().decode("utf-8").strip()
    version = raw.split("-")[0]
    return tuple(map(int, version.split(".")))


@lru_cache
def juju_agent_version() -> Optional[Tuple[int, ...]]:
    try:
        proc = JPopen("juju controllers --format json".split())
        raw = json.loads(proc.stdout.read().decode("utf-8"))
    except FileNotFoundError:
        logger.error("juju not found")
        return None
    current_ctrl = raw["current-controller"]
    agent_version = raw["controllers"][current_ctrl]["agent-version"]
    version = agent_version.split("-")[0]
    return tuple(map(int, version.split(".")))


def get_models(include_controller=False):
    cmd = "juju models --format json"
    proc = JPopen(cmd.split())
    proc.wait()
    data = json.loads(proc.stdout.read().decode("utf-8"))
    if include_controller:
        return [model["short-name"] for model in data["models"]]
    return [
        model["short-name"] for model in data["models"] if not model["is-controller"]
    ]


def show_unit(unit: str, model: str = None):
    _model = f"-m {model} " if model else ""
    proc = JPopen(f"juju show-unit {_model}{unit} --format json".split())
    raw = json.loads(proc.stdout.read().decode("utf-8"))
    return raw[unit]


def show_application(application: str, model: str = None):
    _model = f"-m {model} " if model else ""
    proc = JPopen(f"juju show-application {application} --format json".split())
    raw = json.loads(proc.stdout.read().decode("utf-8"))
    return raw[application]


def get_current_model() -> Optional[str]:
    cmd = "juju models --format json"
    proc = JPopen(cmd.split())
    proc.wait()
    data = json.loads(proc.stdout.read().decode("utf-8"))
    return data.get("current-model", None)


@contextlib.contextmanager
def modify_remote_file(unit: str, path: str):
    # need to create tf in ~ else juju>3.0 scp will break (strict snap)
    with tempfile.NamedTemporaryFile(dir=Path("~").expanduser()) as tf:
        # print(f'fetching remote {path}...')

        cmd = [
            "juju",
            "ssh",
            unit,
            "cat",
            path,
        ]
        buf = check_output(cmd)
        f = Path(tf.name)
        f.write_bytes(buf)

        yield f

        # print(f'copying back modified {path}...')
        cmd = [
            "juju",
            "scp",
            tf.name,
            f"{unit}:{path}",
        ]
        check_call(cmd)


def _push_file_k8s_cmd(
    unit: str,
    local_path: Path,
    remote_path: str,
    is_full_path: bool = False,
    container: Optional[str] = None,
    model: str = None,
):
    container_arg = f" --container {container} " if container else ""
    model_arg = f" -m {model}" if model else ""

    if is_full_path:
        # todo: should we strip the initial / in some cases?
        full_remote_path = remote_path
    else:
        unit_sanitized = unit.replace("/", "-")
        full_remote_path = (
            f"/var/lib/juju/agents/unit-{unit_sanitized}/charm/{remote_path}"
        )
    cmd = f"juju scp{model_arg}{container_arg} {local_path} {unit}:{full_remote_path}"
    return cmd


def _push_file_machine_cmd(
    unit: str,
    local_path: Path,
    remote_path: str,
    is_full_path: bool = False,
    model: str = None,
):
    model_arg = f" -m {model}" if model else ""

    if is_full_path:
        full_remote_path = remote_path
    else:
        unit_sanitized = unit.replace("/", "-")
        full_remote_path = (
            f"/var/lib/juju/agents/unit-{unit_sanitized}/charm/{remote_path}"
        )

    # FIXME:
    #  run this before, and `juju scp` will work.
    #  juju ssh {unit} -- "sudo mkdir -p /root/.ssh; sudo cp /home/ubuntu/.ssh/authorized_keys /root/.ssh/authorized_keys"
    cmd = f"cat {local_path} | juju ssh {unit}{model_arg} sudo -i 'sudo tee {full_remote_path}' > /dev/null"
    return cmd


def push_file(
    unit: str,
    local_path: Path,
    remote_path: str,
    is_full_path: bool = False,
    container: Optional[str] = None,
    model: str = None,
    dry_run: bool = False,
):
    if get_substrate() == "machine":
        cmd = _push_file_machine_cmd(
            unit=unit,
            local_path=local_path,
            remote_path=remote_path,
            is_full_path=is_full_path,
            model=model,
        )
    else:
        cmd = _push_file_k8s_cmd(
            unit=unit,
            local_path=local_path,
            remote_path=remote_path,
            is_full_path=is_full_path,
            container=container,
            model=model,
        )

    if dry_run:
        print(f"would run {cmd}")
        return

    proc = JPopen([cmd], shell=True)
    proc.wait()
    retcode = proc.returncode
    if retcode != 0:
        logger.error(f"{cmd} errored with code {retcode}: ")
        raise RuntimeError(f"Failed to push {local_path} to {unit}.")


def rm_file(unit: str, remote_path: str, model: str = None):
    if remote_path.startswith("/"):
        remote_path = remote_path[1:]
    unit_sanitized = unit.replace("/", "-")
    model_arg = f" -m {model}" if model else ""
    full_remote_path = f"/var/lib/juju/agents/unit-{unit_sanitized}/charm/{remote_path}"
    cmd = f"juju ssh{model_arg} {unit} rm {full_remote_path}"
    try:
        check_output(shlex.split(cmd))
    except CalledProcessError as e:
        raise RuntimeError(
            f"Failed to remove {full_remote_path} from {unit_sanitized}."
        ) from e


def fetch_file(
    unit: str, remote_path: str, local_path: Path = None, model: str = None
) -> Optional[str]:
    unit_sanitized = unit.replace("/", "-")
    model_arg = f" -m {model}" if model else ""
    cmd = (
        f"juju ssh{model_arg} {unit} cat /var/lib/juju/agents/unit-{unit_sanitized}"
        f"/charm/{remote_path}"
    )
    try:
        raw = check_output(cmd.split())
    except CalledProcessError as e:
        raise RuntimeError(
            f"Failed to fetch {remote_path} from {unit_sanitized}."
        ) from e

    if not local_path:
        return raw.decode("utf-8")

    local_path.write_bytes(raw)


LibInfo = namedtuple("LibInfo", "owner, version, lib_name, revision")

JujuVersion = namedtuple("JujuVersion", ("version", "build"))


def juju_version() -> JujuVersion:
    proc = JPopen("juju version".split())
    out = proc.stdout.read().decode("utf-8")
    if "-" in out:
        v, tag = out.split("-", 1)
    else:
        v, tag = out, ""
    return JujuVersion(tuple(map(int, v.split("."))), tag)


def get_local_libinfo(path: Path) -> List[LibInfo]:
    """Get libinfo from local charm project."""

    cmd = f"find {path}/lib -type f " '-iname "*.py" ' r'-exec grep "LIBPATCH" {} \+'
    return _exec_and_parse_libinfo(cmd)


def get_libinfo(app: str, model: str, machine: bool = False) -> List[LibInfo]:
    if machine:
        raise NotImplementedError("machine libinfo not implemented yet.")

    status = cached_juju_status(app, model=model, json=True)
    unit_name = status["applications"][app.split("/")[0]]["units"].popitem()[0]

    if get_substrate(model) == "k8s":
        cwd = "."
    else:
        cwd = "/var/lib/juju"

    cmd = (
        f"juju ssh {unit_name} find {cwd}/agents/unit-{unit_name.replace('/', '-')}/charm/lib "
        "-type f "
        '-iname "*.py" '
        r'-exec grep "LIBPATCH" {} \+'
    )
    return _exec_and_parse_libinfo(cmd)


def _exec_and_parse_libinfo(cmd: str):
    proc = JPopen(shlex.split(cmd))
    out = proc.stdout.read().decode("utf-8")
    libs = out.strip().split("\n")

    libinfo = []
    for lib in libs:
        # todo: if machine, adapt pattern
        # pattern: './agents/unit-zinc-k8s-0/charm/lib/charms/loki_k8s/v0/loki_push_api.py:LIBPATCH = 12'  # noqa
        match = re.search(r".*/charms/(\w+)/v(\d+)/(\w+)\.py\:LIBPATCH\s\=\s(\d+)", lib)
        if match:
            grps = match.groups()
        else:
            logger.error(f"unable to determine libinfo from lib path {lib}")
            continue

        libinfo.append(LibInfo(*grps))

    return libinfo


@dataclass
class Target:
    app: str
    unit: int
    leader: bool = False

    @staticmethod
    def from_name(name: str):
        if "/" not in name:
            logger.warning(
                "invalid target name: expected `<app_name>/<unit_id>`; "
                f"got {name!r}."
            )
        app, unit_ = name.split("/")
        leader = unit_.endswith("*")
        unit = unit_.strip("*")
        return Target(app, unit, leader=leader)

    @property
    def unit_name(self):
        return f"{self.app}/{self.unit}"

    @property
    def charm_root_path(self):
        return Path(f"/var/lib/juju/agents/unit-{self.app}-{self.unit}/charm")

    def __hash__(self):
        return hash((self.app, self.unit, self.leader))


def get_all_units(model: str = None) -> Sequence[Target]:
    status = juju_status(json=True, model=model)
    # sub charms don't have units or applications
    units = list(
        chain(*(_get_units(app, status) for app in status.get("applications", {})))
    )
    return tuple(map(Target.from_name, units))


def _get_units(app, status, predicate: Optional[Callable] = None):
    units = []
    principals = status["applications"][app].get("subordinate-to", False)
    if principals:
        # sub charm = one unit per principal unit
        for principal in principals:
            if predicate and not predicate(principal):
                continue
            machines = [
                u["machine"]
                for u in status["applications"][principal]["units"].values()
            ]
            units.extend(f"{app}/{machine}" for machine in machines)

    else:
        for k, meta in status["applications"][app]["units"].items():
            if predicate and not predicate(meta):
                continue
            units.append(k)
    return units


def get_units(*apps, model: str = None) -> Sequence[Target]:
    status = juju_status(json=True, model=model)
    if not apps:
        apps = status.get("applications", {}).keys()
    units = list(chain(*(_get_units(app, status) for app in apps)))
    return tuple(map(Target.from_name, units))


def get_leader_unit(app, model: str = None) -> Target:
    status = juju_status(json=True, model=model)
    leaders = _get_units(app, status, predicate=lambda unit: unit.get("leader"))
    return Target.from_name(leaders[0])


def parse_target(target: str, model: str = None) -> List[Target]:
    unit_targets = []
    if "/" in target:
        prefix, _, suffix = target.rpartition("/")
        if suffix in {"*", "leader"}:
            unit_targets.append(get_leader_unit(prefix, model=model))
        else:
            unit_targets.append(Target.from_name(target))
    else:
        try:
            unit_targets.extend(get_units(target, model=model))
        except KeyError:
            logger.error(
                f"invalid target {target!r}: not an unit, nor an application in model {model or '<the current model>'!r}"
            )
    return unit_targets


def get_notices(unit: str, container_name: str, model: str = None):
    _model = f"{model} " if model else ""
    cmd = f"juju ssh {_model}{unit} curl --unix-socket /charm/containers/{container_name}/pebble.socket http://localhost/v1/notices"
    return json.loads(JPopen(shlex.split(cmd), text=True).stdout.read())["result"]


if __name__ == "__main__":
    print(get_notices("tempo/0", "tempo"))
