import shutil
from pathlib import Path
from time import sleep

from jhack.helpers import JPopen

jinx_root = Path(__file__).parent
path_to_jinx = jinx_root / "jinx"


def jinx_installed() -> bool:
    return path_to_jinx.exists()


def install():
    """Install jinx source and unpack script."""
    if jinx_installed():
        print("existing jinx source found; cleaning up...")
        shutil.rmtree(path_to_jinx)

    print("installing jinx...")

    script = "git clone https://github.com/PietroPasotti/jinx"
    proc = JPopen(script.split(" "), cwd=jinx_root)
    proc.wait()
    while proc.returncode is None:
        sleep(0.1)

    print("jinx installed." f"\nPYTHONPATH=PYTHONPATH;{path_to_jinx.absolute()}")
