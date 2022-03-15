#!/bin/python3
import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path
from subprocess import Popen, PIPE
from typing import List

import typer
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


async def _remove_model(model_name: str, force=True,
                        no_wait=True, destroy_storage=True,
                        dry_run=False):
    cmd = f'juju destroy-model {model_name} ' \
          f'{"--force " if force else ""}' \
          f'{"--no-wait " if no_wait else ""}' \
          f'{"--destroy-storage " if destroy_storage else ""}-y'

    if dry_run:
        logger.info(f'would destroy model {model_name} with: {cmd!r}')
        return
    else:
        logger.info(f'destroying model {model_name} ({cmd})')

    proc = Popen(cmd.split(' '), stdout=PIPE, stderr=PIPE)
    logger.info(f'spawned off model destroyer to pid={proc.pid}')
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(
            f"{cmd!r} failed with retcode {proc.returncode!r}; "
            f"\nstdout={proc.stdout.read().decode('utf-8')}"
            f"\nstderr={proc.stdout.read().decode('utf-8')}"
        )


def rmodel(
        model_name=typer.Argument(
            'model_name',
            help='comma-separated list of models to be removed, or single '
                 'globbed name'),
        force: bool = True,
        no_wait: bool = True,
        destroy_storage: bool = True,
        dry_run: bool = False):
    if '*' in model_name:
        if model_name.endswith('*'):
            method = str.startswith
        elif model_name.startswith('*'):
            method = str.endswith
        else:
            raise ValueError(
                f'invalid globbing: {model_name!r}; * only supported '
                f'at the end or start of a pattern'
            )
        filterer = lambda name: method(name, model_name.strip('*'))

        proc = Popen('juju models'.split(' '), stdout=PIPE)
        raw = proc.stdout.read().decode('utf-8').strip()
        lines = raw.split('\n')[4:]
        all_models = [line.split(' ')[0].strip('*') for line in lines]
        to_remove = tuple(filter(filterer, all_models))
        if not to_remove:
            logger.info(
                f'Globbed name {model_name!r} yielded no matches; method {all_models}.')

    else:
        to_remove = model_name.split(',')

    if not to_remove:
        logger.info('Nothing to remove.')
        return

    _remove_fn = lambda model: _remove_model(
        model, force, no_wait, destroy_storage, dry_run)
    logger.info('Preparing to remove\n\t' + '\n\t'.join(to_remove))
    asyncio.get_event_loop().run_until_complete(
        jasyncio.gather(*(_remove_fn(model) for model in to_remove))
    )
    logger.info('Done.')


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


def unfuck_juju(model_name: str = 'foo',
                controller_name: str = 'mk8scloud',
                juju_channel: str = 'stable',
                microk8s_channel: str = 'stable'):
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

    proc = Popen(cmd)
    proc.wait()
    if returncode := proc.returncode != 0:
        logger.error(f"{cmd} failed with return code {returncode}")
        logger.error(proc.stdout.read().decode('utf-8'))
        logger.error(proc.stderr.read().decode('utf-8'))
    else:
        print(proc.stdout.read().decode('utf-8'))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    model = typer.Typer(name='model')


    @model.command()
    def clear(apps: List[str] = None):
        jasyncio.run(clear_model(apps))


    utils = typer.Typer(name='utils')

    sync_cmd = utils.command()(sync)
    unfuck_juju_cmd = utils.command()(unfuck_juju)

    ctr = typer.Typer(name='ctr')
    rmodel = ctr.command()(rmodel)

    app = typer.Typer(name='jhack')
    app.add_typer(model)
    app.add_typer(utils)
    app.add_typer(ctr)

    app()
