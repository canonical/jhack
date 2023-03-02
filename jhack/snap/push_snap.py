import os
import re
import sys
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from subprocess import CalledProcessError, run
from typing import Literal, List

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


def _push_to_unit(unit_name: str, snap_name: str, dry_run: bool = False):
    logger.info(f"shelling snap over to {unit_name}...")
    cmd = f"juju scp ./{snap_name} {unit_name}:~/"
    logger.debug(f"running: {cmd}")

    if dry_run:
        print(f"would shell over {snap_name} with {cmd!r}")
        return

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


def _clean(unit_name, snap_name, mode, dry_run: bool = False):
    _mode = " --purge" if mode == "force" else ""
    logger.info(f"cleaning up{_mode} {snap_name} in {unit_name}")
    cmd = f"juju ssh {unit_name} -- sudo snap remove {snap_name}{_mode}"

    if dry_run:
        print(f"would clean {unit_name} with {cmd!r}")
        return

    # check=False as we don't care if this fails because e.g. the snap was not installed.
    out = JPopen(cmd.split(), wait=True).stdout.read().decode("utf-8")
    logger.debug(out)
    logger.info(f"\tcleaned.")


def _install_in_unit(
        unit_name: str, snap_name: str, clean: Literal[False, True, "force"],
        dry_run: bool = False,
):
    if clean:
        _clean(unit_name, snap_name, mode=clean)

    logger.info(f"installing snap in {unit_name}...")
    cmd = f"juju ssh {unit_name} -- sudo snap install --dangerous ~/{snap_name}"
    logger.debug(f"command = {cmd}")

    if dry_run:
        print(f"would install {snap_name} in {unit_name} with {cmd!r}")
        return

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


bind_re = re.compile(r"([\w-]+)/([\w-]+):([\w-]+)")


def _connect_in_unit(unitname: str, snapname: str, plugs: List[str], slots: List[str],
                     dry_run: bool = False):
    def connect_bind(spec: str, is_slot: bool):
        m = bind_re.match(spec)
        if not m:
            logger.error(f'spec {spec} is not a valid bind specification: expected format is: '
                         f'<local-endpoint>/<remote-snap-name>:<remote-endpoint>')
            return

        local_endpoint, remote_snap, remote_endpoint = m.groups()
        local_mount = f"{snapname}:{local_endpoint}"
        remote_mount = f"{remote_snap}:{remote_endpoint}"

        # snap connect syntax is:
        #   PLUG SLOT
        if is_slot:
            # local side is the slot aka RIGHT side:
            a, b = remote_mount, local_mount

        else:
            a, b = local_mount, remote_mount

        cmd = f"juju ssh {unitname} -- sudo snap connect {a} {b}"

        logger.debug(f"running: {cmd}")
        if dry_run:
            print(f'would have connected {a} --> {b} by running: {cmd!r}')
            return

        try:
            proc = JPopen(cmd.split(), wait=True)
        except (FileNotFoundError, CalledProcessError) as e:
            logger.error(exc_info=True)
            raise SnapCtlError(f"cmd {cmd} failed.") from e

        proc.wait()
        out = proc.stdout.read().decode("utf-8")

        if proc.returncode != 0:
            err = proc.stderr.read().decode("utf-8")
            logger.error(f'stderr = {err}')
            fail_msg = f"Failed snap-connecting {a} to {b}"
            logger.error(fail_msg, exc_info=True)
        else:
            logger.debug(out)
            logger.info("\tshelled.")

    logger.info('binding slots and plugs...')
    for spec in (slots or ()):
        connect_bind(spec, is_slot=True)

    for spec in (plugs or ()):
        connect_bind(spec, is_slot=False)
    logger.info('\tAll bound.')


def _rebuild(dry_run: bool):
    """Run snapcraft in current dir."""
    logger.info("snapping...")
    cmd = "snapcraft --use-lxd"

    if dry_run:
        print(f'would call {cmd!r}')
        return

    try:
        run(cmd.split(), capture_output=True, check=True)
    except CalledProcessError:
        logger.error('failed packing snap.', exc_info=True)
        exit("failed packing snap.")


def _push_snap(
        target: str,
        snap: Path = Path("./"),
        rebuild: bool = False,
        model: str = None,
        clean: CleanOpt = CleanOpt.yes,
        bind_slots: List[str] = None,
        bind_plugs: List[str] = None,
        dry_run: bool = False,
):
    if get_substrate(model) == "k8s":
        exit(f"{model or 'this model'} is not a machine model.")

    logger.info(f"snap root={snap}")
    with cwd(snap):
        if rebuild:
            _rebuild(dry_run=dry_run)

        try:
            snap_name = next(Path("./").glob("*.snap"))
        except StopIteration:
            if dry_run:
                snap_name = "my-application.dry-run.snap"
                print(f"no snap found in current folder; assuming at this point "
                      f"you will have something like {snap_name} in {snap.absolute()}")

            else:
                exit("no snap found in ./.")

        logger.info(f"Found snap {snap_name}.")

        def _push_and_install(unitname, snapname):
            try:
                _push_to_unit(unitname, snapname, dry_run=dry_run)
                _install_in_unit(unitname, snapname, clean=clean, dry_run=dry_run)
                _connect_in_unit(unitname, snapname, plugs=bind_plugs, slots=bind_slots, dry_run=dry_run)
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
        bind_slots: List[str] = typer.Option(
            None, "--bind-slots", "-b",
            help="List of `<this-snap-plug>/<other-snap-name>:<slot>` definitions. "
                 "Will be connected after the snap is installed."
        ),
        bind_plugs: List[str] = typer.Option(
            None, "--bind-plugs", "-p",
            help="List of `<this-snap-slot>/<other-snap-name>:<plug>` definitions. "
                 "Will be connected after the snap is installed."
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
        clean: CleanOpt = typer.Option(
            CleanOpt.yes, "--clean", "-c",
            help="Uninstall the existing snap installation before installing the newly pushed snap."),
        dry_run: bool = typer.Option(False, "--dry-run",
                                     help="Do nothing, show what would have happened."),
):
    """Install a local snap into a live machine charm."""
    return _push_snap(
        target=target,
        snap=snap,
        rebuild=rebuild,
        model=model,
        clean=clean,
        bind_slots=bind_slots,
        bind_plugs=bind_plugs,
        dry_run=dry_run
    )


if __name__ == '__main__':
    _push_snap("zoo/0", snap=Path('/home/pietro/canonical/zookeeper-snap/'), rebuild=False)
