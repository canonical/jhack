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
from sys import stdout
from typing import Callable, Dict, List, Literal, Optional, Sequence, Tuple, Union

import typer
import yaml

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


class GetStatusError(RuntimeError):
    """Raised when juju_status fails."""


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
    cmd = f"juju show-model{f' {model}' if model else ''} --format=json"
    proc = JPopen(cmd.split())
    raw = proc.stdout.read().decode("utf-8")
    model_info = jsn.loads(raw)

    if not model:
        model = list(model_info)[0]

    # strip controller prefix
    model_name = model.split(":")[1] if ":" in model else model

    model_type = model_info[model_name]["model-type"]
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
    cmd = f"juju status{' ' + app_name if app_name else ''} --relations"
    if model:
        cmd += f" -m {model}"
    if json:
        cmd += " --format json"
    proc = JPopen(cmd.split())
    raw = proc.stdout.read().decode("utf-8")

    if not raw:
        logger.error(f"{cmd} produced no output.")
        if model:
            logger.error(
                f"This usually means that the model {model!r} you passed does not exist"
            )
        else:
            logger.error("This usually means that the juju client isn't reachable")

        if IS_SNAPPED:
            logger.warning(
                "double-check that the jhack:dot-local-share-juju plug is connected to snapd."
            )

        raise GetStatusError("unable to fetch juju status (see logs)")

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
    cmd = f"juju show-unit {_model}{unit} --format json".split()
    logger.debug(cmd)
    proc = JPopen(cmd)
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


def is_dispatch_aware(unit, model=None) -> bool:
    _model = f" -m {model}" if model else ""
    unit_sanitized = f"unit-{unit.replace('/', '-')}"
    cmd = f"juju ssh{_model} {unit} cat /var/lib/juju/agents/{unit_sanitized}/charm/dispatch"
    logger.debug(f"running {cmd}")
    try:
        check_call(shlex.split(cmd), stdout=PIPE, stderr=PIPE)
        return True
    except CalledProcessError as e:
        if e.returncode == 1:
            return False
        raise e


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
    mkdir_remote: bool = False,
):
    container_arg = f" --container {container}" if container else ""
    model_arg = f" -m {model}" if model else ""

    if is_full_path:
        # todo: should we strip the initial / in some cases?
        full_remote_path = remote_path
    else:
        full_remote_path = charm_root_path(unit) / remote_path

    cmd = f"juju scp{model_arg}{container_arg} {local_path} {unit}:{full_remote_path}"
    if mkdir_remote:
        mkdir_cmd = f"juju ssh{model_arg}{container_arg} {unit} mkdir -p {Path(full_remote_path).parent}"
        return f"{mkdir_cmd} && {cmd}"

    return cmd


def _push_file_machine_cmd(
    unit: str,
    local_path: Path,
    remote_path: str,
    is_full_path: bool = False,
    model: str = None,
    mkdir_remote: bool = False,
):
    model_arg = f" -m {model}" if model else ""

    if is_full_path:
        # todo: should we strip the initial / in some cases?
        full_remote_path = remote_path
    else:
        full_remote_path = charm_root_path(unit) / remote_path

    # FIXME:
    #  run this before, and `juju scp` will work.
    #  juju ssh {unit} -- "sudo mkdir -p /root/.ssh; sudo cp /home/ubuntu/.ssh/authorized_keys
    #  /root/.ssh/authorized_keys"
    cmd = (
        f"cat {local_path} | juju ssh {unit}{model_arg} sudo -i 'sudo tee "
        f"{full_remote_path}' > /dev/null"
    )

    if mkdir_remote:
        mkdir_cmd = (
            f"juju ssh{model_arg} {unit} mkdir -p {Path(full_remote_path).parent}"
        )
        return f"{mkdir_cmd} && {cmd}"

    return cmd


def push_string(
    unit: str,
    text: str,
    remote_path: str,
    is_full_path: bool = False,
    container: Optional[str] = None,
    model: str = None,
    dry_run: bool = False,
    mkdir_remote: bool = False,
):
    with tempfile.NamedTemporaryFile(dir=Path("~").expanduser()) as tf:
        tf_path = Path(tf.name)
        tf_path.write_text(text)
        return push_file(
            unit=unit,
            local_path=tf_path,
            remote_path=remote_path,
            is_full_path=is_full_path,
            container=container,
            model=model,
            dry_run=dry_run,
            mkdir_remote=mkdir_remote,
        )


def push_file(
    unit: str,
    local_path: Path,
    remote_path: str,
    is_full_path: bool = False,
    container: Optional[str] = None,
    model: str = None,
    dry_run: bool = False,
    mkdir_remote: bool = False,
):
    if get_substrate() == "machine":
        cmd = _push_file_machine_cmd(
            unit=unit,
            local_path=local_path,
            remote_path=remote_path,
            is_full_path=is_full_path,
            model=model,
            mkdir_remote=mkdir_remote,
        )
    else:
        cmd = _push_file_k8s_cmd(
            unit=unit,
            local_path=local_path,
            remote_path=remote_path,
            is_full_path=is_full_path,
            container=container,
            model=model,
            mkdir_remote=mkdir_remote,
        )

    if dry_run:
        print(f"would run {cmd}")
        return

    proc = JPopen([cmd], shell=True)
    proc.wait()
    retcode = proc.returncode
    if retcode != 0:
        logger.error(f"{cmd} errored with code {retcode}: ")
        raise RuntimeError(
            f"Failed to push {local_path} to {unit} with {cmd!r}."
            + (
                " (verify that the path is readable by the jhack snap)"
                if IS_SNAPPED
                else ""
            )
        )


def rm_file(
    unit: str,
    remote_path: str,
    model: str = None,
    is_path_relative=True,
    dry_run=False,
    force: bool = False,
    sudo: bool = False,
):
    if is_path_relative:
        if remote_path.startswith("/"):
            remote_path = remote_path[1:]
        full_remote_path = charm_root_path(unit) / remote_path
    else:
        full_remote_path = remote_path

    model_arg = f" -m {model}" if model else ""
    sudo_arg = " sudo" if sudo else ""
    cmd = f"juju ssh{model_arg} {unit}{sudo_arg} rm{' -f' if force else ''} {full_remote_path}"
    if dry_run:
        print(f"would run: {cmd}")
        return
    try:
        check_output(shlex.split(cmd))
    except CalledProcessError as e:
        raise RuntimeError(f"Failed to remove {full_remote_path} from {unit}.") from e


def fetch_file(
    unit: str,
    remote_path: Union[Path, str],
    local_path: Optional[Union[Path, str]] = None,
    model: str = None,
) -> Optional[str]:
    model_arg = f" -m {model}" if model else ""
    charm_path = charm_root_path(unit) / remote_path
    cmd = f"juju ssh{model_arg} {unit} cat {charm_path}"
    try:
        raw = subprocess.run(
            shlex.split(cmd), text=True, capture_output=True, check=True
        ).stdout
    except CalledProcessError:
        logger.debug(f"error fetching {charm_path} from {unit}@{model}:", exc_info=True)
        raise RuntimeError(f"Failed to fetch {charm_path} from {unit}.")

    if not local_path:
        return raw

    Path(local_path).write_text(raw)


LibInfo = namedtuple("LibInfo", "owner, version, lib_name, revision")
EndpointInfo = namedtuple("Endpoint", ("description", "required"))

JujuVersion = namedtuple("JujuVersion", ("version", "build"))


def juju_version() -> JujuVersion:
    proc = JPopen("juju version".split())
    out = proc.stdout.read().decode("utf-8")
    if "-" in out:
        v, tag = out.split("-", 1)
    else:
        v, tag = out, ""
    return JujuVersion(tuple(map(int, v.split("."))), tag)


def charm_root_path(unit_name: str) -> Path:
    """Get the root path of the charm in a juju unit."""
    return Path(f"/var/lib/juju/agents/unit-{unit_name.replace('/', '-')}/charm/")


def get_local_libinfo(path: Path) -> List[LibInfo]:
    """Get libinfo from local charm project."""

    cmd = f"find {path}/lib -type f " '-iname "*.py" ' r'-exec grep "LIBPATCH" {} \+'
    return _exec_and_parse_libinfo(cmd)


def pull_metadata(unit: str, model: str):
    """Get metadata.yaml from this target."""
    logger.info("fetching metadata...")

    meta_path = "metadata.yaml"
    charmcraft_path = "charmcraft.yaml"
    with tempfile.NamedTemporaryFile(dir=Path("~").expanduser()) as tf:
        try:
            fetch_file(unit, meta_path, tf.name, model=model)
        except RuntimeError:
            try:
                fetch_file(unit, charmcraft_path, tf.name, model=model)
            except RuntimeError as e:
                raise RuntimeError(
                    f"cannot find charmcraft nor metadata in {unit}"
                ) from e

        return yaml.safe_load(Path(tf.name).read_text())


def get_epinfo(app_or_unit: str, model: str) -> Dict[str, Dict[str, EndpointInfo]]:
    # returns a mapping from role to endpoint name to endpoint info
    if "/" in app_or_unit:
        unit = app_or_unit
    else:
        app = app_or_unit
        status = cached_juju_status(app, model=model, json=True)
        try:
            unit = next(iter(status["applications"][app]["units"]))
        except StopIteration:
            logger.error(f"app {app} has no units: cannot fetch endpoint info")
            return {}

    meta = pull_metadata(unit, model)
    out = {}
    for role in ("provides", "requires", "peers"):
        out[role] = {
            ep_name: EndpointInfo(
                ep_meta.get("description", ""),
                ep_meta.get("required", not ep_meta.get("optional", True)),
            )
            for ep_name, ep_meta in meta.get(role, {}).items()
        }
    return out


def get_libinfo(app: str, model: str, machine: bool = False) -> List[LibInfo]:
    if machine:
        raise NotImplementedError("machine libinfo not implemented yet.")

    status = cached_juju_status(app, model=model, json=True)
    try:
        unit = next(iter(status["applications"][app]["units"]))
    except StopIteration:
        logger.error(f"app {app} has no units: cannot fetch endpoint info")
        return []

    cmd = (
        f"juju ssh {unit} find {charm_root_path(unit)}/lib "
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


class InvalidUnitNameError(RuntimeError):
    """Unit name is invalid."""


@dataclass
class Target:
    app: str
    unit: int
    leader: bool = False
    _machine_id: Optional[int] = None

    @staticmethod
    def from_name(name: str):
        try:
            app, unit_ = name.split("/")
        except ValueError:
            raise InvalidUnitNameError(
                f"invalid target name: expected `<app_name>/<unit_id>`; got {name!r}."
            )

        leader = unit_.endswith("*")
        unit = unit_.strip("*")
        if not unit or not unit.isdigit():
            raise InvalidUnitNameError(
                f"invalid target name: expected `<app_name:str>/<unit_id:int>`; got {name!r}."
            )
        return Target(app, int(unit), leader=leader)

    @property
    def unit_name(self):
        return f"{self.app}/{self.unit}"

    @property
    def charm_root_path(self):
        return charm_root_path(self.unit_name)

    def __hash__(self):
        return hash((self.app, self.unit, self.leader))

    @property
    def machine_id(self) -> int:
        if self._machine_id is None:
            raise ValueError(
                "machine-id not available. Either a k8s unit, or it wasn't obtained "
                "at Target instantiation time."
            )
        return self._machine_id


def get_all_units(model: str = None) -> Tuple[Target, ...]:
    status = juju_status(json=True, model=model)
    # sub charms don't have units or applications
    return tuple(
        chain(*(_get_units(app, status) for app in status.get("applications", {})))
    )


def _get_units(
    app,
    status,
    predicate: Optional[Callable] = None,
) -> Sequence[Target]:
    units = []
    principals = status["applications"][app].get("subordinate-to", False)
    if principals:
        # sub charm = one unit per principal unit
        for principal in principals:
            if predicate and not predicate(principal):
                continue

            # if the principal is still being set up, it could have no 'units' yet.
            for unit_id, unit_meta in (
                status["applications"][principal].get("units", {}).items()
            ):
                unit = int(unit_id.split("/")[1])
                units.append(
                    Target(
                        app=app,
                        unit=unit,
                        _machine_id=unit_meta.get("machine"),
                        leader=unit_meta.get("leader"),
                    )
                )

    else:
        for unit_id, unit_meta in status["applications"][app]["units"].items():
            if predicate and not predicate(unit_meta):
                continue
            unit = int(unit_id.split("/")[1])
            units.append(
                Target(
                    app=app,
                    unit=unit,
                    _machine_id=unit_meta.get("machine"),
                    leader=unit_meta.get("leader"),
                )
            )
    return units


def get_units(*apps, model: str = None) -> Sequence[Target]:
    status = juju_status(json=True, model=model)
    if not apps:
        apps = status.get("applications", {}).keys()
    return list(chain(*(_get_units(app, status) for app in apps)))


def get_leader_unit(app, model: str = None) -> Optional[Target]:
    status = juju_status(json=True, model=model)
    leaders = _get_units(app, status, predicate=lambda unit: unit.get("leader"))
    return leaders[0] if leaders else None


def parse_target(target: str, model: str = None) -> List[Target]:
    if target == "*":
        return list(get_units(model=model))

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
                f"invalid target {target!r}: not an unit, nor an application in model "
                f"{model or '<the current model>'!r}"
            )
    return unit_targets


def get_notices(unit: str, container_name: str, model: str = None):
    _model = f"{model} " if model else ""
    cmd = (
        f"juju ssh {_model}{unit} curl --unix-socket /charm/containers/{container_name}"
        f"/pebble.socket http://localhost/v1/notices"
    )
    return json.loads(JPopen(shlex.split(cmd), text=True).stdout.read())["result"]


def get_checks(unit: str, container_name: str, model: str = None):
    _model = f"{model} " if model else ""
    cmd = (
        f"juju ssh {_model}{unit} curl --unix-socket /charm/containers/{container_name}"
        f"/pebble.socket http://localhost/v1/checks"
    )
    return json.loads(JPopen(shlex.split(cmd), text=True).stdout.read())["result"]


def get_secrets(model: str = None) -> dict:
    _model = f"{model} " if model else ""
    cmd = f"juju secrets {_model} --format=json"
    return json.loads(JPopen(shlex.split(cmd), text=True).stdout.read())


def show_secret(secret_id, model: str = None) -> dict:
    _model = f"{model} " if model else ""
    cmd = f"juju show-secret {_model} {secret_id} --format=json"
    return json.loads(JPopen(shlex.split(cmd), text=True).stdout.read())


def find_leaders(targets: List[str] = None, model: Optional[str] = None):
    """Find the leader units for these applications"""
    status = juju_status(model=model, json=True)
    if not status:
        logger.error(f"`juju status -m {model}` returned an empty response.")
        return {}

    if not status.get("applications"):
        logger.error(
            "no applications in the current model: cannot find leaders. "
            "Is the model still bootstrapping?"
        )
        return {}

    apps = (
        set(t.split("/")[0] for t in targets)
        if targets
        else list(status.get("applications", []))
    )

    leaders = {}
    for app in apps:
        units = status["applications"].get(app, {}).get("units", {})
        leaders_found = [unit for unit, meta in units.items() if meta.get("leader")]
        if not leaders_found:
            logger.debug(f"leader not found for {app!r} (not elected yet?)")
            continue
        leaders[app] = leaders_found[0]
    return leaders


def get_venv_location(unit: str, model: Optional[str] = None):
    """Charms that were built with the UV plugin have their venv in a different place.

    Since the charm itself contains no indication as to whether it was built with uv,
    and where its venv is, we have to do some hacky guesswork.
    """
    try:
        fetch_file(unit, "./venv/ops/main.py", model=model)
        return "venv"
    except RuntimeError:
        logger.debug("uv charm detected")

    # determine python version:
    _model = f" --model {model}" if model else ""
    charm_root_path = Target.from_name(unit).charm_root_path
    cmd = f"juju ssh {unit}{_model} {charm_root_path}/venv/bin/python --version"
    out = subprocess.run(
        shlex.split(cmd),
        text=True,
        capture_output=True,
    ).stdout
    # out looks like: "Python 3.12.3", we want "3.12"
    python_version = ".".join(out.split()[1].split(".")[:-1])
    return f"{charm_root_path}/venv/lib/python{python_version}/site-packages"


if __name__ == "__main__":
    print(find_leaders())
