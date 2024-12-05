from importlib import metadata
from importlib.metadata import PackageNotFoundError

import toml

from jhack.conf.conf import check_destructive_commands_allowed
from jhack.config import JHACK_PROJECT_ROOT


def print_jhack_version():
    """Print the currently installed jhack version and exit."""
    is_devmode = check_destructive_commands_allowed("", _check_only=True)
    print(f"jhack {get_jhack_version()}{' --DEVMODE--' if is_devmode else ''}")


def get_jhack_version():
    try:
        jhack_version = metadata.version("jhack")
    except PackageNotFoundError:
        # jhack not installed but being used from sources:
        pyproject = JHACK_PROJECT_ROOT / "pyproject.toml"
        if pyproject.exists():
            jhack_version = (
                toml.load(pyproject).get("project", {}).get("version", "<unknown version>")
            )
        else:
            jhack_version = "<unknown version>"
    return jhack_version


VERSION = get_jhack_version()
