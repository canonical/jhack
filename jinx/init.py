import os
import shutil
from pathlib import Path
from subprocess import Popen
from time import sleep

from jinx.install import jinx_installed, path_to_jinx


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

    # copy template to src/charm.py
    shutil.copy(path_to_jinx / 'resources' / 'template_jinx.py', Path() / 'src' / 'charm.py')

    print('all clear! Happy jinxing.')