"""Tools to mess with leadership."""

import shlex
import signal
from contextlib import contextmanager
from pathlib import Path
from time import sleep
from typing import Optional

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
    push_file,
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


def _patch_machine(
    apply: bool,
    unit: Target,
    model: Optional[str],
    dry_run: bool = False,
):
    systemctl_cmd = f"sudo systemctl {'start' if apply else 'stop'} jujud-machine-{unit.machine_id}.service"
    _model = f" {model}" if model else ""
    cmd = f"juju ssh{_model} {unit.unit_name} {systemctl_cmd}"
    logger.debug(f"stopping {unit} with {cmd}")

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
        if dry_run:
            print("would abort.")
        else:
            # FIXME: this might leave your units braindead.
            exit("aborted. Warning: your units might be somewhat confused.")


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


JHACK_MOCK_SERVER_LOCAL_PATH = (
    Path(__file__).parent / "mock_health_server" / "server.py"
)
assert JHACK_MOCK_SERVER_LOCAL_PATH.exists(), JHACK_MOCK_SERVER_LOCAL_PATH

JHACK_MOCK_SERVER_REMOTE_PATH = "/jhack_mock_liveness_server.py"
MOCK_SERVER_SERVICE_NAME_PEBBLE = "jhack-mock-server-pebble"
MOCK_SERVER_SERVICE_NAME_K8S = "jhack-mock-server-k8s"
MOCK_SERVER_LAYER = f"""services:                                             
    {MOCK_SERVER_SERVICE_NAME_PEBBLE}:                                  
        summary: Jhack's drop-in juju-agent replacement                 
        startup: disabled                              
        override: replace                             
        command: python3 {JHACK_MOCK_SERVER_REMOTE_PATH}
        environment: 
          SERVER_PROBE: "pebble"
          SERVER_PORT: "65301"
    {MOCK_SERVER_SERVICE_NAME_K8S}:                                  
        summary: Jhack's drop-in juju-agent replacement                 
        startup: disabled                              
        override: replace                             
        command: python3 {JHACK_MOCK_SERVER_REMOTE_PATH}
        environment: 
          SERVER_PROBE: "kubernetes"
          SERVER_PORT: "38813"
"""

CHECKS_LAYER = """checks:
    liveness:
        override: replace
        level: alive
        period: 10s
        timeout: 3s
        threshold: {threshold}
        http:
            url: http://localhost:65301/liveness
    readiness:
        override: replace
        level: ready
        period: 10s
        timeout: 3s
        threshold: {threshold}
        http:
            url: http://localhost:65301/readiness
 """
THRESH_HIGH = 100501
THRESH_LOW = 3
LAYER_REMOTE_PATH = "/.jhack-layer-checks-tmp.yaml"


def _patch_k8s(
    apply: bool,
    unit: str,
    model: Optional[str] = None,
    dry_run: bool = False,
    cleanup: bool = False,
):
    logger.info(("applying" if apply else "lifting") + f" pebble patch on {unit}")
    threshold = THRESH_HIGH if apply else THRESH_LOW
    logger.debug(f"setting pebble liveness check threshold to {threshold}")

    if apply:
        layer = MOCK_SERVER_LAYER + CHECKS_LAYER
    else:
        layer = CHECKS_LAYER

    push_string(
        unit,
        layer.format(threshold=threshold),
        remote_path=LAYER_REMOTE_PATH,
        is_full_path=True,
        model=model,
        dry_run=dry_run,
    )

    if apply:
        logger.debug("pushing mock server source...")
        push_file(
            unit,
            JHACK_MOCK_SERVER_LOCAL_PATH,
            JHACK_MOCK_SERVER_REMOTE_PATH,
            is_full_path=True,
            model=model,
            dry_run=dry_run,
        )

    logger.debug(
        f"adding layer and {'starting' if apply else 'killing'} mock server..."
    )

    add_layer = f"/charm/bin/pebble add {'jhackdo' if threshold==THRESH_HIGH else 'jhackundo'} --combine {LAYER_REMOTE_PATH}"
    # if applying patch: stop container-agent, start server
    # if lifting patch: other way 'round
    containeragent_cmd = (
        f"/charm/bin/pebble {'stop' if apply else 'start'} container-agent"
    )
    server_cmd_pebble = f"/charm/bin/pebble {'start' if apply else 'stop'} {MOCK_SERVER_SERVICE_NAME_PEBBLE}"
    server_cmd_k8s = f"/charm/bin/pebble {'start' if apply else 'stop'} {MOCK_SERVER_SERVICE_NAME_K8S}"
    cmd = [
        "juju",
        "ssh",
        unit,
        "bash",
        "-c",
        f'"{add_layer} && {containeragent_cmd} && {server_cmd_pebble} && {server_cmd_k8s}"',
    ]
    JPopen(cmd, wait=True)

    if cleanup:
        logger.debug("cleaning up layer file...")
        rm_file(
            unit,
            remote_path=LAYER_REMOTE_PATH,
            is_path_relative=False,
            model=model,
            dry_run=dry_run,
        )
        # if lifting the patch, we can also remove the server
        if not apply:
            logger.debug("cleaning up server file...")
            rm_file(
                unit,
                remote_path=JHACK_MOCK_SERVER_REMOTE_PATH,
                is_path_relative=False,
                model=model,
                dry_run=dry_run,
            )


def _leader_set(
    target: Target, model: Optional[str] = None, cleanup=True, dry_run: bool = False
):
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
            _patch_k8s(True, unit=unit.unit_name, model=model, dry_run=dry_run)
        else:
            _patch_machine(True, unit=unit, model=model, dry_run=dry_run)

    # block until new leader is elected
    _wait_for_leader(target, dry_run=dry_run)

    # then resurrect all units
    for unit in murderable_units:
        if substrate == "k8s":
            _patch_k8s(
                False,
                unit=unit.unit_name,
                model=model,
                dry_run=dry_run,
                cleanup=cleanup,
            )
        else:
            _patch_machine(False, unit=unit, model=model, dry_run=dry_run)

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
    skip_cleanup: bool = typer.Option(
        False,
        is_flag=True,
        help="Skip cleaning up all temporary files on the units for debugging purposes.",
    ),
):
    """Force a given unit to become leader by hacking Juju.

    Note that this will trigger a restart on every unit except the newly-elected one.
    TODO: patch the k8s liveness probes to prevent this from happening
      cfr https://github.com/kubernetes/kubernetes/pull/126844
    """
    _leader_set(
        target=Target.from_name(target),
        model=model,
        dry_run=dry_run,
        cleanup=not skip_cleanup,
    )


if __name__ == "__main__":
    _leader_set(Target.from_name("ubuntu/1"), dry_run=True)
