import shutil
from pathlib import Path
from subprocess import Popen
from time import sleep

jinx_root = Path(__file__).parent
path_to_jinx = jinx_root / 'jinx'


def jinx_installed() -> bool:
    return path_to_jinx.exists()


def install():
    """Install jinx source and unpack script."""
    if jinx_installed():
        print('existing jinx source found; cleaning up...')
        shutil.rmtree(path_to_jinx)

    print('installing jinx...')

    script = "git clone https://github.com/PietroPasotti/jinx"
    proc = Popen(script.split(' '), cwd=jinx_root)
    proc.wait()
    while proc.returncode is None:
        sleep(.1)

    print('jinx installed.'
          f'\nPYTHONPATH=PYTHONPATH;{path_to_jinx.absolute()}')
