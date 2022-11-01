import contextlib
import os
import sys
import tempfile
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ContextManager,
    Dict,
    Optional,
    Tuple,
    Type,
)

import yaml
from ops.charm import CharmBase

from jhack.helpers import fetch_file
from jhack.logger import logger
from jhack.utils.event_recorder.memo_tools import (
    DECORATE_MODEL,
    DECORATE_PEBBLE,
    inject_memoizer,
)
from jhack.utils.event_recorder.recorder import (
    DEFAULT_DB_NAME,
    MEMO_DATABASE_NAME_KEY,
    MEMO_MODE_KEY,
    MEMO_REPLAY_INDEX_KEY,
    Event,
    Scene,
    _reset_replay_cursors,
    event_db,
)

if TYPE_CHECKING:
    from ops.testing import CharmType

RECORDER_MODULE = Path(__file__).parent
logger = logger.getChild("event_recorder.runtime")


class Runtime:
    """Charm runtime wrapper.

    This object bridges a live charm unit and a local environment.
    """

    def __init__(
        self,
        charm_type: Type["CharmType"],
        local_db_path: Path = None,
        unit: str = None,
        remote_db_path: str = DEFAULT_DB_NAME,
        meta: Optional[Dict[str, Any]] = None,
        actions: Optional[Dict[str, Any]] = None,
        install: bool = False,
    ):

        self._charm_type = charm_type
        local_db_path = local_db_path or Path(
            tempfile.NamedTemporaryFile(delete=False).name
        )
        local_db_path.touch(exist_ok=True)

        self._local_db_path = local_db_path
        self._remote_db_path = remote_db_path

        self._meta = meta
        self._actions = actions

        if unit:
            self.load(unit, remote_db_path)
        if install:
            self.install()

    def load(self, unit: str, remote_db_path=None):
        """Fetch event db and charm metadata from the live unit."""
        logger.info(f"Fetching db from {unit}@~/{remote_db_path}.")
        fetch_file(
            unit, remote_db_path or self._remote_db_path, local_path=self._local_db_path
        )

        if not self._meta:
            logger.info(f"Fetching metadata from {unit}.")
            self._meta = yaml.safe_load(fetch_file(unit, "metadata.yaml"))
        if not self._actions:
            logger.info(f"Fetching actions metadata from {unit}.")
            self._actions = yaml.safe_load(fetch_file(unit, "actions.yaml"))

        return self

    @staticmethod
    def install(force=False):
        """Install the runtime LOCALLY.

        Fine prints:
          - this will **REWRITE** your local ops.model module to include a @memo decorator
            in front of all hook-tool calls.
          - this will mess with your os.environ.
          - These operations might not be reversible, so consider your environment corrupted.
            You should be calling this in a throwaway venv, and probably a container sandbox.

            Nobody will help you fix your borked env.
            Have fun!
        """
        if not force and Runtime._is_installed:
            logger.warning(
                "Runtime is already installed. "
                "Pass `force=True` if you wish to proceed anyway. "
                "Skipping..."
            )
            return

        logger.warning(
            "Installing Runtime... "
            "DISCLAIMER: this **might** (aka: most definitely will) corrupt your venv."
        )

        logger.info("rewriting ops.pebble")
        from ops import pebble

        ops_pebble_module = Path(pebble.__file__)
        inject_memoizer(ops_pebble_module, decorate=DECORATE_PEBBLE)

        logger.info("rewriting ops.model")
        from ops import model

        ops_model_module = Path(model.__file__)
        inject_memoizer(ops_model_module, decorate=DECORATE_MODEL)

        logger.info("rewriting ops.main")
        from ops import main

        # make main return the charm instance, for testing
        ops_main_module = Path(main.__file__)
        retcharm = "return charm  # added by jhack.replay.Runtime"
        ops_main_module_text = ops_main_module.read_text()
        if retcharm not in ops_main_module_text:
            ops_main_module.write_text(ops_main_module_text + f"    {retcharm}\n")

    def cleanup(self):
        self._local_db_path.unlink()
        # todo consider cleaning up venv, but ideally you should be
        #  running this in a clean venv or a container anyway.

    def __delete__(self, instance):
        self.cleanup()

    @staticmethod
    def _is_installed():
        from ops import model

        if "from recorder import memo" not in Path(model.__file__).read_text():
            logger.error("ops.model does not seem to import recorder.memo.")
            return False

        try:
            import recorder
        except ModuleNotFoundError:
            logger.error("Could not `import recorder`.")
            return False

        return True

    def _redirect_root_logger(self):
        # the root logger set up by ops calls a hook tool: `juju-log`.
        # that is a problem for us because `juju-log` is itself memoized by `jhack.replay`
        # which leads to recursion.
        def _patch_logger(*args, **kwargs):
            logger.debug("Hijacked root logger.")
            pass

        import ops.main

        ops.main.setup_root_logging = _patch_logger

    @staticmethod
    def _clear_env():
        # cleanup env, in case we'll be firing multiple events, we don't want to accumulate.
        for key in os.environ:
            del os.environ[key]

    def _prepare_env(self, event: Event, scene_idx: int):
        os.environ.update(event.env)
        os.environ.update(
            {
                MEMO_REPLAY_INDEX_KEY: str(scene_idx),
                MEMO_DATABASE_NAME_KEY: str(self._local_db_path.absolute()),
            }
        )
        sys.path.append(str(RECORDER_MODULE.absolute()))
        os.environ[MEMO_MODE_KEY] = "replay"

    def _mock_charm_root(self, charm_root: Path):
        logger.debug("Dropping metadata.yaml and actions.yaml...")
        (charm_root / "metadata.yaml").write_text(yaml.safe_dump(self._meta))
        if self._actions:
            (charm_root / "actions.yaml").write_text(yaml.safe_dump(self._actions))

        os.environ["JUJU_CHARM_DIR"] = str(charm_root.absolute())

    def run(
        self, scene_idx: int, fetch_from_unit: Optional[str] = None
    ) -> Tuple["CharmType", Scene]:
        """Executes a scene on the charm.

        This will set the environment up and call ops.main.main().
        After that it's up to ops.
        """
        if not self._is_installed():
            raise sys.exit(
                "Runtime is not installed. Call `runtime.install()` (and read the fine prints)."
            )

        if fetch_from_unit:
            self.load(unit=fetch_from_unit)

        with event_db(self._local_db_path) as data:
            try:
                scene = data.scenes[scene_idx]
            except IndexError:
                sys.exit(
                    f"Scene ID {scene_idx} not found in the local db ({self._local_db_path}).\n"
                    f"If you are replaying from a remote unit, you should call `Runtime.load(<unit-name>)`"
                )

        logger.info(
            f"Preparing to run {self._charm_type.__name__} like it did back in {scene.event.datetime.isoformat()}"
        )

        logger.info(" - clearing env")
        self._clear_env()

        logger.info(" - preparing env")
        self._prepare_env(scene.event, scene_idx)

        logger.info(" - redirecting root logging")
        self._redirect_root_logger()

        logger.info("Resetting scene {} replay cursor.")
        _reset_replay_cursors(self._local_db_path, scene_idx)

        with tempfile.TemporaryDirectory() as cr:
            self._mock_charm_root(Path(cr))
            from ops.main import main

            logger.info("Entering ops.main.")

            try:
                charm = main(self._charm_type)
            except Exception as e:
                raise RuntimeError("Uncaught error in operator/charm code.") from e

        return charm, scene


@contextlib.contextmanager
def live_unit_runtime(
    unit_name: str,
    local_charm_src: Path,
    charm_cls_name: str,
    patch: Callable[["CharmType"], "CharmType"] = lambda x: x,
) -> ContextManager[Runtime]:

    sys.path.extend((str(local_charm_src / "src"), str(local_charm_src / "lib")))

    ldict = {}

    try:
        exec(f"from charm import {charm_cls_name} as my_charm_type", globals(), ldict)
    except ModuleNotFoundError as e:
        raise RuntimeError(
            f"Failed to load charm {charm_cls_name}. "
            f"Probably some dependency is missing. "
            f"Try `pip install -r {local_charm_src / 'requirements.txt'}`"
        ) from e

    my_charm_type: Type[CharmBase] = ldict["my_charm_type"]

    charm_type = patch(my_charm_type)

    yield Runtime(
        charm_type,
        # omitting these would mean Runtime will fetch them from the live unit
        meta=yaml.safe_load((local_charm_src / "metadata.yaml").read_text()),
        actions=yaml.safe_load((local_charm_src / "actions.yaml").read_text()),
    ).load(unit_name)


if __name__ == "__main__":
    # install Runtime **in your current venv** so that all
    # relevant pebble.Client | model._ModelBackend juju/container-facing calls are
    # @memo-decorated and can be used in "replay" mode to reproduce a remote run.
    Runtime.install(force=False)

    # IRL one would probably manually @memo the annoying ksp calls.
    def _patch_traefik_charm(charm: "CharmType"):
        from charms.observability_libs.v0 import kubernetes_service_patch  # noqa

        def _do_nothing(*args, **kwargs):
            print("KubernetesServicePatch call skipped")

        def _null_evt_handler(self, event):
            print(f"event {event} received and skipped")

        kubernetes_service_patch.KubernetesServicePatch._service_object = _do_nothing
        kubernetes_service_patch.KubernetesServicePatch._patch = _null_evt_handler
        return charm

    # here's the magic:
    # this env grabs the event db from the "trfk/0" unit (assuming the unit is available
    # in the currently switched-to juju model/controller).
    with live_unit_runtime(
        "trfk/0",
        local_charm_src=Path("/home/pietro/canonical/traefik-k8s-operator"),
        charm_cls_name="TraefikIngressCharm",
        patch=_patch_traefik_charm,
    ) as runtime:
        # then it will grab the TraefikIngressCharm from that local path and simulate the whole
        # remote runtime env by calling `ops.main.main()` on it.
        # this tells the runtime which event to replay. Right now, #X of the
        # `jhack replay list trfk/0` queue. Switch it to whatever number you like to
        # locally replay that event.
        runtime.run(2)
