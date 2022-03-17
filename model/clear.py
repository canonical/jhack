import contextlib
from typing import List

from juju import jasyncio
from juju.application import Application
from juju.model import Model

from logger import logger


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


async def clear_model(apps: List[str] = (),
                      keep: List[str] = (),
                      dry_run: bool = False):
    """Destroys all applications from a model, or a specified subset of them,
    while keeping a few.
    """
    apps = set(apps)
    async with get_current_model() as model:
        app: Application
        existing_apps = model.applications.keys()

        if not existing_apps:
            logger.info('This model is already empty.')
            return

        if invalid := apps - existing_apps:
            logger.error(f"Applications {invalid} not found in model.")
            return

        to_destroy = apps or existing_apps - set(keep)
        if not to_destroy:
            logger.info(f"Model clear.")
            return

        destroying = '\n' + '\n\t'.join(to_destroy)
        if dry_run:
            print(f"Would destroy: {destroying}.")
            return
        else:
            logger.info(f'Destroying: {destroying}')

        await jasyncio.gather(
            *(model.applications[app].destroy() for app in to_destroy))

        logger.info('Model cleared.')
        # todo find way to do --force --no-wait


def sync_clear_model(apps: List[str] = None, dry_run: bool = False):
    jasyncio.run(clear_model(apps, dry_run=dry_run))