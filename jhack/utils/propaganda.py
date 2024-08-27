"""Tools to mess with leadership."""

import shlex
import signal
from contextlib import contextmanager
from time import sleep
from typing import Literal, Optional

import typer
from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.style import Style
from rich.text import Text

from jhack.conf.conf import CONFIG, check_destructive_commands_allowed
from jhack.helpers import (
    JPopen,
    Target,
    get_leader_unit,
    get_substrate,
    get_units,
    push_string,
    rm_file,
)
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("propaganda")
BLINK = CONFIG.get("propaganda", "blink")

CROWN = r"""
      <>              
    .::::.             
@\\/W\/\/W\//@         
 \\/^\/\/^\//     
  \_O_<>_O_/
"""


def _stop_jujud(
    unit: Target,
    model: Optional[str],
    substrate: Literal["k8s", "machine"],
    dry_run: bool = False,
):
    if substrate == "k8s":
        kill_cmd = "/charm/bin/pebble stop container-agent"
    elif substrate == "machine":
        kill_cmd = f"sudo systemctl stop jujud-machine-{unit.machine_id}.service"
    else:
        raise ValueError(
            f"unknown substrate: {substrate}; don't know how to dethronize units here."
        )
    _model = f" {model}" if model else ""
    cmd = f"juju ssh{_model} {unit.unit_name} {kill_cmd}"
    logger.debug(f"stopping {unit} with {cmd}")

    if dry_run:
        print(f"would run: {cmd}")
        return
    JPopen(shlex.split(cmd))


def _start_jujud(
    unit: Target,
    model: Optional[str],
    substrate: Literal["k8s", "machine"],
    dry_run: bool = False,
):
    if substrate == "k8s":
        start_cmd = "/charm/bin/pebble start container-agent"
    elif substrate == "machine":
        start_cmd = f"sudo systemctl start jujud-machine-{unit.machine_id}.service"
    else:
        raise ValueError(
            f"unknown substrate: {substrate}; don't know how to dethronize units here."
        )
    _model = f" {model}" if model else ""
    cmd = f"juju ssh{_model} {unit.unit_name} {start_cmd}"
    logger.debug(f"starting {unit} with {cmd}")

    if dry_run:
        print(f"would run: {cmd}")
        return
    JPopen(shlex.split(cmd))


def _wait_for_leader(unit, dry_run: bool = False):
    try:
        with Live(
            Spinner(
                "bouncingBall",
                text=f"Waiting for {unit.unit_name} to be 'democratically elected'...",
            ),
            refresh_per_second=20,
        ):
            # is the unit we want to elect leader already?
            def current_leader_name():
                leader = get_leader_unit(unit.app)
                # there is a brief moment of time in which there is no leader at all.
                return leader.unit_name if leader else None

            while not current_leader_name() == unit.unit_name:
                sleep(0.5)

    except KeyboardInterrupt:
        # FIXME: this might leave your units braindead.
        if dry_run:
            print("would abort.")
        else:
            exit("aborted.")


class TimeoutException(Exception):
    pass


@contextmanager
def timeout(seconds, raise_=False):
    def signal_handler(signum, frame):
        raise TimeoutException("Timed out!")

    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    except TimeoutException as e:
        if raise_:
            raise e
        return None
    finally:
        signal.alarm(0)


CHECKS_LAYER = """checks:
    liveness:
        override: replace
        level: alive
        period: 10s
        timeout: 3s
        threshold: {}
        http:
            url: http://localhost:65301/liveness
    readiness:
        override: replace
        level: ready
        period: 10s
        timeout: 3s
        threshold: 3
        http:
            url: http://localhost:65301/readiness
 """
THRESH_HIGH = 100501
THRESH_LOW = 3
LAYER_REMOTE_PATH = "/.jhack-layer-checks-tmp.yaml"


def _set_checks_threshold(
    unit: str, threshold: int, model: Optional[str] = None, dry_run: bool = False
):
    logger.debug(f"setting liveness check threshold to {threshold}")
    push_string(
        unit,
        CHECKS_LAYER.format(threshold),
        remote_path=LAYER_REMOTE_PATH,
        is_full_path=True,
        model=model,
        dry_run=dry_run,
    )

    logger.debug("applying layer...")
    JPopen(
        shlex.split(
            f"juju ssh {unit} /charm/bin/pebble add jhacklayer " f"{LAYER_REMOTE_PATH}"
        )
    )

    logger.debug("cleaning up layer file...")
    rm_file(
        unit,
        remote_path=LAYER_REMOTE_PATH,
        is_path_relative=False,
        model=model,
        dry_run=dry_run,
    )


def _increase_liveness_check_threshold(
    unit: str, model: Optional[str] = None, dry_run: bool = False
):
    _set_checks_threshold(unit, THRESH_HIGH, model=model, dry_run=dry_run)


def _restore_liveness_check_threshold(
    unit: str, model: Optional[str] = None, dry_run: bool = False
):
    _set_checks_threshold(unit, THRESH_LOW, model=model, dry_run=dry_run)


def _leader_set(target: Target, model: Optional[str] = None, dry_run: bool = False):
    substrate = get_substrate(model)
    units = get_units(target.app, model=model)
    if not units:
        exit(f"{target.app} has no units in {'<this model>' if not model else model}.")
    if len(units) == 1:
        exit(f"There is only one unit of {target.app}.")

    if target.unit_name not in {t.unit_name for t in units}:
        exit(
            f"invalid target: {target.unit_name} not found in {'<this model>' if not model else model}."
        )

    leaders = [u for u in units if u.leader]
    if not leaders:
        exit("No leader found.")

    previous_leader_unit = leaders[0]
    if previous_leader_unit.unit_name == target.unit_name:
        exit(f"{target.unit_name} is already the leader.")

    check_destructive_commands_allowed("elect")

    logger.info(f"preparing to elect {target.unit_name}...")

    murderable_units = [u for u in units if u.unit_name != target.unit_name]

    # lobotomize all units except the prospective leader
    for unit in murderable_units:
        if substrate == "k8s":
            _increase_liveness_check_threshold(
                unit=unit.unit_name, model=model, dry_run=dry_run
            )
        _stop_jujud(unit=unit, model=model, substrate=substrate, dry_run=dry_run)

    # block until new leader is elected
    _wait_for_leader(target, dry_run=dry_run)

    # then resurrect all units
    for unit in murderable_units:
        if substrate == "k8s":
            _restore_liveness_check_threshold(
                unit=unit.unit_name, model=model, dry_run=dry_run
            )
        _start_jujud(unit=unit, model=model, substrate=substrate, dry_run=dry_run)

    console = Console()
    console.print(
        Align(
            Text(
                f"Unit {target.unit_name} has been freely™ elected to be the new leader. Long live!",
                style=Style(color="green"),
            ),
            align="center",
        )
    )
    console.print(
        Align(
            Text(
                f"†♔† {previous_leader_unit.unit_name} has abdicated. RIP. †♔†",
                style=Style(color="red"),
            ),
            align="center",
        )
    )
    console.print(
        Align(
            Text(
                CROWN,
                style=Style(dim=True, blink=BLINK, bold=True),
            ),
            align="center",
        )
    )


def leader_set(
    target: str = typer.Argument(
        None, help="Unit you want to elect. " "Example: traefik/0."
    ),
    model: Optional[str] = typer.Option(
        None, "-m", "--model", help="The model. Defaults to current model."
    ),
    dry_run: bool = typer.Option(
        None, "--dry-run", help="Do nothing, print out what would have happened."
    ),
):
    """Force a given unit to become leader by hacking Juju."""
    _leader_set(target=Target.from_name(target), model=model, dry_run=dry_run)


if __name__ == "__main__":
    _leader_set(Target.from_name("ubuntu/1"), dry_run=True)
