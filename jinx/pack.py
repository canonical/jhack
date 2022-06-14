import os
from datetime import datetime
from pathlib import Path
from subprocess import Popen
from time import sleep

from typer import Argument

from jinx.cleanup import cleanup
from jinx.install import jinx_installed

PATH_TO_JINX_PACKAGE = Path(__file__).parent / 'jinx'


def pack(charm_source: Path = Argument(
    None, help='Path to file containing the Jinx subclass to pack; '
               'e.g. ./path/to/charm.py')):
    """Unpacks the jinx using jinx.unpack. Basically `jinxcraft pack`."""
    if not jinx_installed():
        print('run jhack jinx install first.')
        return

    if not charm_source:
        print('charm_source not provided, guessing `./src/charm.py`')
    charm_source = Path(
        charm_source) if charm_source else Path() / 'src' / 'charm.py'
    if not charm_source.name == 'charm.py':
        print(f'expected charm.py file, not {charm_source}')
        return
    begin = datetime.now()
    env = os.environ
    cmd = Popen(
        f'{PATH_TO_JINX_PACKAGE}/unpack.py ./src/charm.py'.split(),
        cwd=charm_source.parent.parent)
    cmd.wait()

    cmd = Popen(
        'charmcraft pack'.split(),
        cwd=charm_source.parent.parent)
    cmd.wait()

    while cmd.returncode == None:
        sleep(.1)

    if cmd.returncode != 0:
        print("command exited with code nonzero: something went wrong. "
              "There's likely to be additional output above.")
        print("aborting...")
        return

    # delete all metadata files
    cleanup()

    print(f'jinx packed ({(datetime.now() - begin).seconds}s)')
