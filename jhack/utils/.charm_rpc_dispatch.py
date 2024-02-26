import importlib
import inspect
import logging
import os
import sys
import warnings
from pathlib import Path
from typing import Type

import ops
import ops.storage
from ops.main import (
    _get_charm_dir,
    setup_root_logging,
    _Dispatcher,
    CharmMeta,
    CHARM_STATE_FILE,
    JujuVersion,
    _should_use_controller_storage,
)


MODULE_NAME = os.getenv("CHARM_RPC_MODULE_NAME")  # string
ENTRYPOINT = os.getenv("CHARM_RPC_ENTRYPOINT")  # string
SCRIPT_NAME = os.getenv("CHARM_RPC_SCRIPT_NAME")  # string
LOGLEVEL = os.getenv("CHARM_RPC_LOGLEVEL")  # string

logger = logging.getLogger("charm-rpc")
logger.setLevel(LOGLEVEL)


def rpc(charm):
    # load module
    module = importlib.import_module(MODULE_NAME)
    entrypoint = getattr(module, ENTRYPOINT)
    logger.debug(
        f"found entrypoint {ENTRYPOINT!r} in {SCRIPT_NAME}. Invoking on charm..."
    )
    return_value = entrypoint(charm)
    return return_value


def ops_main_rpc(charm_class: Type[ops.charm.CharmBase], use_juju_for_storage: bool):
    charm_dir = _get_charm_dir()

    model_backend = ops.model._ModelBackend()
    debug = "JUJU_DEBUG" in os.environ
    setup_root_logging(model_backend, debug=debug)
    logger.debug("charm rpc dispatch v0.1 up and running.")

    # not a real event, but we don't care
    os.environ["JUJU_DISPATCH_PATH"] = "charm-rpc"

    dispatcher = _Dispatcher(charm_dir)
    metadata = (charm_dir / "metadata.yaml").read_text()
    actions_meta = charm_dir / "actions.yaml"
    if actions_meta.exists():
        actions_metadata = actions_meta.read_text()
    else:
        actions_metadata = None

    meta = CharmMeta.from_yaml(metadata, actions_metadata)
    model = ops.model.Model(meta, model_backend)

    charm_state_path = charm_dir / CHARM_STATE_FILE

    if use_juju_for_storage and not ops.storage.juju_backend_available():
        # raise an exception; the charm is broken and needs fixing.
        msg = "charm set use_juju_for_storage=True, but Juju version {} does not support it"
        raise RuntimeError(msg.format(JujuVersion.from_environ()))

    if use_juju_for_storage is None:
        use_juju_for_storage = _should_use_controller_storage(charm_state_path, meta)

    if use_juju_for_storage:
        store = ops.storage.JujuStorage()
    else:
        store = ops.storage.SQLiteStorage(charm_state_path)
    framework = ops.framework.Framework(
        store, charm_dir, meta, model, event_name=dispatcher.event_name
    )
    framework.set_breakpointhook()
    charm = charm_class(framework)

    logger.debug(f"instantiated charm {charm.__class__.__name__}")
    return charm


def check_controller_storage(charm_type: Type[ops.charm.CharmBase]) -> bool:
    # try to guesstimate if the charm is using controller storage or not.
    # unfortunately this is probably best done in the hackiest way possible
    charm_source = Path(inspect.getmodule(charm_type).__file__).read_text()

    # I literally had to go and wash my hands after writing this
    if (
        "use_juju_for_storage=True" in charm_source
        or "use_juju_for_storage = True" in charm_source
    ):
        return True
    return False


def load_charm_type() -> Type[ops.charm.CharmBase]:
    module = importlib.import_module("charm")
    for identifier, obj in module.__dict__.items():
        if (
            isinstance(obj, type)
            and issubclass(obj, ops.charm.CharmBase)
            and obj.__name__ != "CharmBase"
        ):
            logger.debug(f"found charm type {obj}")
            return obj

    raise RuntimeError("couldn't find any charm type in charm.py")


def main():
    charm_type = load_charm_type()
    use_juju_for_storage = check_controller_storage(charm_type)
    charm = ops_main_rpc(charm_type, use_juju_for_storage=use_juju_for_storage)
    output = rpc(charm)

    if output is not None:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
