import random
import shlex
from subprocess import check_output, CalledProcessError
from time import sleep
from typing import List, Dict

import typer

from jhack.helpers import juju_status
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("gather_endpoints")


def _mancioppi(
    model: str = None,
    include: List[str] = None,
    exclude: List[str] = None,
    step: int = 2,
    reverse: bool = False,
    dry_run: bool = False,
    wait_user: bool = False,
):
    include = set(include) or set()
    exclude = set(exclude) or set()
    if include and exclude:
        exit("only pass one of --include and --exclude.")

    print("Gathering status...")

    status = juju_status(json=True, model=model)
    _all = set(status["applications"])

    targets = list(_all.intersection(include) or _all.difference(exclude))

    print(f"Will Mancioppi: {list(targets)}")

    remove_n = {}
    for app in targets:
        scale = len(status["applications"][app].get("units", []))

        if reverse:
            # if we're first scaling up, we can always go all the way
            remove_n[app] = step
        else:
            remove_n[app] = min(scale, step)

    def down(_targets):
        done = []
        for app in targets:
            n = remove_n[app]
            cmd = f"juju remove-unit {app} --num-units {n}"
            if dry_run:
                print(f"\t{cmd}")
            else:
                print(f"Manciopping {app}...")
                try:
                    check_output(shlex.split(cmd))
                except CalledProcessError:
                    logger.error(f"error scaling {app} down by {n}. Skipping...")
                    logger.debug(f"error scaling {app} down by {n}", exc_info=True)
                    continue
            done.append(app)
        return done

    def up(_targets):
        done = []
        for app in targets:
            n = remove_n[app]
            cmd = f"juju add-unit {app} --num-units {n}"

            if dry_run:
                print("\t" + cmd)
            else:
                print(f"Demanciopping {app}...")
                try:
                    check_output(shlex.split(cmd))
                except CalledProcessError:
                    logger.error(f"error scaling {app} back up by {n}.")
                    logger.debug(f"error scaling {app} back up by {n}", exc_info=True)
                    continue
            done.append(app)
        return done

    if reverse:
        one, two = down, up
    else:
        one, two = up, down

    random.shuffle(targets)

    modified = one(targets)

    if dry_run:
        if wait_user:
            print(f"would wait for user to enter [y]...")
    elif wait_user:
        try:
            confirmed = typer.confirm("continue")
        except typer.Abort:
            confirmed = False
        if not confirmed:
            print("Aborted by user.")
            exit(0)

    random.shuffle(modified)
    two(modified)


def mancioppi(
    model: str = typer.Option(None, "--model", "-m", help="The model to Mancioppi."),
    include: List[str] = typer.Option(
        None, "--include", "-i", help="Mancioppi this app."
    ),
    exclude: List[str] = typer.Option(
        None, "--exclude", "-e", help="Do not Mancioppi this app."
    ),
    step: int = typer.Option(2, "--step", "-s", help="Mancioppi steppi."),
    wait_user: bool = typer.Option(
        True, is_flag=True, help="Wait for user input before Demanciopping."
    ),
    reverse: bool = typer.Option(
        False, is_flag=True, help="First scale down, then up."
    ),
    dry_run: bool = typer.Option(
        False,
        is_flag=True,
        help="Don't actually do anything, just print what would have happened.",
    ),
):
    """Micheles the bugs out of this model.

    Scales all apps down by ``step``, then scales them all back up by ``step``.
    """

    return _mancioppi(
        model=model,
        include=include,
        exclude=exclude,
        step=step,
        reverse=reverse,
        dry_run=dry_run,
        wait_user=wait_user,
    )
