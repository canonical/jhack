import os
from pathlib import Path
from subprocess import check_call, CalledProcessError

is_snapped = False
if config_dir := os.environ.get('SNAP_DATA'):
    is_snapped = True

if is_snapped:
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
    JUJU_COMMAND = "/snap/bin/juju"

try:
    check_call(['which', JUJU_COMMAND])
except CalledProcessError:
    print('juju command not found. '
          'All jhacks depending on juju calls will bork.')

    if is_snapped:
        print('configure jhack by running '
              '`snap set jhack juju /path/to/juju`.')
    else:
        print('install juju to proceed.')
