import asyncio
import os
from subprocess import Popen, PIPE

import typer
from juju import jasyncio

from jhack.config import JUJU_COMMAND
from jhack.helpers import list_models, current_model
from jhack.logger import logger


def _exec(cmd):
    return_code = os.system(cmd)
    if return_code != 0:
        raise RuntimeError(
            f"{cmd!r} failed with retcode {return_code!r}; "
        )
    return return_code


async def _remove_model(model_name: str, force=True,
                        no_wait=True, destroy_storage=True,
                        restart=False,
                        dry_run=False):
    cmd = f'{JUJU_COMMAND} destroy-model {model_name} ' \
          f'{"--force " if force else ""}' \
          f'{"--no-wait " if no_wait else ""}' \
          f'{"--destroy-storage " if destroy_storage else ""}-y'

    nuking = not restart
    if nuking:
        # if we're nuking, we can avoid the wait and
        # redirect the cmd output into the void
        cmd = 'nohup ' + cmd + ' > /dev/null 2>&1 &'

    if dry_run:
        print(f'would destroy model {model_name} with: {cmd!r}')
        if restart:
            print(f'would recreate a fresh model called {model_name}')
        return

    print(f'{"nuking" if nuking else "shutting down"} :: {model_name} {"⚛" if nuking else "✞"}')

    return_code = _exec(cmd)
    logger.info(f'spawned off model destroyer ({return_code}')

    if restart:
        print(f'cycling :: {model_name} ♽')
        return_code = _exec(f"{JUJU_COMMAND} add-model {model_name}")
        logger.info(f'spawned off model creator ({return_code}')


def rmodel(
        model_name=typer.Argument(
            None,
            help='comma-separated list of models to be removed, or single '
                 'globbed name'),
        force: bool = True,
        restart: bool = False,
        no_wait: bool = True,
        destroy_storage: bool = True,
        dry_run: bool = False):

    if not model_name:
        to_remove = (current_model(), )
        logger.info(f'Preparing to remove current model ({to_remove[0]}...')

    elif '*' in model_name:
        if model_name.endswith('*'):
            method = str.startswith
        elif model_name.startswith('*'):
            method = str.endswith
        else:
            raise ValueError(
                f'invalid globbing: {model_name!r}; * only supported '
                f'at the end or start of a pattern'
            )
        all_models = list_models()
        key = lambda name: method(name, model_name.strip('*'))
        to_remove = tuple(filter(key, all_models))
        if not to_remove:
            logger.info(
                f'Globbed name {model_name!r} yielded no matches; '
                f'method {all_models}.')

    else:
        to_remove = model_name.split(',')

    if not to_remove:
        logger.info('Nothing to remove.')
        return

    # ensure no model has the current-model star
    to_remove_clean = tuple(m.strip('*') for m in to_remove)

    _remove_fn = lambda model: _remove_model(
        model, force, no_wait, destroy_storage, restart, dry_run)
    logger.info('Preparing to remove\n\t' + '\n\t'.join(to_remove_clean))
    asyncio.get_event_loop().run_until_complete(
        jasyncio.gather(*(_remove_fn(model) for model in to_remove_clean))
    )
    logger.info('Done.')