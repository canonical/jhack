import asyncio
from subprocess import Popen, PIPE

import typer
from juju import jasyncio

from logger import logger


async def _remove_model(model_name: str, force=True,
                        no_wait=True, destroy_storage=True,
                        restart=True,
                        dry_run=False):
    cmd = f'juju destroy-model {model_name} ' \
          f'{"--force " if force else ""}' \
          f'{"--no-wait " if no_wait else ""}' \
          f'{"--destroy-storage " if destroy_storage else ""}-y'

    if dry_run:
        logger.info(f'would destroy model {model_name} with: {cmd!r}')
        if restart:
            logger.info(f'would recreate a fresh model called {model_name}')
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

    if not restart:
        return

    cmd = f'juju add-model {model_name}'
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
        restart: bool = True,
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
        model, force, no_wait, destroy_storage, restart, dry_run)
    logger.info('Preparing to remove\n\t' + '\n\t'.join(to_remove))
    asyncio.get_event_loop().run_until_complete(
        jasyncio.gather(*(_remove_fn(model) for model in to_remove))
    )
    logger.info('Done.')