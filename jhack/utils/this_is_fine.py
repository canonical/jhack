import shlex
import subprocess
import time
from contextlib import contextmanager
from typing import List, Optional

import typer

from jhack.conf.conf import check_destructive_commands_allowed
from jhack.helpers import juju_status, Target
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("this-is-fine")


def _unit_in_error(status: dict, target: str) -> bool:
    app_name = target.split("/")[0]
    unit_meta = (
        status.get("applications", {}).get(app_name, {"units": {}})["units"].get(target)
    )
    return unit_meta["workload-status"]["current"] == "error"


def _matches(targets: List[str], tgt):
    for target in targets:
        if "/" in target:
            return tgt.unit_name == target
        else:
            return tgt.app == target.split("/")[0]


def _resolve_targets(targets: List[str], model: Optional[str]) -> List[Target]:
    out = []
    status = juju_status(model=model, json=True)
    for app in status.get("applications", {}).values():
        for unit_name, unit_meta in app.get("units", {}).items():
            tgt = Target.from_name(unit_name)
            if not targets:
                out.append(tgt)
            elif _matches(targets, tgt):
                out.append(tgt)
    return out


def _bamboozle(
    units: List[Target], model: Optional[str], dry_run: bool, no_retry: bool = False
):
    _model = f" -m {model}" if model else ""
    _no_retry = " --no-retry" if no_retry else ""

    for unit in units:
        cmd = f"juju resolve{_model} {unit.unit_name}{_no_retry}"

        if dry_run:
            status = juju_status(model=model, json=True)
            if _unit_in_error(status, unit.unit_name):
                print(f"would bamboozle {unit.unit_name=} with {cmd=}")
            continue

        proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
        stderr = proc.stderr
        if "is not in an error state" in stderr:
            logger.debug("unit: not in error")
        elif stderr := proc.stderr:
            logger.error(f"[{cmd}] {stderr=}")
        else:
            msg = f"{unit.unit_name=} bamboozled."
            if no_retry:
                msg += " Extremely so."
            print(msg)


@contextmanager
def _ratelimiter(rate: int):
    start = time.time()

    yield

    end = time.time()
    diff = rate - (end - start)
    if diff > 0:
        time.sleep(diff)


def _this_is_fine(
    target: List[str] = None,
    watch: int = 3,
    model: Optional[str] = None,
    dry_run: bool = False,
    no_retry: bool = False,
):
    units = _resolve_targets(target, model)

    cmd = ";".join(f"juju resolve {u.unit_name} --model {model}" for u in units)
    check_destructive_commands_allowed("this_is_fine", dry_run_cmd=cmd)

    print("watching:")
    for unit in units:
        print(f"\t{unit.unit_name}")
    if not watch:
        print("(ctrl+c to interrupt)")

    try:
        while True:
            with _ratelimiter(watch):
                _bamboozle(units, model=model, dry_run=dry_run, no_retry=no_retry)

            if not watch:
                break

    except KeyboardInterrupt:
        print("aborted")


def this_is_fine(
    target: List[str] = typer.Argument(
        None,
        help="Unit or application names you want to include in the bamboozlement. "
        "Defaults to all.",
    ),
    watch: int = typer.Option(
        3, "-w", "--watch", help="Keep a-watching and a-bamboozlin'. 0 means no watch."
    ),
    model: Optional[str] = typer.Option(
        None, "-m", "--model", help="The model. Defaults to current model."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Do nothing, print out what would have happened."
    ),
    no_retry: bool = typer.Option(
        False,
        "--no-retry",
        help="Extreme bamboozlement: tells juju not to retry the failed hook.",
    ),
):
    """Bamboozles the juju controller and auto-resolves all units in error.

    Everything is fine.
    """

    _this_is_fine(
        target=target, watch=watch, model=model, dry_run=dry_run, no_retry=no_retry
    )


if __name__ == "__main__":
    _this_is_fine()
