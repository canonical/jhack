import shlex
import subprocess
import tempfile
from pathlib import Path
from subprocess import CalledProcessError, check_output
from typing import List, Optional, Tuple, Union

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from jhack.conf.conf import check_destructive_commands_allowed
from jhack.helpers import Target, get_all_units, get_substrate, parse_target, push_file
from jhack.logger import logger

logger = logger.getChild(__file__)


def _parse_exit_code(out):
    return (out[len("EXIT_CODE=") :]).strip() == "0"


def _parse_disabled(out):
    return (out[len("DISABLED=") :]).strip()


def _get_lobo_details(target: Target) -> Tuple[Union[bool, List[str]], str]:
    """Return lobotomy details.

    - False if lobotomy is not active, else a list of events (for selective lobotomy).
    - Return code: "0" or "1"
    """
    # if dispatch.ori is present; dispatch is lobo dispatch (or cleanup failed; either way)
    cmd = f"juju ssh {target.unit_name} cat {target.charm_root_path/'dispatch'} | grep -A1 DISABLED= "
    try:
        out = check_output(shlex.split(cmd), stderr=subprocess.PIPE, text=True).strip()
        disabled, exitcode = out.split("\n") if out else (None, None)
        return _parse_disabled(disabled), _parse_exit_code(exitcode)
    except CalledProcessError:
        return False, False


def _print_plan(targets: List[Target]):
    table = {target: _get_lobo_details(target) for target in targets}
    t = Table("unit", "lobotomy", "retry", "events", title="lobotomy plan")
    for target, (lobotomized, retry) in table.items():

        t.add_row(
            target.unit_name,
            Text(
                "active" if lobotomized else "inactive",
                style="bold red" if lobotomized else "green",
            ),
            Text(
                "yes" if retry else "no",
                style="bold cyan" if retry else "yellow",
            ),
            (
                Text("n/a", style="light grey")
                if lobotomized is False
                else (lobotomized or Text("all", style="bold red"))
            ),
        )

    Console().print(t)


def _lobotomy(
    target: List[str],
    _all: bool = False,
    events: List[str] = None,
    dry_run: bool = False,
    model: Optional[str] = None,
    undo: bool = False,
    plan: bool = False,
    retry: bool = False,
):
    if plan:
        _all = True
    elif undo and not target:
        # in the case of undo, no targets = all targets
        _all = True

    targets: List[Target] = []
    if _all:
        if target:
            logger.warning(f"`all` flag overrules provided targets {target}.")
        targets.extend(get_all_units(model))
    elif target:
        for tgt in target:
            targets.extend(parse_target(tgt, model))

    if not targets:
        exit("no targets provided. Aborting...")

    if plan:
        _print_plan(targets or get_all_units(model))
        return

    if undo:
        targets = [t for t in targets if _get_lobo_details(t)[0]]
    else:
        targets = [t for t in targets if not _get_lobo_details(t)[0]]

    if not targets:
        exit("no changes to apply.")

    logger.debug(f"gathered targets {targets}")

    for t in targets:
        logger.info(f"lobotomizing {t}...")
        _do_lobotomy(t, model, dry_run, undo, events, retry)


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
    retry: bool = False,
):
    is_machine = get_substrate(model) == "machine"
    sudo = " sudo" if is_machine else ""
    if undo:
        # move dispatch.ori back to dispatch
        move_cmd = (
            f"juju ssh {target.unit_name}{sudo} mv "
            f"{target.charm_root_path/'dispatch.ori'} "
            f"{target.charm_root_path/'dispatch'}"
        )
        if dry_run:
            print("would run:")
            print(f"\t{move_cmd}")
            return
    else:
        # move dispatch to dispatch.ori
        move_cmd = (
            f"juju ssh {target.unit_name}{sudo} mv "
            f"{target.charm_root_path/'dispatch'} "
            f"{target.charm_root_path/'dispatch.ori'}"
        )

    if dry_run:
        print("would run:")
        print(f"\t{move_cmd}")

    else:
        check_destructive_commands_allowed(
            "lobotomy", move_cmd + " ... and some more nasty commands"
        )

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
                .replace("{%EXIT_CODE%}", "1" if retry else "0")
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
    retry: bool = typer.Option(
        False,
        "--retry",
        is_flag=True,
        help="Tell juju to keep retrying calling the intercepted hook."
        "Note that this will prevent the model from progressing further, as juju will "
        "effectively be stuck at the first failing hook for the lobotomized units.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        is_flag=True,
        help="Don't actually do anything, just print what would have happened.",
    ),
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
        retry=retry,
    )


if __name__ == "__main__":
    _lobotomy(["tempo-k8s"])
