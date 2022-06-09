from datetime import datetime
from subprocess import Popen
from time import sleep

from jinx.cleanup import cleanup
from jinx.install import jinx_installed


def pack():
    """Unpacks the jinx using jinx.unpack. Basically `jinxcraft pack`."""
    if not jinx_installed():
        print('run jhack jinx install first.')
        return

    begin = datetime.now()
    cmd = Popen('unpack; charmcraft pack'.split())
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
