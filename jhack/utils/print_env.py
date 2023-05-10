import csv
import subprocess
import sys
from json import dumps as json_dumps
from json import loads as json_loads
from pathlib import Path
from typing import Optional

import requests_unixsocket
import toml
from rich.console import Console
from rich.table import Table

from jhack.config import IS_SNAPPED
from jhack.helpers import Format, FormatOption
from jhack.logger import logger as jhack_logger

NOT_INSTALLED = "Not Installed."
logger = jhack_logger.getChild(__name__)


def get_output(command: str) -> Optional[str]:
    try:
        p = subprocess.run(command.split(), capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None
    except subprocess.CalledProcessError as e:
        logger.info(e)
        return None


def get_os_release():
    with open("/etc/os-release") as f:
        return dict(csv.reader(f, delimiter="="))


def _gather_juju_snaps_versions(format: Format = FormatOption):
    url = "http+unix://%2Frun%2Fsnapd.socket/v2/snaps"

    try:
        snap_info = requests_unixsocket.get(url)
        snap_info.raise_for_status()
        local_snaps = snap_info.json()["result"]
    except ConnectionError:
        local_snaps = []

    versions = {
        snap["name"]: f"{snap['version']} - {snap['revision']} ({snap['channel']})"
        for snap in local_snaps
        if snap["name"].startswith("juju")
    }

    if format == Format.json:
        return versions
    table = Table(
        show_header=False, show_edge=False, show_lines=False, show_footer=False
    )

    for k, v in versions.items():
        table.add_row(k, v)

    return table


def get_jhack_version() -> str:
    if IS_SNAPPED:
        from importlib import metadata

        return metadata.version("jhack")
    else:
        pyproject_toml = (
            Path(__file__).parent.parent.parent.absolute().joinpath("pyproject.toml")
        )
        return toml.loads(pyproject_toml.read_text())["project"]["version"]


def get_multipass_version():
    """Multipass --version."""
    try:
        multipass_version = get_output("multipass version --format json")
    except subprocess.CalledProcessError:
        logger.info("multipass not found")
        multipass_version = None
    multipass_version = json_loads(multipass_version) if multipass_version else {}
    return multipass_version


def print_env(format: Format = FormatOption):
    """Print the details of the juju environment for use in bug reports."""
    python_v = sys.version_info
    python_version = (
        f"{python_v.major}.{python_v.minor}.{python_v.micro} ({sys.executable})"
    )

    multipass_version = get_multipass_version()
    data = {
        "jhack": get_jhack_version(),
        "python": python_version,
        "juju-* snaps": _gather_juju_snaps_versions(format=format),
        "microk8s": get_output("microk8s version") or NOT_INSTALLED,
        "lxd": get_output("lxd --version") or NOT_INSTALLED,
        "multipass": multipass_version.get("multipass", NOT_INSTALLED),
        "multipassd": multipass_version.get("multipassd", NOT_INSTALLED),
        "os": get_os_release()["PRETTY_NAME"],
        "kernel": get_output("uname -srp"),
    }

    if format == Format.json:
        jsn = json_dumps(data, indent=2)
        print(jsn)

    else:
        table = Table(title="juju info v0.1", show_header=False)
        for k, v in data.items():
            table.add_row(k, v)
        Console().print(table)


if __name__ == "__main__":
    print_env(False)
