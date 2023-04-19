import csv
import subprocess
import toml
from json import dumps as json_dumps, loads as json_loads
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
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


def print_env(json: bool = typer.Option(False, is_flag=True)):
    """Print the details of the juju environment for use in bug reports."""
    pyproject_toml = Path(__file__).parent.parent.parent.absolute().joinpath('pyproject.toml')
    jhack_version = toml.loads(pyproject_toml.read_text())['project']['version']

    juju_version = get_output("juju --version")
    mk8s_version = get_output("microk8s version")
    lxd_version = get_output("lxd --version")
    multipass_version = get_output("multipass version --format json")
    if multipass_version:
        multipass_version = json_loads(multipass_version)
    else:
        multipass_version = {}
    os_version = get_os_release()["PRETTY_NAME"]
    kernel_info = get_output("uname -srp")

    data = {
        'jhack': jhack_version,
        'juju': juju_version,
        'microk8s': mk8s_version,
        'lxd': lxd_version,
        'multipass': multipass_version.get('multipass', None),
        'multipassd': multipass_version.get('multipassd', None),
        'os': os_version,
        'kernel': kernel_info,
    }

    if json:
        jsn = json_dumps(data, indent=2)
        print(jsn)

    else:
        table = Table(title="juju info v0.1", show_header=False)
        for k, v in data.items():
            table.add_row(k, v or NOT_INSTALLED)
        Console().print(table)


if __name__ == '__main__':
    print_env(False)
