import os
from pathlib import Path
from subprocess import CalledProcessError, check_output

from jhack.logger import logger

IS_SNAPPED = False


def configure():
    snap_data = os.environ.get("SNAP_DATA")

    if not snap_data or "jhack" not in snap_data:  # we could be in another snap
        logger.info("jhack running in unsnapped mode. Nothing to configure.")
        return

    logger.info("jhack running in snapped mode. Configuring...")
    IS_SNAPPED = True

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

    user = os.environ["USER"]
    jdata = f"/home/{user}/.local/share/juju"

    try:
        test_file = Path(jdata) / ".test_rw"
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
    os.environ["JUJU_DATA"] = jdata
    logger.info(f"Set JUJU_DATA to {jdata}.")


if __name__ == "__main__":
    configure()
