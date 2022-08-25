import os
from subprocess import CalledProcessError, check_output

from jhack.logger import logger


def configure():
    snap_data = os.environ.get("SNAP_DATA")

    if not snap_data or "jhack" not in snap_data:  # we could be in another snap
        logger.info("jhack running in unsnapped mode. Nothing to configure.")
        return

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


if __name__ == "__main__":
    configure()
