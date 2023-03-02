import os
import sys
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from subprocess import CalledProcessError, run
from typing import Literal

import typer

from jhack.helpers import get_all_units, get_substrate, JPopen
from jhack.logger import logger

logger = logger.getChild(__file__)


@contextmanager
def cwd(dir: Path):
    previous_cwd = os.getcwd()
    os.chdir(str(dir))
    yield
    os.chdir(previous_cwd)


class SnapCtlError(RuntimeError):
    pass


def _push_to_unit(unit_name: str, snap_name: str):
    logger.info(f"shelling snap over to {unit_name}...")
    cmd = f"juju scp ./{snap_name} {unit_name}:~/"
    logger.debug("running: cmd")

    def fail():
        fail_msg = f"Failed scp'ing {snap_name} to {unit_name}"
        logger.error(fail_msg, exc_info=True)
        return SnapCtlError(fail_msg)

    try:
        proc = JPopen(cmd.split(), wait=True)

    except (FileNotFoundError, CalledProcessError) as e:
        raise fail() from e

    proc.wait()
    out = proc.stdout.read().decode("utf-8")

    if proc.returncode != 0:
        err = proc.stderr.read().decode("utf-8")
        logger.error(f'stderr = {err}')
        raise fail()

    logger.debug(out)
    logger.info("\tshelled.")


def _clean(unit_name, snap_name, mode):
    _mode = " --purge" if mode == "force" else ""
    logger.info(f"cleaning up{_mode} {snap_name} in {unit_name}")
    cmd = f"juju ssh {unit_name} -- sudo snap remove {snap_name}{_mode}"
    # check=False as we don't care if this fails because e.g. the snap was not installed.
    out = JPopen(cmd.split(), wait=True).stdout.read().decode("utf-8")
    logger.debug(out)
    logger.info(f"\tcleaned.")


def _install_in_unit(
        unit_name: str, snap_name: str, clean: Literal[False, True, "force"]
):
    if clean:
        _clean(unit_name, snap_name, mode=clean)

    logger.info(f"installing snap in {unit_name}...")
    cmd = f"juju ssh {unit_name} -- sudo snap install --dangerous '~/{snap_name}'"
    logger.debug(f"command = {cmd}")

    try:
        out = JPopen(
            cmd.split(), wait=True
        ).stdout.read().decode("utf-8")
    except CalledProcessError as e:
        msg = f"Failed installing {snap_name} in {unit_name}"
        logger.error(msg, exc_info=True)
        raise SnapCtlError(msg) from e

    logger.debug(out)
    logger.info("\tinstalled.")


class CleanOpt(str, Enum):
    no = False
    yes = True
    force = "force"


def _push_snap(
        target: str,
        snap: Path = Path("./"),
        rebuild: bool = False,
        model: str = None,
        clean: CleanOpt = CleanOpt.yes,
):
    if get_substrate(model) == "k8s":
        exit(f"{model or 'this model'} is not a machine model.")

    logger.info(f"snap root={snap}")
    with cwd(snap):
        if rebuild:
            logger.info("snapping...")
            try:
                run(["snapcraft", "--use-lxd"], capture_output=True, check=True)
            except CalledProcessError:
                logger.error('failed packing snap.', exc_info=True)
                exit("failed packing snap.")

        try:
            snap_name = next(Path("./").glob("*.snap"))
        except StopIteration:
            exit("no snap found in ./.")

        logger.info(f"Found snap {snap_name}.")

        def _push_and_install(unitname, snapname):
            try:
                _push_to_unit(unitname, snapname)
                _install_in_unit(unitname, snapname, clean=clean)
            except SnapCtlError as e:
                sys.exit(e.args[0])

        if "/" in target:
            logger.info(f'target is a unit. Pushing to {target}.')

            unit_name = target
            _push_and_install(unit_name, snap_name)
        else:
            # todo parallelize
            units = get_all_units(model, filter_apps=(target,))
            if not units:
                exit(f'application {target} has no units. Is the app allocating?')

            logger.info(f'target is an app. Pushing to {units}.')

            for target_unit in units:
                _push_and_install(target_unit.unit_name, snap_name)


def push_snap(
        target: str = typer.Argument(
            None,
            help="Unit to which the snap should be pushed. If a unit ID is omitted (i.e. if you pass an "
                 "application name), this command will push the snap to all units.",
        ),
        snap: Path = typer.Option(
            Path(os.getcwd()).absolute(), "--snap", "-s",
            help="Root path of the snap package."
        ),
        rebuild: bool = typer.Option(
            False,
            "--rebuild",
            "-r",
            help="Whether to rebuild the snap and push the resulting build, or use an existing .snap file.",
        ),
        model: str = typer.Option(
            None,
            "--model",
            "-m",
            help="Model in which to find the target. Defaults to the current model.",
        ),
        clean: CleanOpt = typer.Option(CleanOpt.yes, "--clean", "-c", help=""),
):
    """Install a local snap into a live machine charm."""
    return _push_snap(
        target=target,
        snap=snap,
        rebuild=rebuild,
        model=model,
        clean=clean,
    )


if __name__ == '__main__':
    _push_snap("zookeeper", snap=Path('/home/pietro/canonical/zookeeper-snap/'), rebuild=False)
