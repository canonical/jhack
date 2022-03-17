import asyncio
import os
import time
from pathlib import Path
from subprocess import Popen, PIPE
from typing import List

from juju import jasyncio

from logger import logger


def walk(obj, recursive, check_ext) -> List[Path]:
    walked = []
    for obj_ in obj.iterdir():
        if obj_.is_file() and check_ext(obj_):
            walked.append(obj_)
        elif recursive:
            if obj_.is_dir():
                walked.extend(walk(obj_))
            else:
                logger.warning(f'skipped {obj_}')
    return walked


def sync(local_folder: str,
         unit: str,
         remote_root: str = None,
         container_name: str = 'charm',
         polling_interval: float = 1,
         recursive: bool = False,
         exts: List[str] = None,
         dry_run: bool = False):
    """Syncs a local folder to a remote juju unit via juju scp.

    Example:
      suppose you're developing a tester-charm and the deployed app name is
      'tester-charm'; you can sync the local src with the remote src by
      running:

      jhack utils sync ./tests/integration/tester_charm/src tester-charm

      The remote root defaults to whatever juju ssh defaults to; that is
      / for workload containers but /var/lib/juju for sidecar containers.
      If you wish to use a different remote root, keep in mind that the path
      you pass will be interpreted to this relative remote root which we have no
      control over.
    """
    path = Path(local_folder).resolve()
    spec = unit.split('/')

    if len(spec) == 2:
        app, unit = spec
    else:
        app = spec[0]
        unit = 0

    if not path.is_dir():
        logger.error(f'not a directory: {path}')
        return

    def check_ext(file):
        if not exts:
            return True
        return str(file).split('.')[-1] in exts

    watch_list = walk(path, recursive, check_ext)
    if not watch_list:
        logger.error('nothing to watch')
        return

    logger.info('watching: \n\t%s' % "\n\t".join(map(str, watch_list)))
    logger.info('Ctrl+C to interrupt')

    hashes = {}
    while True:
        # determine which files have changed
        changed_files = []
        for file in watch_list:
            logger.debug(f'checking {file}')
            if old_tstamp := hashes.get(file, None):
                new_tstamp = os.path.getmtime(file)
                if new_tstamp == old_tstamp:
                    logger.debug(f'timestamp unchanged {old_tstamp}')
                    continue
                logger.debug(f'changed: {file}')
                hashes[file] = new_tstamp
                changed_files.append(file)
            else:
                hashes[file] = os.path.getmtime(file)

        if changed_files:
            if dry_run:
                print('would sync:', changed_files)
                continue

            loop = asyncio.events.get_event_loop()

            remote_root = remote_root or f"/var/lib/juju/agents/" \
                                         f"unit-{app}-{unit}/charm/"
            loop.run_until_complete(
                jasyncio.gather(
                    *(push_to_remote_juju_unit(changed, remote_root,
                                               app, unit, container_name)
                      for changed in changed_files)
                )
            )

        time.sleep(polling_interval)


async def push_to_remote_juju_unit(file: Path, remote_root: str,
                                   app, unit, container_name):
    remote_file_path = remote_root + str(file)[len(os.getcwd()) + 1:]
    container_opt = f"--container {container_name} " if container_name else ""
    cmd = f"juju scp {container_opt}{file} {app}/{unit}:{remote_file_path}"
    proc = Popen(cmd.split(' '), stdout=PIPE, stderr=PIPE)
    retcode = proc.returncode
    if retcode != None:
        logger.error(f"{cmd} errored with code {retcode}: "
                     f"\nstdout={proc.stdout.read()}, "
                     f"\nstderr={proc.stderr.read()}")

    logger.info(f'synced {file}')