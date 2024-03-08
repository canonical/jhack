import shlex
import subprocess
from pathlib import Path
from subprocess import check_output, CalledProcessError
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from jhack.helpers import get_all_units, Target, push_file, get_units
from jhack.logger import logger

logger = logger.getChild(__file__)


def _parse_target(target: List[str], model: str) -> List[Target]:
    unit_targets = []
    for tgt in target:
        if "/" in tgt:
            unit_targets.append(Target.from_name(tgt))
        try:
            unit_targets.extend(get_units(tgt, model=model))
        except KeyError:
            logger.error(
                f"invalid target {tgt!r}: not an unit, nor an application in model {model or '<the current model>'!r}"
            )
    return unit_targets


def _print_plan(targets: List[Target]):
    table = {}
    for target in targets:
        # if dispatch.ori is present; dispatch is lobo dispatch (or cleanup failed; either way)
        cmd = f"juju ssh {target.unit_name} ls {target.charm_root_path/'dispatch.ori'}"
        try:
            check_output(shlex.split(cmd), stderr=subprocess.PIPE)
            table[target] = True

        except CalledProcessError:
            table[target] = False

    t = Table("unit", "lobotomy", title="lobotomy plan")
    for target, l in table.items():
        t.add_row(
            target.unit_name,
            Text("active" if l else "inactive", style="bold red" if l else "green"),
        )

    Console().print(t)


def _lobotomy(
    target: List[str],
    _all: bool = False,
    dry_run: bool = False,
    model: Optional[str] = None,
    undo: Optional[bool] = False,
    plan: Optional[bool] = False,
):
    targets: List[Target] = []
    if _all:
        if target:
            logger.warning(f"`all` flag overrules provided targets {target}.")
        targets.extend(get_all_units(model))
    elif target:
        targets.extend(_parse_target(target, model))

    if not targets:
        logger.error("no targets provided; nothing to do.")
        exit(1)

    logger.debug(f"gathered targets {targets}")

    if plan:
        _print_plan(targets)
        return

    for t in targets:
        logger.info(f"lobotomizing {t}...")
        _do_lobotomy(t, model, dry_run, undo)


def _do_lobotomy(
    target: Target, model: Optional[str], dry_run: bool = False, undo: bool = False
):
    if undo:
        # move dispatch.ori back to dispatch
        move_cmd = f"juju ssh {target.unit_name} mv {target.charm_root_path/'dispatch.ori'} {target.charm_root_path/'dispatch'}"
        if dry_run:
            print("would run:")
            print(f"\t{move_cmd}")
            return

    else:
        # move dispatch to dispatch.ori
        move_cmd = f"juju ssh {target.unit_name} mv {target.charm_root_path/'dispatch'} {target.charm_root_path/'dispatch.ori'}"
        # push lobo dispatch in place of dispatch

    if dry_run:
        print("would run:")
        print(f"\t{move_cmd}")

    else:
        try:
            check_output(shlex.split(move_cmd))
        except CalledProcessError as e:
            logger.exception(e)

    if not undo:
        push_file(
            target.unit_name,
            local_path=Path(__file__).parent / "dispatch-lobo",
            remote_path="dispatch",
            model=model,
            container="charm",
            dry_run=dry_run,
        )

    if undo:
        print(f"{target.unit_name}: lobotomy reversed")
    else:
        print(f"{target.unit_name}: lobotomy applied")


def lobotomy(
    target: List[str] = typer.Argument(
        None,
        help="The target to lobotomize. Can be an app (lobotomizes all units),"
        " or a unit (lobotomizes that unit only).",
    ),
    _all: bool = typer.Option(
        False,
        "--all",
        is_flag=True,
        help="Overrules `target`; lobotomizes the whole model.",
    ),
    plan: bool = typer.Option(
        False,
        "--plan",
        is_flag=True,
        help="Print an overview of the lobotomy status of the units and exit.",
    ),
    undo: bool = typer.Option(
        False,
        "--undo",
        is_flag=True,
        help="Undoes a lobotomy.",
    ),
    model: str = typer.Option(None, "-m", "--model", help="Which model to look into."),
    dry_run: bool = False,
):
    """Lobotomizes one or multiple charms, preventing them from processing any incoming events."""
    return _lobotomy(
        target=target, _all=_all, undo=undo, dry_run=dry_run, model=model, plan=plan
    )


if __name__ == "__main__":
    _lobotomy(["tempo-k8s"])
