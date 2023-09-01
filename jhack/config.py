"""Jhack configuration module."""

import os
import pwd
import sys
from pathlib import Path
from subprocess import CalledProcessError, check_output

from jhack.logger import logger

IS_SNAPPED = False
JHACK_PROJECT_ROOT = Path(__file__).parent.parent


def get_home_dir() -> Path:
    """Get the path to the home directory for the user."""
    try:
        usr = pwd.getpwuid(os.getuid())[0]
    except KeyError:
        logger.debug(
            "pwd.getpwuid could not get pwd for your UID. "
            "If you think you're root, something must have gone wrong. "
            "Set the envvar JHACK_DATA to some snap-writable path where "
            "jhack should store its data and config."
        )
        usr = ""

    if usr == "root":
        home_dir = Path("/root")
    else:
        if os.environ.get("USER"):
            home_dir = Path("/home") / os.environ["USER"]
        else:
            home_dir = Path("~").expanduser().absolute()
    return home_dir


def get_jhack_data_path() -> Path:
    """Get the path to the jhack data root.

    That's where we store all jhack config and data.
    """
    if data := os.getenv("JHACK_DATA"):
        return Path(data)

    return get_home_dir() / ".config" / "jhack"


def get_jhack_config_path() -> Path:
    """Get the path to the jhack config file.

    It needs not exist.
    """
    return get_jhack_data_path() / "config.toml"


def configure():
    """Configure jhack."""
    snap_data = os.environ.get("SNAP_DATA")

    if not snap_data or "jhack" not in snap_data:  # we could be in another snap
        logger.info(
            "jhack running in unsnapped mode. "
            "Skipping .local/share/juju configuration."
        )
    else:
        global IS_SNAPPED
        IS_SNAPPED = True

        logger.info("jhack running in snapped mode. Checking configuration...")
        # check `juju` command.
        try:
            juju_command = check_output(["which", "juju"])
            logger.info(f"juju command is {juju_command}")
        except CalledProcessError:
            logger.error(
                "juju command not found. "
                "All jhacks depending on juju calls will bork."
                "if this is a snap, you might have forgotten to "
                "connect jhack to some required plugs."
            )

        # check JUJU_DATA is writeable
        jdata = get_home_dir() / ".local/share/juju"

        try:
            test_file = jdata / ".__test_rw_jhack__.hacky"
            test_file.write_text("kuckadoodle-foo")
            test_file.unlink()
        except FileNotFoundError:
            sys.exit(f"JUJU_DATA default directory not found at {jdata}. "
                     f"Is the juju snap bootstrapped?")
        except PermissionError:
            logger.error(
                f"It seems like the snap doesn't have access to {jdata};"
                f"to grant it, run 'sudo snap connect jhack:dot-local-share-juju snapd'."
                f"Some Jhack commands will still work, but those that interact "
                f"with the juju client will not."
            )
