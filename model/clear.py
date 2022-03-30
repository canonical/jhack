from typing import Set, Optional

from juju import jasyncio
from juju.application import Application

from helpers import get_current_model
from logger import logger


def parse_app_or_app_list(s: Optional[str]) -> Set[str]:
    if s is None:
        return set()
    if ',' in s:
        return set(s.split(','))
    return {s}


async def clear_model(apps: str = (),
                      keep: str = (),
                      dry_run: bool = False):
    """Destroys all applications from a model, or a specified subset of them,
    while keeping a few.
    """
    apps, keep = map(parse_app_or_app_list, (apps, keep))
    async with get_current_model() as model:
        app: Application
        existing_apps = model.applications.keys()

        if not existing_apps:
            logger.info('This model is already empty.')
            return

        if invalid := apps - existing_apps:
            logger.error(f"Applications {invalid} not found in model.")
            return

        to_destroy = apps or existing_apps - keep
        if not to_destroy:
            logger.info(f"Model clear.")
            return

        destroying = '\n - ' + '\n - '.join(to_destroy)
        if dry_run:
            print(f"Would destroy: {destroying}")
            return
        else:
            print(f"Destroying: {destroying}")

        await jasyncio.gather(
            *(model.applications[app].destroy() for app in to_destroy))

        logger.info('Model cleared.')
        # todo find way to do --force --no-wait


def sync_clear_model(apps: str = None, keep: str = None, dry_run: bool = False):
    jasyncio.run(clear_model(apps, keep, dry_run=dry_run))
