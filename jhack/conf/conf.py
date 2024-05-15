import os
import sys
from pathlib import Path

import toml

from jhack.config import get_jhack_config_path
from jhack.logger import logger as jhacklogger

logger = jhacklogger.getChild(__file__)


class Config:
    _DEFAULTS = Path(__file__).parent / "jhack_config_defaults.toml"

    def __init__(self, path: Path = None):
        is_default = False
        if not path:
            jconf = get_jhack_config_path()

            try:
                jconf_exists = jconf.exists()
            except PermissionError:
                logger.warning(
                    f"trying to stat {jconf} gave PermissionError; bad config path. "
                    f"All will be defaulted."
                )
                jconf_exists = False
            path = jconf if jconf_exists else self._DEFAULTS
            is_default = False if jconf_exists else True

        self._path: Path = path
        self.is_default: bool = is_default
        self._data = None

    def _load(self):
        try:
            self._data = toml.load(self._path.open())
        except PermissionError as e:
            logger.error(
                f"Unable to open config file at {self._path}."
                f"Try `sudo snap connect jhack:dot-config-jhack snapd`."
            )
            raise e

    @property
    def data(self):
        if not self._data:
            self._load()
        return self._data

    def pprint(self):
        try:
            print(self._path.read_text())
        except FileNotFoundError:
            sys.exit(f"No config file found at {self._path}.")

    def get(self, *path: str) -> bool:  # todo: add more toml types?
        data = self.data
        for item in path:
            try:
                data = data[item]
            except KeyError:
                if self._path is self._DEFAULTS:
                    logger.error(f"{item} not found in default config; invalid path")
                    raise

                logger.info(
                    f"{item} not found in user-config {self._path}; defaulting..."
                )
                return self.get_default(*path)
        return data

    @staticmethod
    def get_default(*path: str):
        return Config(Config._DEFAULTS).get(*path)


def print_defaults():
    """Print jhack's default config."""
    Config(Config._DEFAULTS).pprint()


def print_current_config():
    """Show the current config.

    Unless you have a `~/.config/jhack/config.toml` file, this will be the default config.
    """
    CONFIG.pprint()


def check_destructive_commands_allowed(msg: str, _check_only=False):
    if os.getenv("JHACK_PROFILE") == "devmode":
        if _check_only:
            return True
        logger.debug(f"running destructive command {msg} with profile = devmode.")
        return

    if not CONFIG.get(
        "general", "enable_destructive_commands_NO_PRODUCTION_zero_guarantees"
    ):
        if _check_only:
            return False

        preamble = (
            "in order to run this command, you must enable destructive mode. "
            "this mode is intended for development environments and should be disabled "
            "in production! This is *for your own good*. "
        )
        closure = (
            "Or, if you want to allow destructive mode just this once, set the "
            "`JHACK_PROFILE=devmode` envvar."
        )

        if CONFIG.is_default:
            logger.error(
                preamble
                + "If you know better, you can run `jhack conf default |> ~/.config/jhack/config.toml` "
                "and edit that file and set `[general]enable_destructive_commands_NO_PRODUCTION_zero_guarantees` "
                "to `true`. " + closure
            )
        else:
            logger.error(
                preamble
                + "If you know better, you can edit your `~/.config/jhack/config.toml` "
                "and set `[general]enable_destructive_commands_NO_PRODUCTION_zero_guarantees` "
                "to `true`. " + closure
            )

        exit(f"operation not allowed: {msg}")
    logger.debug(f"running destructive command {msg}, as allowed by conf.")


CONFIG = Config()
