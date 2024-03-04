import inspect
import os
import select
import shlex
import sys
import tempfile
from functools import partial
from importlib.util import module_from_spec, spec_from_file_location
from multiprocessing import Pool
from pathlib import Path
from subprocess import run
from typing import List

import typer

from jhack.helpers import juju_status, push_file, rm_file
from jhack.logger import logger as jhack_logger
from jhack.utils.simulate_event import build_event_env
from jhack.utils.tail_charms import Target

logger = jhack_logger.getChild("crpc")


def charm_rpc(
    target: str = typer.Argument(
        ...,
        help="Target unit or application name. "
        "Using an application name will run the script on all units.",
    ),
    script: Path = typer.Option(
        None,
        "-i",
        "--input",
        help="Path to a python script to be executed in the charm context."
        "If not provided, we'll take STDIN.",
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
    validate: bool = typer.Option(
        True,
        help="Attempt to load the entrypoint from the crpc script to validate its signature.",
        is_flag=True,
    ),
    env_override: List[str] = typer.Option(
        None,
        "--env",
        help="Key-value mapping to override any ENV with. For whatever reason."
        "E.g."
        " --event foo-pebble-ready --env JUJU_DEPARTING_UNIT_NAME=remote/0 --env FOO=bar",
    ),
    event: str = typer.Option(
        "charm-rpc",
        "--event",
        help="The name of an event whose context to simulate. "
        "Needs to be a valid event name for the unit; e.g. \n"
        " - 'start' \n"
        " - 'config-changed' \n"
        " - 'my-relation-name-relation-joined' # write it out in full",
    ),
):
    """Executes a function defined in a local python script onto a live Juju unit,
    passing to it the charm instance.

    Example:
        $ echo "def main(charm):\n    print("welcome to", charm.unit.name)" > crpc.py
        $ jhack crpc myapp/1 crpc.py
         --> welcome to myapp/1

    By default, it sets up a generic hook environment (no event-type-specific envvars are set up).
    Essentially identical to running the script in the context of an ``update-status`` event.
    If you want to execute the script in the context of a specific event, you can use the
    ``--event`` option.
    """

    _charm_rpc(
        target=target,
        script=script,
        entrypoint=entrypoint,
        crpc_module_name=crpc_module_name,
        crpc_dispatch_name=crpc_dispatch_name,
        model=model,
        cleanup=cleanup,
        validate=validate,
        env_override=env_override,
        event=event,
    )


class InvalidScriptOrEntrypointError(Exception):
    """Raised if script or entrypoint are invalid."""


def verify_signature(script, entrypoint):
    logger.debug(f"verifying signature of {script}::{entrypoint}")

    spec = spec_from_file_location(script.name, str(script.absolute()))
    try:
        module = module_from_spec(spec)
    except AttributeError:
        logger.debug(f"failed to import {script}; signature verification skipped")
        return

    spec.loader.exec_module(module)

    try:
        entrypoint = getattr(module, entrypoint)
    except AttributeError as e:
        raise InvalidScriptOrEntrypointError(
            f"identifier {entrypoint} not found in {module}."
        ) from e

    sig = inspect.signature(entrypoint)
    params = list(sig.parameters.values())
    if not (len(params) == 1 and params[0].name == "charm"):
        raise InvalidScriptOrEntrypointError(
            f"The crpc entrypoint {entrypoint!r} has the wrong signature. "
            "It needs to take a single positional argument called 'charm'. This will be a "
            "subclass of `ops.CharmBase`."
        )

    logger.debug(f"{script}::{entrypoint} signature OK")


def _charm_rpc(
    target: str,
    script: Path,
    entrypoint: str,
    crpc_module_name: str,
    crpc_dispatch_name: str,
    model: str,
    cleanup: bool,
    validate: bool,
    event: str,
    env_override: List[str],
):
    """Rpc local script on live charm.

    1. uploads a local script to a charm unit
    2. executes dispatch on a patched init script so the charm is set up and passed to
        the script's entrypoint instead of being passed to ops.main standard event loop
    3. cleans up
    """
    if script is None:
        tf = tempfile.NamedTemporaryFile(dir=Path("~").expanduser())
        f = Path(tf.name)

        # from https://stackoverflow.com/questions/3762881/how-do-i-check-if-stdin-has-some-data
        stdin_has_data = select.select(
            [
                sys.stdin,
            ],
            [],
            [],
            0.0,
        )[0]
        if not stdin_has_data:
            raise RuntimeError("no script provided in stdin or as `--input`.")

        stdin = sys.stdin.read()
        f.write_text(stdin)
        script = f

    if not script.exists():
        raise FileNotFoundError(script)

    if validate:
        try:
            verify_signature(script, entrypoint)
        except Exception as e:
            logger.debug(e, exc_info=True)
            logger.error(
                f"encountered exception while verifying entrypoint signature... {e}"
                f"Proceeding..."
            )

    targets = []
    if "/" not in target:
        # app name received. run on all units.
        status = juju_status(app_name=target, model=model, json=True)
        targets.extend(
            Target.from_name(u) for u in status["applications"][target]["units"]
        )

    else:
        targets.append(Target.from_name(target))

    with Pool(len(targets)) as pool:
        logger.debug(f"initiating async crpc calls to {targets}")
        pool.map(
            partial(
                _exec_crpc_script,
                script=script,
                entrypoint=entrypoint,
                crpc_module_name=crpc_module_name,
                crpc_dispatch_name=crpc_dispatch_name,
                model=model,
                cleanup=cleanup,
                event=event,
                env_override=env_override,
            ),
            targets,
        )


def _exec_crpc_script(
    target: Target,
    script: Path,
    entrypoint: str,
    crpc_module_name: str,
    crpc_dispatch_name: str,
    model: str,
    cleanup: bool,
    event: str,
    env_override: List[str],
):
    logger.info(f"pushing crpc module {script}...")
    remote_rpc_module_path = f"src/{crpc_module_name}.py"
    push_file(target.unit_name, script, remote_rpc_module_path, model=model)

    logger.info("pushing crpc dispatch script...")
    remote_rpc_dispatch_path = f"src/{crpc_dispatch_name}.py"
    dispatch = Path(__file__).parent / ".charm_rpc_dispatch.py"
    push_file(target.unit_name, dispatch, remote_rpc_dispatch_path, model=model)

    if event or env_override:
        evt = event or "charm-rpc"
        logger.info(f"preparing environment for event {evt!r}...")
        crpc_env = build_event_env(
            target.unit_name, evt, override=env_override, model=model
        )
    else:
        logger.info("setting up generic event context...")
        crpc_env = "JUJU_DISPATCH_PATH=charm-rpc"

    env = " ".join(
        f"{key}={val}"
        for key, val in {
            "CHARM_RPC_ENV": crpc_env,
            "CHARM_RPC_MODULE_NAME": crpc_module_name,
            "CHARM_RPC_ENTRYPOINT": entrypoint,
            "CHARM_RPC_SCRIPT_NAME": script.name,
            "CHARM_RPC_LOGLEVEL": os.getenv("LOGLEVEL", "WARNING"),
            "PYTHONPATH": "lib:venv",
        }.items()
    )

    logger.info("executing crpc...")
    exec_dispatch_cmd = f"juju exec --unit {target.unit_name} -- {env} python3 ./src/{crpc_dispatch_name}.py"

    run(shlex.split(exec_dispatch_cmd))

    if cleanup:
        logger.info("cleaning up...")
        try:
            rm_file(target.unit_name, remote_rpc_module_path, model=model)
            rm_file(target.unit_name, remote_rpc_dispatch_path, model=model)
        except RuntimeError as e:
            logger.warning(f"cleanup FAILED with {e}")
