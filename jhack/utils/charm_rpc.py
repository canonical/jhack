import shlex
from pathlib import Path
from subprocess import run
from typing import Optional

import typer

from jhack.helpers import push_file, rm_file
from jhack.utils.tail_charms import Target
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("crpc")


def charm_rpc(
    target: str = typer.Argument(..., help="Target unit or database file."),
    script: Path = typer.Argument(
        ..., help="Path to a python script to be executed in the charm context."
    ),
    entrypoint: str = typer.Option(
        "main",
        "-e",
        "--entrypoint",
        help="Name of a function defined in the script. "
        "Must take a charm instance as only positional argument.",
    ),
    crpc_module_name: str = typer.Option(
        "crpc_mod",
        help="Name of the (temporary) file containing the script "
        "that will be created on the charm.",
    ),
    crpc_dispatch_name: str = typer.Option(
        "crpc_dispatch",
        help="Name of the (temporary) file containing the dispatch script.",
    ),
    model: str = typer.Option(
        None, "-m", "--model", help="Which model to apply the command to."
    ),
    cleanup: bool = typer.Option(
        True,
        help="Remove all files created onto the unit when you're done.",
        is_flag=True,
    ),
):
    """Executes a function defined in a local python script onto a live Juju unit,
    passing to it the charm instance.

    Example:
        $ echo "def main(charm):\n    print("welcome to", charm.unit.name)" > crpc.py
        $ jhack crpc myapp/1 crpc.py
         --> welcome to myapp/1
    """

    _charm_rpc(
        target=target,
        script=script,
        entrypoint=entrypoint,
        crpc_module_name=crpc_module_name,
        crpc_dispatch_name=crpc_dispatch_name,
        model=model,
        cleanup=cleanup,
    )


def _charm_rpc(
    target: str,
    script: Path,
    entrypoint: str,
    crpc_module_name: str,
    crpc_dispatch_name: str,
    model: str,
    cleanup: bool,
):

    """Rpc local script on live charm.

    1. uploads a local script to a charm unit
    2. executes dispatch on a patched init script so the charm is set up and passed to
        the script's entrypoint instead of being passed to ops.main standard event loop
    3. cleans up
    """

    if not script.exists():
        raise FileNotFoundError(script)

    target = Target.from_name(target)

    # TODO: we could attempt to load the module and verify the signature of the entrypoint now
    logger.info(f"pushing crpc module {script}...")
    remote_rpc_module_path = f"src/{crpc_module_name}.py"
    push_file(target.unit_name, script, remote_rpc_module_path, model=model)

    logger.info(f"pushing crpc dispatch script...")
    remote_rpc_dispatch_path = f"src/{crpc_dispatch_name}.py"
    dispatch = Path(__file__).parent / ".charm_rpc_dispatch.py"
    push_file(target.unit_name, dispatch, remote_rpc_dispatch_path, model=model)

    logger.info(f"preparing environment...")
    env = " ".join(
        f"{key}={val}"
        for key, val in {
            "CHARM_RPC_MODULE_NAME": crpc_module_name,
            "CHARM_RPC_ENTRYPOINT": entrypoint,
            "CHARM_RPC_SCRIPT_NAME": script.name,
            "PYTHONPATH": "lib:venv",
        }.items()
    )

    logger.info(f"executing crpc...")
    exec_dispatch_cmd = f"juju exec --unit {target.unit_name} -- {env} python3 ./src/{crpc_dispatch_name}.py"

    run(shlex.split(exec_dispatch_cmd))

    if cleanup:
        logger.info("cleaning up...")
        try:
            rm_file(target.unit_name, remote_rpc_module_path, model=model)
            rm_file(target.unit_name, remote_rpc_dispatch_path, model=model)
        except RuntimeError as e:
            logger.warning(f"cleanup FAILED with {e}")
