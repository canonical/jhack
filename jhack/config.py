import os
from pathlib import Path
from subprocess import check_call, CalledProcessError

is_snapped = False
if config_dir := os.environ.get('SNAP_DATA'):
    is_snapped = True

if is_snapped:
    config_file = Path(config_dir) / 'config'
    print(f'loaded config file {config_file}')

    try:
        JUJU_COMMAND = config_file.read_text().strip()
    except:
        JUJU_COMMAND = "BORK"

    print(f'juju cmd = {JUJU_COMMAND}')

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
