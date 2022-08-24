import os
from pathlib import Path
from subprocess import CalledProcessError, check_output

from jhack.logger import logger

default_juju_data_loc = '~/.local/share/juju/'


def configure():
    snap_data = os.environ.get('SNAP_DATA')

    if "jhack" not in snap_data:  # we could be in another snap
        logger.info("jhack running in unsnapped mode. Nothing to configure.")
        return

    logger.info("jhack running in snapped mode. Configuring...")

    # check `juju` command.
    try:
        juju_command = check_output(['which', 'juju'])
        logger.info(f'juju command is {juju_command}')
    except CalledProcessError:
        logger.error('juju command not found. '
                     'All jhacks depending on juju calls will bork.'
                     'if this is a snap, you might have forgotten to '
                     'connect jhack to juju.')

    # check that `JUJU_DATA` is set. if not, default it.
    jdata_key = 'JUJU_DATA'
    jdata = os.environ.get(jdata_key)
    logger.warning(f"JUJU_DATA is {jdata}")

    config_file = Path(snap_data) / 'config'
    if not config_file.exists():
        logger.warning(f'no config file found at: {config_file}.')
        logger.warning(f"setting JUJU_DATA to default: {default_juju_data_loc}")
        juju_data_loc = default_juju_data_loc
    else:
        logger.debug(f'config file found at: {config_file}.')
        try:
            juju_data_loc = config_file.read_text().split('=')[1].strip()
        except (IndexError, TypeError) as e:
            logger.error(f'error parsing config file: {e}.'
                         f'Will fall back to default juju data '
                         f'location: {default_juju_data_loc}')
            juju_data_loc = default_juju_data_loc

    logger.warning(f"setting JUJU_DATA to: {juju_data_loc}")
    os.environ[jdata_key] = juju_data_loc


if __name__ == '__main__':
    configure()
