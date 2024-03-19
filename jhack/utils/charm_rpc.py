import base64
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
from typing import List, Optional

import typer

from jhack.helpers import Target, get_units, push_file, rm_file
from jhack.logger import logger as jhack_logger
from jhack.utils.simulate_event import build_event_env

logger = jhack_logger.getChild("crpc")


def charm_rpc(
    target: str = typer.Argument(
        ...,
        help="Target unit or application name. "
        "Using an application name will run the script on all units.",
    ),
    expr: str = typer.Argument(
        ...,
        help="Path to an object or callable starting from the charm instance. "
        "Can start with ``self.``, or it can be omitted."
        "Examples: \n"
        "- .model.relations['foo']\n"
        "- self.ingress.is_ready\n",
    ),
    model: str = typer.Option(
        None, "-m", "--model", help="Which model to apply the command to."
    ),
    cleanup: bool = typer.Option(
        True,
        help="Remove all files created onto the unit when you're done.",
        is_flag=True,
    ),
    crpc_dispatch_name: str = typer.Option(
        "crpc_dispatch",
        help="Name of the (temporary) file containing the dispatch script.",
    ),
    charm_name: Optional[str] = typer.Option(
        None,
        "-c",
        "--charm-name",
        help="Name of the charm type to import from `charm.py`. Useful if your charm.py "
        "contains more than one charm type (e.g. if you have a base class...).",
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
    """Evaluates an expression in the context of a live charm.

    RENAMED to ``jhack eval``.
    """
    logger.warning("`jhack crpc` is being renamed; please use `jhack eval`.")
    _charm_rpc(
        target=target,
        expr=expr,
        model=model,
        cleanup=cleanup,
        crpc_dispatch_name=crpc_dispatch_name,
        env_override=env_override,
        event=event,
        charm_name=charm_name,
    )


def charm_eval(
    target: str = typer.Argument(
        ...,
        help="Target unit or application name. "
        "Using an application name will evaluate the expression on all units.",
    ),
    expr: str = typer.Argument(
        ...,
        help="Path to an object or callable starting from the charm instance. "
        "Can start with ``self.``, or it can be omitted."
        "Examples: \n"
        "- .model.relations['foo']\n"
        "- self.ingress.is_ready\n",
    ),
    model: str = typer.Option(
        None, "-m", "--model", help="Which model to apply the command to."
    ),
    cleanup: bool = typer.Option(
        True,
        help="Remove all files created onto the unit when you're done.",
        is_flag=True,
    ),
    crpc_dispatch_name: str = typer.Option(
        "crpc_dispatch",
        help="Name of the (temporary) file containing the dispatch script.",
    ),
    charm_name: Optional[str] = typer.Option(
        None,
        "-c",
        "--charm-name",
        help="Name of the charm type to import from `charm.py`. Useful if your charm.py "
        "contains more than one charm type (e.g. if you have a base class...).",
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
    """Evaluates an expression in the context of a live charm.

    You can retrieve any value you can access from the charm instance:
    >>> $ jhack eval unit/0 self.app.name
    >>> "unit"

    You can invoke any method you can refer at from the charm instance:
    >>> $ jhack eval unit/0 self._adder._add(1, 1)
    >>> 2

    With a bit of effort you can also set attributes:
    >>> $ jhack eval unit/0 setattr(self.unit, "status", ops.ActiveStatus("foo"))
    >>> None

    And of course mutate anything the charm can mutate
    >>> $ jhack eval unit/0 self._some_relation.data[self.unit].__setitem__("foo", "bar")
    >>> None
    """
    _charm_rpc(
        target=target,
        expr=expr,
        model=model,
        cleanup=cleanup,
        crpc_dispatch_name=crpc_dispatch_name,
        env_override=env_override,
        event=event,
        charm_name=charm_name,
    )


def charm_script(
    target: str = typer.Argument(
        ...,
        help="Target unit or application name. "
        "Using an application name will run the script on all units.",
    ),
    script: Path = typer.Argument(
        None,
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
    charm_name: Optional[str] = typer.Option(
        None,
        "-c",
        "--charm-name",
        help="Name of the charm type to import from `charm.py`. Useful if your charm.py "
        "contains more than one charm type (e.g. if you have a base class...).",
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

    _charm_script(
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
        charm_name=charm_name,
    )


class InvalidScriptOrEntrypointError(Exception):
    """Raised if script or entrypoint are invalid."""


def _verify_signature(script, entrypoint):
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


def _charm_script(
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
    charm_name: Optional[str],
):
    """Execute local script on live charm.

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
            _verify_signature(script, entrypoint)
        except Exception as e:
            logger.debug(e, exc_info=True)
            logger.error(
                f"encountered exception while verifying entrypoint signature... {e}"
                f"Proceeding..."
            )

    targets = _get_targets(target, model)

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
                charm_name=charm_name,
            ),
            targets,
        )


def _build_rpc_expr(path: str) -> str:
    if path.startswith("self."):
        return path
    if path.startswith("."):
        return "self" + path
    return path


def _get_targets(target, model):
    targets = []
    if "/" not in target:
        # app name received. run on all units.
        targets.extend(get_units(target))

    else:
        targets.append(Target.from_name(target))

    return targets


def _encode(expr: str) -> str:
    return base64.b64encode(expr.encode("utf-8")).decode("ascii")


def _charm_rpc(
    target: str,
    expr: str,
    crpc_dispatch_name: str,
    model: str,
    cleanup: bool,
    event: str,
    env_override: List[str],
    charm_name: Optional[str],
):
    """Rpc a live charm method.

    Executes dispatch on a patched init script so the charm is set up and a specific method is called
    instead of being passed to ops.main standard event loop.
    """
    expr = _build_rpc_expr(expr)
    logger.debug(f"rpc expression: {expr!r}")
    encoded_expr = _encode(expr)

    targets = _get_targets(target, model)

    with Pool(len(targets)) as pool:
        logger.debug(f"initiating async crpc calls to {targets}")
        pool.map(
            partial(
                _exec_crpc_expr,
                expr=encoded_expr,
                crpc_dispatch_name=crpc_dispatch_name,
                model=model,
                cleanup=cleanup,
                event=event,
                env_override=env_override,
                charm_name=charm_name,
            ),
            targets,
        )


def _push_crpc_dispatch_script(target, model, crpc_dispatch_name):
    logger.info("pushing crpc dispatch script...")
    remote_rpc_dispatch_path = f"src/{crpc_dispatch_name}.py"
    dispatch = Path(__file__).parent / "charm_rpc_dispatch.py"
    push_file(target.unit_name, dispatch, remote_rpc_dispatch_path, model=model)
    return remote_rpc_dispatch_path


def _prepare_crpc_env(target, event, env_override, model):
    if event or env_override:
        evt = event or "charm-rpc"
        logger.info(f"preparing environment for event {evt!r}...")
        crpc_env = build_event_env(
            target.unit_name, evt, override=env_override, model=model
        )
    else:
        logger.info("setting up generic event context...")
        crpc_env = "JUJU_DISPATCH_PATH=charm-rpc"
    return crpc_env


def _exec_crpc_script(
    target: Target,
    script: Path,
    entrypoint: str,
    crpc_module_name: str,
    crpc_dispatch_name: str,
    model: str,
    cleanup: bool,
    event: str,
    charm_name: Optional[str],
    env_override: List[str],
):
    logger.info(f"pushing crpc module {script}...")
    remote_rpc_module_path = f"src/{crpc_module_name}.py"
    push_file(target.unit_name, script, remote_rpc_module_path, model=model)

    remote_rpc_dispatch_path = _push_crpc_dispatch_script(
        target, model, crpc_dispatch_name
    )
    crpc_env = _prepare_crpc_env(target, event, env_override, model)

    env = " ".join(
        f"{key}={val}"
        for key, val in {
            "CHARM_RPC_ENV": crpc_env,
            "CHARM_RPC_MODULE_NAME": crpc_module_name,
            "CHARM_RPC_ENTRYPOINT": entrypoint,
            "CHARM_RPC_CHARM_NAME": charm_name,
            "CHARM_RPC_LOGLEVEL": os.getenv("LOGLEVEL", "WARNING"),
            "PYTHONPATH": "lib:venv",
        }.items()
    )

    _run_crpc(target, env, crpc_dispatch_name)

    if cleanup:
        logger.info("cleaning up...")
        try:
            rm_file(target.unit_name, remote_rpc_module_path, model=model)
            rm_file(target.unit_name, remote_rpc_dispatch_path, model=model)
        except RuntimeError as e:
            logger.warning(f"cleanup FAILED with {e}")


def _run_crpc(target, env, crpc_dispatch_name):
    logger.info("executing crpc...")
    exec_dispatch_cmd = f"juju exec --unit {target.unit_name} -- {env} python3 ./src/{crpc_dispatch_name}.py"
    run(shlex.split(exec_dispatch_cmd))


def _exec_crpc_expr(
    target: Target,
    expr: str,
    crpc_dispatch_name: str,
    model: str,
    cleanup: bool,
    event: str,
    env_override: List[str],
    charm_name: Optional[str],
):
    remote_rpc_dispatch_path = _push_crpc_dispatch_script(
        target, model, crpc_dispatch_name
    )
    crpc_env = _prepare_crpc_env(target, event, env_override, model)

    env_dict = {
        "CHARM_RPC_ENV": crpc_env,
        "CHARM_RPC_EXPR": expr,
        "CHARM_RPC_LOGLEVEL": os.getenv("LOGLEVEL", "WARNING"),
        "PYTHONPATH": "lib:venv",
    }
    if charm_name:
        env_dict["CHARM_RPC_CHARM_NAME"] = charm_name

    env = " ".join(f"{key}={val}" for key, val in env_dict.items())

    _run_crpc(target, env, crpc_dispatch_name)

    if cleanup:
        logger.info("cleaning up...")
        try:
            rm_file(target.unit_name, remote_rpc_dispatch_path, model=model)
        except RuntimeError as e:
            logger.warning(f"cleanup FAILED with {e}")
