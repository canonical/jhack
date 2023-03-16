import sys
from pathlib import Path

import toml

from jhack.config import get_jhack_config_path
from jhack.logger import logger as jhacklogger

logger = jhacklogger.getChild(__file__)


class Config:
    _DEFAULTS = Path(__file__).parent / "jhack_config_defaults.toml"

    def __init__(self, path: Path = None):
        if not path:
            jconf = get_jhack_config_path()

            try:
                jconf_exists = jconf.exists()
            except PermissionError:
                logger.warning(f'trying to stat {jconf} gave PermissionError; bad config path. '
                             f'All will be defaulted.')
                jconf_exists = False
            path = jconf if jconf_exists else self._DEFAULTS

        self._path: Path = path
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

    def __getitem__(self, item):
        return self.data[item]


def print_defaults():
    """Print jhack's default config."""
    Config(Config._DEFAULTS).pprint()


def print_current_config():
    """Show the current config.

    Unless you have a `~/.config/jhack/config.toml` file, this will be the default config.
    """
    CONFIG.pprint()


CONFIG = Config()
