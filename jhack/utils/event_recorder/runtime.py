import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Type, TYPE_CHECKING

import yaml

from jhack.logger import logger
from jhack.utils.event_recorder.client import _fetch_db
from jhack.utils.event_recorder.memo_tools import inject_memoizer
from jhack.utils.event_recorder.recorder import (
    DEFAULT_DB_NAME,
    MEMO_DATABASE_NAME_KEY,
    MEMO_MODE_KEY,
    MEMO_REPLAY_INDEX_KEY,
    Event,
    event_db, _reset_replay_cursors,
)

if TYPE_CHECKING:
    from ops.testing import CharmType

RECORDER_MODULE = Path(__file__).parent
logger = logger.getChild("event_recorder.runtime")


class Runtime:
    def __init__(
            self,
            charm_type: Type['CharmType'],
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
        if not meta:
            raise ValueError("We NEED metadata.")
        self._meta = meta
        self._actions = actions

        if unit:
            self.fetch_db(unit, remote_db_path)
        if install:
            self.install()

    def fetch_db(self, unit: str, remote_db_path=None):
        logger.info(f"Fetching db from {unit}@~/{remote_db_path}.")
        _fetch_db(
            unit,
            remote_db_path or self._remote_db_path,
            local_db_path=self._local_db_path,
        )

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
        logger.warning("Installing Runtime... "
                       "DISCLAIMER: this **might** (most definitely will) corrupt your venv.")

        from ops import model, main

        ops_model_module = Path(model.__file__)
        inject_memoizer(ops_model_module)

        # make main return the charm instance, for testing
        ops_model_module = Path(main.__file__)
        retcharm = "return charm  # added by jhack.replay.Runtime"
        ops_model_module_text = ops_model_module.read_text()
        if retcharm not in ops_model_module_text:
            ops_model_module.write_text(
                ops_model_module_text
                + f"    {retcharm}\n"
            )

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
        def _patch_logger(*args, **kwargs):
            logger.debug("Hijacked root logger.")
            pass
        import ops.main
        ops.main.setup_root_logging = _patch_logger

    def _clear_env(self):
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

    def run(self, scene_idx: int,
            fetch_from_unit: Optional[str] = None) -> 'CharmType':
        if not self._is_installed():
            raise sys.exit(
                "Runtime is not installed. Call `runtime.install()` (and read the fine prints)."
            )

        if fetch_from_unit:
            self.fetch_db(unit=fetch_from_unit)

        with event_db(self._local_db_path) as data:
            try:
                scene = data.scenes[scene_idx]
            except IndexError:
                sys.exit(
                    f"Scene ID {scene_idx} not found in the local db ({self._local_db_path}).\n"
                    f"If you are replaying from a remote unit, you should call `Runtime.fetch_db(<unit-name>)`"
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

        return charm


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
    runtime.fetch_db("trfk/0")
    runtime.run(0)
