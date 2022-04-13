import os
from pathlib import Path
from subprocess import Popen, PIPE

from logger import logger


def unbork_juju(model_name: str = 'foo',
                controller_name: str = 'mk8scloud',
                juju_channel: str = 'stable',
                microk8s_channel: str = 'stable',
                dry_run: bool = False):
    """reset your Juju + Microk8s installation.

    Purge-refresh juju and microk8s snaps, bootstrap a new controller and add a
    new model to it.
    Have a good day!
    """
    unbork_juju_script = Path(__file__).parent / 'unbork_juju'
    if not unbork_juju_script.exists():
        raise RuntimeError(
            f'unbork_juju script not found. Is it where it should be? '
            f'{unbork_juju_script}'
        )
    if not os.access(unbork_juju_script, os.X_OK):
        raise RuntimeError(
            'unbork_juju script is not executable. Ensure it has X permissions.'
        )
    if not unbork_juju_script.exists():
        raise RuntimeError(
            f'unable to locate unbork_juju shell script '
            f'({unbork_juju_script!r})'
        )

    cmd = [str(unbork_juju_script),
           '-J', juju_channel,
           '-M', microk8s_channel,
           '-m', model_name,
           '-c', controller_name]

    if dry_run:
        print('would run:', cmd)

    proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
    proc.wait()
    if return_code := proc.returncode != 0:
        logger.error(f"{cmd} failed with return code {return_code}")
        logger.error(proc.stdout.read().decode('utf-8'))
        logger.error(proc.stderr.read().decode('utf-8'))
    else:
        print(proc.stdout.read().decode('utf-8'))