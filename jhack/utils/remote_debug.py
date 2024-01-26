import shlex
import tempfile
from pathlib import Path

import typer

from jhack.helpers import get_substrate, JPopen
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("endpoints")


def _upload_text(text: str, target: str, remote_path: str):
    # use a prefix that juju can 'see' despite the snap confinement!
    with tempfile.NamedTemporaryFile(
        dir=Path("~/.local/share/juju/").expanduser(), prefix=".jhack_tmp_"
    ) as f:
        Path(f.name).write_text(text)
        # upload script to charm
        proc = JPopen(shlex.split(f"juju scp {f.name} {target}:./{remote_path}"))
        proc.wait()

        if proc.returncode != 0:
            exit(
                f"failed uploading to {remote_path};"
                f"\n stdout={proc.stdout.read()},"
                f"\n stderr={proc.stderr.read()}"
            )


def _setup_remote_debug(
    target: str, listen_address: str = "localhost:5678", debugpy_version: str = "1.8.0"
):
    sanitized_unit_name = target.replace("/", "-")
    install_script_name = "install_debugpy.sh"

    if get_substrate() == "k8s":
        logger.debug("detected kubernetes env")

        install_debugpy_script = f"""#!/bin/bash
            f.name
            cd ./agents/unit-{sanitized_unit_name}/charm/venv
            curl -LO https://github.com/microsoft/debugpy/archive/refs/tags/v{debugpy_version}.zip
            apt update -y
            apt install unzip -y
            unzip ./v{debugpy_version}.zip
            rm ./v{debugpy_version}.zip
            mv ./debugpy-{debugpy_version}/src/debugpy/ ./debugpy
            """

        logger.info("uploading install script...")
        _upload_text(install_debugpy_script, target, f"./{install_script_name}")

        logger.info("installing... (this may take a little while)")

        # need to make it executable, else juju agent might have trouble later
        chmod_x_proc = JPopen(
            shlex.split(f"juju ssh {target} chmod +x ./{install_script_name}")
        )
        chmod_x_proc.wait()

        proc = JPopen(shlex.split(f"juju ssh {target} bash ./{install_script_name}"))
        proc.wait()
        # proc = JPopen(shlex.split(f"juju ssh {target} ./{install_script_name}"))
        # proc.wait()

        if proc.returncode != 0:
            exit(
                f"failed executing install script \n stdout={proc.stdout.read()} \n stderr={proc.stderr.read()}",
            )

    else:
        raise NotImplementedError("not implemented yet for lxd")

    # let's patch dispatch!
    logger.info("patching dispatch script... (dis-patch or dat-patch?)")
    new_dispatch_script = """#!/bin/sh                                  
    # Dispatch injected by jhack's remote-debug tool
                                                                                    
    JUJU_DISPATCH_PATH="${JUJU_DISPATCH_PATH:-$0}" PYTHONPATH=lib:venv:$PYTHONPATH \    
    python3 -m debugpy --listen {listen_address} ./src/charm.py
    """.replace(
        "listen_address", listen_address
    )

    _upload_text(
        new_dispatch_script,
        target,
        "./agents/unit-{sanitized_unit_name}/charm/dispatch",
    )

    logger.info("debugpy installed on dispatch.")


def remote_debug(
    target: str = typer.Argument(..., help="Juju unit name you want to target."),
    debugpy_version: str = typer.Option(
        "1.8.0",
        "--debugpy-version",
        "-d",
        help="Debugpy version to install. See on https://github.com/microsoft/debugpy/releases "
        "which tags are available.",
    ),
    listen_address: str = typer.Option(
        "localhost:5678",
        "--listen-address",
        "-l",
        help="host:port at which the debugpy server will be listening. Has to match your local "
        "debugger client configuration.",
    ),
):
    """Set up a remote debugging server (debugpy) on a juju unit.

    Once this is done, you can connect an interactive debugging session from (for example) vscode.
    """
    _setup_remote_debug(target, listen_address, debugpy_version)


if __name__ == "__main__":
    _setup_remote_debug("traefik/0")
