import contextlib
import json
import json as jsn
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_output
from typing import List, Literal, Optional, Tuple

import typer
from juju.model import Model

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


def get_models():
    cmd = f"juju models --format json"
    proc = JPopen(cmd.split())
    proc.wait()
    data = json.loads(proc.stdout.read().decode("utf-8"))
    return data


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


@contextlib.asynccontextmanager
async def get_current_model() -> Model:
    model = Model()
    try:
        # connect to the current model with the current user, per the Juju CLI
        await model.connect()
        yield model

    finally:
        if model.is_connected():
            print("Disconnecting from model")
            await model.disconnect()


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
        env=kwargs.pop("env", os.environ),
        stderr=kwargs.pop("stderr", PIPE),
        stdout=kwargs.pop("stdout", PIPE),
        **kwargs,
    )
    if wait:
        proc.wait()

    # this will presumably only ever branch if wait==True
    if proc.returncode not in {0, None}:
        msg = f"failed to invoke juju command ({args}, {kwargs})"
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
def juju_agent_version() -> Tuple[int, ...]:
    proc = JPopen(f"juju controllers --format json".split())
    raw = json.loads(proc.stdout.read().decode("utf-8"))
    current_ctrl = raw["current-controller"]
    agent_version = raw["controllers"][current_ctrl]["agent-version"]
    version = agent_version.split("-")[0]
    return tuple(map(int, version.split(".")))


def juju_models() -> str:
    proc = JPopen(f"juju models".split())
    return proc.stdout.read().decode("utf-8")


def show_unit(unit: str):
    proc = JPopen(f"juju show-unit {unit} --format json".split())
    raw = json.loads(proc.stdout.read().decode("utf-8"))
    return raw[unit]


def show_application(application: str):
    proc = JPopen(f"juju show-application {application} --format json".split())
    raw = json.loads(proc.stdout.read().decode("utf-8"))
    return raw[application]


def list_models(strip_star=False) -> List[str]:
    raw = juju_models()
    lines = raw.split("\n")[3:]
    models = filter(None, (line.split(" ")[0] for line in lines))
    if strip_star:
        return [name.strip("*") for name in models]
    return models


def current_model() -> str:
    all_models = list_models()
    key = lambda name: name.endswith("*")
    return next(filter(key, all_models)).strip("*")


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
        buf = subprocess.check_output(cmd)
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
        subprocess.check_call(cmd)


def fetch_file(
    unit: str, remote_path: str, local_path: Path = None, model: str = None
) -> Optional[str]:
    unit_sanitized = unit.replace("/", "-")
    model_arg = f" -m {model}" if model else ""
    cmd = f"juju ssh{model_arg} {unit} sudo cat /var/lib/juju/agents/unit-{unit_sanitized}/charm/{remote_path}"
    try:
        raw = check_output(cmd.split())
    except CalledProcessError as e:
        raise RuntimeError(
            f"Failed to fetch {remote_path} from {unit_sanitized}."
        ) from e

    if not local_path:
        return raw.decode("utf-8")

    local_path.write_bytes(raw)
