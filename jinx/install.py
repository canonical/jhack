from pathlib import Path
from subprocess import Popen
from time import sleep

path = Path(__file__)
path_to_jinx = path.parent / 'jinx'


def jinx_installed() -> bool:
    return path_to_jinx.exists()


def install():
    """Install jinx source and unpack script."""
    script = "cd ./jinx; git clone https://github.com/PietroPasotti/jinx"
    proc = Popen(script.split(' '))
    proc.wait()
    while proc.returncode is None:
        sleep(.1)
    print('jinx installed. Why not:'
          f'sys.path.append({path_to_jinx.absolute()})')

