import os
from pathlib import Path
from subprocess import Popen
from time import sleep

from jinx.install import jinx_installed


def init_jinx():
    """Initializes the cwd as jinx root."""
    if not jinx_installed():
        print('run jhack jinx install first.')
        return

    # charmcraft init
    proc = Popen('charmcraft init'.split())
    proc.wait()
    while proc.returncode is None:
        sleep(.1)

    # cleanup metadata files
    to_remove = ['charmcraft', 'actions', 'metadata', 'config']
    for file in to_remove:
        os.remove(Path()/(file + '.yaml'))

    print('all clear! Happy jinxing.')