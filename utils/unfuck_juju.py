import os
from pathlib import Path
from subprocess import Popen

from logger import logger


def unfuck_juju(model_name: str = 'foo',
                controller_name: str = 'mk8scloud',
                juju_channel: str = 'stable',
                microk8s_channel: str = 'stable',
                dry_run: bool = False):
    """Unfuck your Juju + Microk8s installation.

    Purge-refresh juju and microk8s snaps, bootstrap a new controller and add a
    new model to it.
    Have a good day!
    """
    unfuck_juju_script = Path(__file__).parent / 'unfuck_juju'
    if not os.access(unfuck_juju_script, os.X_OK):
        raise RuntimeError(
            'unfuck_juju script is not executable. Ensure it has X permissions.'
        )
    if not unfuck_juju_script.exists():
        raise RuntimeError(
            f'unable to locate unfuck_juju shell script '
            f'({unfuck_juju_script!r})'
        )

    cmd = [str(unfuck_juju_script),
           '-J', juju_channel,
           '-M', microk8s_channel,
           '-m', model_name,
           '-c', controller_name]

    if dry_run:
        print('would run:', cmd)

    proc = Popen(cmd)
    proc.wait()
    if return_code := proc.returncode != 0:
        logger.error(f"{cmd} failed with return code {return_code}")
        logger.error(proc.stdout.read().decode('utf-8'))
        logger.error(proc.stderr.read().decode('utf-8'))
    else:
        print(proc.stdout.read().decode('utf-8'))