import time
from datetime import datetime
from subprocess import Popen
from time import sleep

from jinx.install import jinx_installed


def pack_jinx():
    """Packs a jinx. Alias for jinx.unpack; charmcraft pack."""
    if not jinx_installed():
        print('run jhack jinx install first.')
        return

    begin = datetime.now()
    cmd = Popen('unpack; charmcraft pack'.split())
    cmd.wait()

    while cmd.returncode == None:
        sleep(.1)
    elapsed = datetime.now() - begin

    print(f'jinx packed ({elapsed.seconds}s)')
