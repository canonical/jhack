from typing import List
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("gather_endpoints")

import typer


def _flicker(
    model: str = None,
    include: List[str] = None,
    exclude: List[str] = None,
    wait_for_idle: bool = False,
    dry_run: bool = False,
):
    include = set(include) or set()
    exclude = set(exclude) or set()


def flicker(
    model: str = typer.Option(None, "--model", "-m", help="The model to flicker."),
    include: List[str] = typer.Option(
        None, "--include", "-i", help="Flicker this app."
    ),
    exclude: List[str] = typer.Option(
        None, "--exclude", "-e", help="Leave this app unflickered."
    ),
    wait_for_idle: bool = typer.Option(
        False,
        is_flag=True,
        help="Wait for all to be active/idle for at least 10 seconds "
        "before turning the lights back on.",
    ),
    dry_run: bool = typer.Option(
        False,
        is_flag=True,
        help="Don't actually do anything, just print what would have happened.",
    ),
):
    """Flickers the bugs out of this model.

    Removes all relations and adds them back in a random order.
    """

    return _flicker(
        model=model,
        include=include,
        exclude=exclude,
        wait_for_idle=wait_for_idle,
        dry_run=dry_run,
    )
