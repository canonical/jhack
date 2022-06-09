import os
import shutil
from pathlib import Path
from subprocess import Popen
from time import sleep

from jinx.install import jinx_installed, path_to_jinx
from jinx.cleanup import cleanup


def init_jinx(force: bool = False):
    """Initializes the cwd as jinx root. Basically `jinxcraft init`."""
    if not jinx_installed():
        print('run jhack jinx install first.')
        return

    # charmcraft init
    cmd = 'charmcraft init'
    if force:
        cmd += ' --force'
    proc = Popen(cmd.split())
    proc.wait()
    while proc.returncode is None:
        sleep(.1)

    if not proc.returncode == 0:
        print('charmcraft exited with status nonzero. '
              'There is likely to be some output above.')
        print('operation aborted.')
        return

    # cleanup metadata files
    cleanup()

    # copy template to src/charm.py
    shutil.copy(path_to_jinx / 'resources' / 'template_jinx.py',
                Path() / 'src' / 'charm.py')

    print('all clear! Happy jinxing.')
