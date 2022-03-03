#!/bin/python3
import asyncio
import os
import time
import contextlib
import logging
from typing import List, Set
from subprocess import Popen, PIPE

from pathlib import Path
from juju import jasyncio
from juju.application import Application
from juju.model import Model

logger = logging.getLogger('jhack')
logger.setLevel('INFO')


@contextlib.asynccontextmanager
async def get_current_model() -> Model:
    model = Model()
    try:
        # connect to the current model with the current user, per the Juju CLI
        await model.connect()
        yield model

    finally:
        if model.is_connected():
            print('Disconnecting from model')
            await model.disconnect()


async def clear_model(apps: List[str]):
    async with get_current_model() as model:
        app: Application
        app_mapping = model.applications

        if app_mapping:
            invalid = {a for a in apps if a not in model.applications}
            if invalid:
                logger.error(f"applications {invalid} not found in model.")
                return

        to_destroy = apps or app_mapping.keys()
        if not to_destroy:
            logger.info(f"model clear.")
            return

        logger.info('destroying: \n' + '\n\t'.join(
            (app for app in to_destroy)))
        await jasyncio.gather(
            *(app_mapping[app].destroy() for app in to_destroy))

        logger.info('model clear.')
        # todo find way to do --force --no-wait


async def app_action(action):
    if action == 'clear':
        async with get_current_model() as model:
            app: Application
            logger.info('destroying: \n' + '\n\t'.join(
                (app for app in model.applications.keys())))
            await jasyncio.gather(
                *(app.destroy() for app in model.applications.values()))
            # todo find way to do --force --no-wait
    else:
        logger.error(f'unknown action: {action}')


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


async def push(file: Path, remote_root: str, app, unit, container_name):
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


def sync(local_folder: str,
         unit: str,
         remote_root: str = None,
         container_name: str = 'charm',
         polling_interval: float = 1,
         recursive: bool = False,
         exts: List[str] = None):
    path = Path(local_folder).resolve()
    spec = unit.split('/')
    if len(spec) == 2:
        app, unit = spec
    else:
        app = spec[0]
        unit = 0

    remote_root = remote_root or f"/var/lib/juju/agents/unit-{app}-{unit}/charm/"

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
            loop = asyncio.events.get_event_loop()
            loop.run_until_complete(
                jasyncio.gather(
                    *(push(changed, remote_root, app, unit, container_name)
                      for changed in changed_files)
                )
            )

        logger.debug('ping')
        time.sleep(polling_interval)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    import typer

    model = typer.Typer(name='model')


    @model.command()
    def clear(apps: List[str] = None):
        jasyncio.run(clear_model(apps))


    utils = typer.Typer(name='utils')

    sync_cmd = utils.command()(sync)

    app = typer.Typer(name='jhack')
    app.add_typer(model)
    app.add_typer(utils)

    app()
