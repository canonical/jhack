import contextlib
import json
import json as jsn
import os
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from itertools import chain
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_call, check_output
from typing import Iterable, List, Literal, Optional, Sequence, Tuple

import typer

from jhack.config import IS_SNAPPED
from jhack.logger import logger

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


def _JPopen(args: Tuple[str], wait: bool, **kwargs):  # noqa
    # Env-passing-down Popen
    proc = subprocess.Popen(
        args,
        env=kwargs.get("env", os.environ),
        stderr=kwargs.get("stderr", PIPE),
        stdout=kwargs.get("stdout", PIPE),
        **kwargs,
    )
    if wait:
        proc.wait()

    # this will presumably only ever branch if wait==True
    if proc.returncode not in {0, None}:
        msg = f"failed to invoke juju command ({' '.join(args)!r}, {kwargs}); exited with {proc.returncode}"
        if IS_SNAPPED and "ssh client keys" in proc.stderr.read().decode("utf-8"):
            msg += (
                " If you see an ERROR above saying something like "
                "'open ~/.local/share/juju/ssh: permission denied',"
                "you might have forgotten to "
                "'sudo snap connect jhack:dot-local-share-juju snapd'"
            )
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


def is_k8s_model(status=None):
    status = status or juju_status(json=True)
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
        proc = JPopen(f"juju controllers --format json".split())
        raw = json.loads(proc.stdout.read().decode("utf-8"))
    except FileNotFoundError:
        logger.error("juju not found")
        return None
    current_ctrl = raw["current-controller"]
    agent_version = raw["controllers"][current_ctrl]["agent-version"]
    version = agent_version.split("-")[0]
    return tuple(map(int, version.split(".")))


def get_models(include_controller=False):
    cmd = f"juju models --format json"
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
    cmd = f"juju models --format json"
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


def fetch_file(
    unit: str, remote_path: str, local_path: Path = None, model: str = None
) -> Optional[str]:
    unit_sanitized = unit.replace("/", "-")
    model_arg = f" -m {model}" if model else ""
    cmd = f"juju ssh{model_arg} {unit} cat /var/lib/juju/agents/unit-{unit_sanitized}/charm/{remote_path}"
    try:
        raw = check_output(cmd.split())
    except CalledProcessError as e:
        raise RuntimeError(
            f"Failed to fetch {remote_path} from {unit_sanitized}."
        ) from e

    if not local_path:
        return raw.decode("utf-8")

    local_path.write_bytes(raw)


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

    def __hash__(self):
        return hash((self.app, self.unit, self.leader))


def get_all_units(
    model: str = None, filter_apps: Iterable[str] = None
) -> Sequence[Target]:
    def _filter(app):
        if filter_apps:
            return app in filter_apps
        return True

    status = juju_status(json=True, model=model)
    # sub charms don't have units or applications
    units = list(
        chain(
            *(
                app.get("units", ())
                for app_name, app in status.get("applications", {}).items()
                if _filter(app_name)
            )
        )
    )
    return tuple(map(Target.from_name, units))
