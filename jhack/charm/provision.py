import time
from pathlib import Path

from jhack.helpers import JPopen
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild('provision')

PROV_SCRIPT_ROOT = Path('~/.cprov/').expanduser().absolute()


def _get_script(script: str) -> str:
    pth = Path(script)
    if pth.exists() and pth.is_file():
        logger.debug(f'loaded script file {script}')
        return pth.read_text()
    script_from_root = PROV_SCRIPT_ROOT / script
    if script_from_root.exists() and script_from_root.is_file():
        logger.debug(f'found {script} in `~/.cprov/`')
        return script_from_root.read_text()
    # we'll interpret script as a literal bash script
    logger.debug(f'interpreting {script[:10]}... as an executable script')
    return script


def _provision_unit(unit: str, script: str = 'default', container='charm'):
    try:
        app_name, unit_n_txt = unit.split('/')
        unit_n = int(unit_n_txt)
    except (ValueError, TypeError) as e:
        logger.debug(e)
        print(f"invalid unit name {unit}: expected <app_name:str>/<unit_n:int>,"
              f"e.g. `traefik-k8s/0`, `prometheus/2`.")
        return

    script = _get_script(script)

    cmd = f'juju ssh --container {container} {unit} bash sh -c "{script}"'
    logger.debug(f"cmd: {cmd}")
    proc = JPopen(cmd.split())

    while proc.returncode is None:
        stdout = proc.stdout.read().decode('utf-8')
        print(stdout)
        time.sleep(.1)

    if proc.returncode != 0:
        logger.debug(f'process returned with returncode={proc.returncode}')
        logger.error(proc.stdout.read().decode('utf-8'))
        print(f'failed provisioning {unit}')
        return


if __name__ == '__main__':
    _provision_unit('traefik-route-k8s/0')
