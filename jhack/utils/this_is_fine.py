import time
from subprocess import getoutput, CalledProcessError
from typing import List, Optional

import typer

from jhack.helpers import juju_status
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("tif")


def _this_is_fine(
    targets: List[str] = None,
    model: str = None,
    keep_alive: bool = False,
    retry: bool = False,
    dry_run: bool = False,
    rate: float = 2,
):
    print("starting whacker... (interrupt with Ctrl+C)")

    while True:
        start = time.time()
        status = juju_status(model=model, json=True)
        units_in_error = []

        for app_name, app_meta in status["applications"].items():
            included = not targets or app_name in targets

            for unit_name, unit_meta in app_meta["units"].items():
                if targets and unit_name in targets:
                    included = True

                if not included:
                    continue

                wl_status = unit_meta["workload-status"]["current"]
                jj_status = unit_meta["juju-status"]["current"]
                if wl_status == "error" and jj_status == "idle":
                    units_in_error.append(unit_name)

        if units_in_error:
            print(f"apps {units_in_error} in error")
        else:
            logger.debug("no apps in error")
            if not keep_alive:
                return

        for unit in units_in_error:
            _model = f" -m {model}" if model else ""
            cmd = f"juju resolve{' --no-retry' if not retry else ''}{_model} {unit}"
            if dry_run:
                print(f"would tell {unit} to stop whining with {cmd}")
            else:
                if retry:
                    print(f"\t{unit} is giving it another shot")
                else:
                    print(f"\t{unit} is now *fine*")
                try:
                    getoutput(cmd)
                except CalledProcessError:
                    logger.exception(f"{cmd} bugged out")
                    continue

        elapsed = start - time.time()
        time.sleep(max(rate - elapsed, 0))


def this_is_fine(
    targets: Optional[List[str]] = typer.Argument(
        None,
        help="The app, apps or units that are now *fine*. If left blank, will include all apps and units.",
    ),
    model: str = typer.Option(
        None, "-m", "--model", help="Model to which to apply this command."
    ),
    keep_alive: bool = typer.Option(
        False,
        "-k",
        "--keep-alive",
        is_flag=True,
        help="Keep the process alive instead of exiting as soon as all units in error have been told that life is good.",
    ),
    retry: bool = typer.Option(
        False,
        "-r",
        "--retry",
        is_flag=True,
        help="Whether juju should retry the last failed hook or not.",
    ),
    dry_run: bool = typer.Option(
        False,
        help="Don't actually do anything, just print out what would have been done.",
    ),
    rate: float = typer.Option(
        2,
        help="Minimum sleep between successive runs, only applicable in keep-alive mode.",
    ),
):
    """This command tells all your units and applications that things are good."""
    return _this_is_fine(
        targets=targets or [],
        model=model,
        keep_alive=keep_alive,
        retry=retry,
        dry_run=dry_run,
        rate=rate,
    )


if __name__ == "__main__":
    _this_is_fine(keep_alive=True)
