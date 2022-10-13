import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Type, Tuple, FrozenSet

import yaml

from jhack.helpers import JPopen
from jhack.logger import logger
from jhack.utils.event_recorder.client import _fetch_file
from jhack.utils.event_recorder.memo_tools import inject_memoizer
from jhack.utils.event_recorder.recorder import (
    DEFAULT_DB_NAME,
    MEMO_DATABASE_NAME_KEY,
    MEMO_MODE_KEY,
    MEMO_REPLAY_INDEX_KEY,
    Event,
    _reset_replay_cursors,
    event_db, Scene,
)

if TYPE_CHECKING:
    from ops.testing import CharmType

RECORDER_MODULE = Path(__file__).parent
logger = logger.getChild("event_recorder.runtime")


class Runtime:
    """Charm runtime wrapper.

    This object bridges a live charm unit and a local environment.
    """

    DECORATE_MODEL = {
        '_ModelBackend': frozenset({
            "relation_ids",
            "relation_list",
            "relation_remote_app_name",
            "relation_get",
            "update_relation_data",
            "relation_set",
            "config_get",
            "is_leader",
            "application_version_set",
            "resource_get",
            "status_get",
            "status_set",
            "storage_list",
            "storage_get",
            "storage_add",
            "action_get",
            "action_set",
            "action_log",
            "action_fail",
            "network_get",
            "add_metrics",
            "juju_log",
            "planned_units",
            # 'secret_get',
            # 'secret_set',
            # 'secret_grant',
            # 'secret_remove',
        })
    }
    DECORATE_PEBBLE = {
        'Client': frozenset({
            "_request",
        })
    }

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
        _fetch_file(unit, remote_db_path or self._remote_db_path, local_path=self._local_db_path)

        if not self._meta:
            logger.info(f"Fetching metadata from {unit}.")
            self._meta = _fetch_file(unit, 'metadata.yaml')
        if not self._actions:
            logger.info(f"Fetching actions metadata from {unit}.")
            self._actions = _fetch_file(unit, 'actions.yaml')

    def install(self):
        """Install the runtime.

        Fine prints:
          - this will **REWRITE** your local ops.model module to include a @memo decorator
            in front of all hook-tool calls.
          - this will mess with your os.environ.
          - These operations might not be reversible, so consider your environment corrupted.
            You should be calling this in a throwaway venv, and probably a container sandbox.

            Nobody will help you fix your borked env.
            Have fun!
        """
        logger.warning(
            "Installing Runtime... "
            "DISCLAIMER: this **might** (most definitely will) corrupt your venv."
        )

        logger.info('rewriting ops.pebble')
        from ops import pebble
        ops_pebble_module = Path(pebble.__file__)
        inject_memoizer(ops_pebble_module, decorate=self.DECORATE_PEBBLE)

        logger.info('rewriting ops.model')
        from ops import model
        ops_model_module = Path(model.__file__)
        inject_memoizer(ops_model_module, decorate=self.DECORATE_MODEL)

        logger.info('rewriting ops.main')
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

    def _is_installed(self):
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

    def run(self,
            scene_idx: int,
            fetch_from_unit: Optional[str] = None
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
            charm = main(self._charm_type)

        return charm, scene


if __name__ == "__main__":
    from ops.charm import CharmBase


    class MyCharm(CharmBase):
        def __init__(self, framework, key: Optional[str] = None):
            super().__init__(framework, key)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._catchall)

        def _catchall(self, e):
            print(e)


    runtime = Runtime(
        MyCharm,
        meta={
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        },
    )
    runtime.install()
    runtime.load("trfk/0")
    runtime.run(0)
