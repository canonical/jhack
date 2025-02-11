import os
import sys
from enum import Enum
from pathlib import Path
from typing import Union

import toml
import typer

from jhack.config import get_jhack_config_path
from jhack.logger import logger as jhacklogger

logger = jhacklogger.getChild(__file__)


class Config:
    _DEFAULTS = Path(__file__).parent / "jhack_config_defaults.toml"
    _DESTRUCTIVE = Path(__file__).parent / "jhack_config_destructive.toml"
    _YOLO = Path(__file__).parent / "jhack_config_yolo.toml"

    def __init__(self, path: Path = None):
        is_default = False
        if not path:
            path, is_default = self._get_config_path()
        self._path: Path = path
        self.is_default: bool = is_default
        self._data = None

    def _get_config_path(self):
        # get user config path
        jconf = get_jhack_config_path()
        try:
            jconf_exists = jconf.exists()
        except PermissionError:
            logger.warning(
                f"trying to stat {jconf} gave PermissionError; bad config path. "
                f"All will be defaulted."
            )
            return self._DEFAULTS, True

        # try creating the config if not found
        if jconf_exists:
            return jconf, False

        try:
            jconf.parent.mkdir(parents=True, exist_ok=True)
            jconf.write_text(self._DEFAULTS.read_text())
            logger.info(f"initialized default user config in {jconf}.")
            return jconf, False

        except Exception:
            logger.exception(
                "Error encountered while attempting to initialize user config: ",
                f"Failed to create default user config in {jconf}. "
                f"You'll have to do that manually.",
            )

        return self._DEFAULTS, True

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
                if self.is_default:
                    logger.error(f"{item} not found in default config; invalid path")
                    raise

                logger.info(f"{item} not found in user-config {self._path}; defaulting...")
                return self.get_default(*path)
        return data

    @staticmethod
    def get_default(*path: str):
        return Config(Config._DEFAULTS).get(*path)


def print_defaults():
    """Print jhack's built-in `default` config profile."""
    Config(Config._DEFAULTS).pprint()


def print_destructive():
    """Print jhack's built-in `destructive` config profile."""
    Config(Config._DESTRUCTIVE).pprint()


def print_yolo():
    """Print jhack's built-in `yolo` config profile."""
    Config(Config._YOLO).pprint()


def print_current_config():
    """Show the current config.

    Unless you have a `~/.config/jhack/config.toml` file, this will be the default config.
    """
    CONFIG.pprint()


class _Denied:
    """Falsy return object."""

    def __init__(self, reason: str = ""):
        self.reason = reason

    def __bool__(self):
        return False


class _Reason(str, Enum):
    devmode_temp = "devmode_temp"
    devmode_perm = "devmode_perm"
    user = "user"


class _Allowed:
    """Truthy return object."""

    def __init__(self, reason: _Reason):
        self.reason = reason

    def __bool__(self):
        return True


def check_destructive_commands_allowed(
    msg: str, dry_run_cmd: str = "", _check_only=False
) -> Union[_Denied, _Allowed]:
    if os.getenv("JHACK_PROFILE") == "devmode":
        logger.debug(f"operation {msg!r} allowed by devmode profile.")
        return _Allowed(_Reason.devmode_temp)

    if not CONFIG.get("general", "enable_destructive_commands_NO_PRODUCTION_zero_guarantees"):
        preamble = (
            "\n ** Jhack is now 'safe'! **\nAll dangerous commands require manual confirmation."
        )

        if CONFIG.is_default:
            body = (
                "If you know better, you can run: \n"
                "> `jhack conf [default | destructive | yolo] > ~/.config/jhack/config.toml` \n"
                "and edit the config to match your needs."
            )
        else:
            body = "If you know better, you can tune `~/.config/jhack/config.toml` to your needs."

        closure = (
            "See https://github.com/canonical/jhack?tab=readme-ov-file#enabling-devmode for more."
        )

        logger.warning("\n\n".join([preamble, body, closure]))

        if dry_run_cmd:
            print(f"{msg!r} would run: \n\t {dry_run_cmd}")

        confirmation_msg = (
            "confirm" if dry_run_cmd else "Proceed with this potentially world-ending command"
        )
        try:
            if not typer.confirm(confirmation_msg, default=False):
                if _check_only:
                    return _Denied(_Reason.user)
                exit("operation disallowed by user")
        except typer.Abort:
            if _check_only:
                return _Denied()
            exit("aborted")

        logger.debug(f"operation {msg} allowed by user.")
        return _Allowed(_Reason.user)

    logger.debug(f"operation {msg} allowed by conf.")
    return _Allowed(_Reason.devmode_perm)


CONFIG = Config()
