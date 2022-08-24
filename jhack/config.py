import os
from pathlib import Path
from subprocess import CalledProcessError, check_output

try:
    juju_command = check_output(['which', 'juju'])
except CalledProcessError:
    # we're snapped!

    config_dir = os.environ.get('SNAP_DATA')
    config_file = Path(config_dir) / 'config'

    try:
        juju, jujudata = config_file.read_text().strip().split('\n')
        JUJU_COMMAND = juju.split('=')[1]
        JUJU_DATA = jujudata.split('=')[1]
        os.environ["JUJU_DATA"] = JUJU_DATA
    except (KeyError, FileNotFoundError, Exception) as e:
        print(e)
        JUJU_COMMAND = "BORK"

else:
    JUJU_COMMAND = juju_command.decode('utf-8').strip()

try:
    out = check_output(['which', JUJU_COMMAND])
    print(f'juju command = {JUJU_COMMAND}::{out}')
except CalledProcessError:
    print('juju command not found. '
          'All jhacks depending on juju calls will bork.' 
          'if this is a snap, configure jhack by running '
          '`snap set jhack juju /path/to/juju`;'
          'else ensure the `juju` command is available.')
