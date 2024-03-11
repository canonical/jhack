import shlex
import subprocess
import tempfile
from pathlib import Path
from subprocess import CalledProcessError, check_output
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from jhack.helpers import Target, get_all_units, get_units, push_file, get_substrate
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


def _parse_disabled(out):
    return (out[len("DISABLED=") :]).strip()


def _is_lobotomized(target: Target):
    """Return False if not, return an optional list of events (for selective lobotomy)."""
    # if dispatch.ori is present; dispatch is lobo dispatch (or cleanup failed; either way)
    cmd = f"juju ssh {target.unit_name} cat {target.charm_root_path/'dispatch'} | grep DISABLED="
    try:
        out = check_output(shlex.split(cmd), stderr=subprocess.PIPE, text=True)
        return _parse_disabled(out)
    except CalledProcessError:
        return False


def _print_plan(targets: List[Target]):
    table = {target: _is_lobotomized(target) for target in targets}
    t = Table("unit", "lobotomy", "events", title="lobotomy plan")
    for target, l in table.items():
        t.add_row(
            target.unit_name,
            Text("active" if l else "inactive", style="bold red" if l else "green"),
            Text("n/a", style="light grey")
            if l is False
            else (l or Text("all", style="bold red")),
        )

    Console().print(t)


def _lobotomy(
    target: List[str],
    _all: bool = False,
    events: List[str] = None,
    dry_run: bool = False,
    model: Optional[str] = None,
    undo: Optional[bool] = False,
    plan: Optional[bool] = False,
):
    targets: List[Target] = []
    if undo or plan:
        # in the case of plan or undo, no targets = all targets
        _all = True

    if _all:
        if target:
            logger.warning(f"`all` flag overrules provided targets {target}.")
        targets.extend(get_all_units(model))
    elif target:
        targets.extend(_parse_target(target, model))

    if not targets:
        exit("no targets provided. Aborting...")

    if plan:
        _print_plan(targets or get_all_units(model))
        return

    if undo:
        targets = [t for t in targets if _is_lobotomized(t)]
    else:
        targets = [t for t in targets if not _is_lobotomized(t)]

    if not targets:
        exit("no changes to apply.")

    logger.debug(f"gathered targets {targets}")

    for t in targets:
        logger.info(f"lobotomizing {t}...")
        _do_lobotomy(t, model, dry_run, undo, events)


def _events_to_hookpaths_list(events: Optional[List[str]]):
    if not events:
        return None
    return ",".join(f"hooks/{e}" for e in events)


def _do_lobotomy(
    target: Target,
    model: Optional[str],
    dry_run: bool = False,
    undo: bool = False,
    events: Optional[List[str]] = None,
):
    is_machine = get_substrate(model) == "machine"
    sudo = " sudo" if is_machine else ""
    if undo:
        # move dispatch.ori back to dispatch
        move_cmd = f"juju ssh {target.unit_name}{sudo} mv {target.charm_root_path/'dispatch.ori'} {target.charm_root_path/'dispatch'}"
        if dry_run:
            print("would run:")
            print(f"\t{move_cmd}")
            return

    else:
        # move dispatch to dispatch.ori
        move_cmd = f"juju ssh {target.unit_name}{sudo} mv {target.charm_root_path/'dispatch'} {target.charm_root_path/'dispatch.ori'}"

    if dry_run:
        print("would run:")
        print(f"\t{move_cmd}")

    else:
        try:
            check_output(shlex.split(move_cmd))
        except CalledProcessError:
            logger.exception(move_cmd)
            # going on would leave us in an inconsistent state, especially if we're applying
            exit("failed to move dispatch script")

    if not undo:
        with tempfile.NamedTemporaryFile(dir=Path("~").expanduser()) as tf:
            p = Path(tf.name)
            p.write_text(
                (Path(__file__).parent / "dispatch_lobo.sh")
                .read_text()
                .replace("{%DISABLED%}", _events_to_hookpaths_list(events) or "ALL")
            )
            push_file(
                target.unit_name,
                local_path=p,
                remote_path="dispatch",
                model=model,
                dry_run=dry_run,
            )

        cmd = f"juju ssh {target.unit_name}{sudo} chmod +x {target.charm_root_path / 'dispatch'}"
        try:
            subprocess.check_call(shlex.split(cmd))
        except CalledProcessError:
            logger.exception(cmd)
            exit("failed to make dispatch executable! charm is bork.")

    if undo:
        print(f"{target.unit_name}: lobotomy reversed")
    else:
        if events:
            print(f"{target.unit_name}: (selective) lobotomy applied")
        else:
            print(f"{target.unit_name}: lobotomy applied")


def lobotomy(
    target: List[str] = typer.Argument(
        None,
        help="The target to lobotomize. Can be an app (lobotomizes all units),"
        " or a unit (lobotomizes that unit only). "
        "If not provided, will lobotomize the whole model.",
    ),
    events: List[str] = typer.Option(
        None,
        "-e",
        "--events",
        help="If you wish to restrict the lobotomy to specific events.",
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
        target=target,
        _all=_all,
        undo=undo,
        dry_run=dry_run,
        model=model,
        plan=plan,
        events=events,
    )


if __name__ == "__main__":
    _lobotomy(["tempo-k8s"])
