import os
import pwd
from pathlib import Path
from subprocess import CalledProcessError, check_output

from jhack.logger import logger

IS_SNAPPED = False

USR = pwd.getpwuid(os.getuid())[0]


if USR == "root":
    HOME_DIR = "/root"
else:
    if os.environ.get("USER"):
        HOME_DIR = Path("/home") / os.environ["USER"]
    else:
        HOME_DIR = Path("~").expanduser().absolute()

JHACK_DATA_PATH = HOME_DIR / ".config" / "jhack"
JHACK_CONFIG_PATH = JHACK_DATA_PATH / "config.toml"


def configure():
    snap_data = os.environ.get("SNAP_DATA")

    if not snap_data or "jhack" not in snap_data:  # we could be in another snap
        logger.info(
            "jhack running in unsnapped mode. "
            "Skipping .local/share/juju configuration."
        )
    else:
        logger.info("jhack running in snapped mode. Configuring...")
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

        jdata = HOME_DIR / ".local/share/juju"

        try:
            test_file = jdata / ".__test_rw_jhack__.hacky"
            test_file.write_text("kuckadoodle-foo")
            test_file.unlink()
        except PermissionError:
            logger.error(
                f"It seems like the snap doesn't have access to {jdata};"
                f"to grant it, run 'sudo snap connect jhack:dot-local-share-juju snapd'."
                f"Some Jhack commands will still work, but those that interact "
                f"with the juju client will not."
            )

        # if we don't have rw access this will not do anything:
        # python-libjuju grabs the juju-data location from envvar.
        # We provide it here to ensure it's what we think it should be.
        logger.info(f'Previous env JUJU_DATA = {os.environ.get("JUJU_DATA")}.')
        os.environ["JUJU_DATA"] = str(jdata)
        logger.info(f"Set JUJU_DATA to {jdata}.")

    # check if the user has provided a jhack config file
    has_config = JHACK_CONFIG_PATH.exists()
    logger.info(
        f'searching for {JHACK_CONFIG_PATH}!r... {"found" if has_config else "not found"}'
    )
    if not has_config:
        logger.debug(f"no jhack config file found. All will be defaulted.")


if __name__ == "__main__":
    configure()
