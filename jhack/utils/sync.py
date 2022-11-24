import asyncio
import os
import re
import time
import typing
from itertools import chain, product
from pathlib import Path
from subprocess import PIPE
from typing import List

import typer
from juju import jasyncio

from jhack.helpers import JPopen, juju_status
from jhack.logger import logger

logger = logger.getChild(__file__)


def watch(
    paths,
    on_change: typing.Callable,
    include_files: str = None,
    recursive: bool = True,
    refresh_rate: float = 1.0,
    dry_run: bool = False,
):
    """Watches a directory for changes; on any, calls on_change back with them."""

    resolved = [Path(path).resolve() for path in paths]
    include_files = re.compile(include_files) if include_files else None

    def check_file(file: Path):
        if not include_files:
            return True
        return include_files.match(file.name)

    watch_list = []
    for path in resolved:
        if not path.is_dir():
            logger.error(f"not a directory: {path} cannot watch.")
            continue
        watch_list += walk(path, recursive, check_file)

    if not watch_list:
        logger.error("nothing to watch")
        return

    msg = "watching: \n\t%s" % "\n\t".join(map(str, watch_list))
    if dry_run:
        print(msg)
    logger.info(msg)
    logger.info("Ctrl+C to interrupt")

    hashes = {}
    while True:
        # determine which files have changed
        changed_files = []
        for file in watch_list:
            logger.debug(f"checking {file}")
            if old_tstamp := hashes.get(file, None):
                new_tstamp = os.path.getmtime(file)
                if new_tstamp == old_tstamp:
                    logger.debug(f"timestamp unchanged {old_tstamp}")
                    continue
                logger.debug(f"changed: {file}")
                hashes[file] = new_tstamp
                changed_files.append(file)
            else:
                hashes[file] = os.path.getmtime(file)

        if changed_files:
            on_change(changed_files)

        time.sleep(refresh_rate)


def ignore_hidden_dirs(file: Path):
    return not file.name.startswith(".")


def walk(
    path: Path,
    recursive: bool,
    check_file: typing.Callable[[Path], bool],
    check_dir: typing.Callable[[Path], bool] = ignore_hidden_dirs,
) -> List[Path]:
    """Recursively explore a directory for files matching check_file"""
    walked = []
    for path_ in path.iterdir():
        if path_.is_file() and check_file(path_):
            walked.append(path_)
        elif recursive:
            if path_.is_dir() and (not check_dir or check_dir(path_)):
                walked.extend(walk(path_, recursive, check_file))
            else:
                logger.warning(f"skipped {path_}")
    return walked


def _sync(
    target: str,
    source_dirs: str = "./src;./lib",
    remote_root: str = None,
    container_name: str = "charm",
    machine_charm: bool = False,
    refresh_rate: float = 1,
    recursive: bool = True,
    dry_run: bool = False,
    include_files: str = ".*\.py$",
):
    app, _, unit_tgt = target.rpartition("/")

    if not app:
        app = unit_tgt
        status = juju_status(json=True)
        units = [a.split('/')[1] for a in list(status["applications"][app].get("units", {}))]
    else:
        units = [unit_tgt]

    remote_root = remote_root or "/var/lib/juju/agents/unit-{app}-{unit}/charm/"

    def on_change(changed_files):
        if not changed_files:
            return
        loop = asyncio.events.get_event_loop()
        loop.run_until_complete(
            jasyncio.gather(
                *(
                    push_to_remote_juju_unit(
                        changed,
                        remote_root,
                        app,
                        unit,
                        container_name,
                        machine_charm,
                        dry_run=dry_run,
                    )
                    for unit, changed in product(units, changed_files)
                )
            )
        )
        time.sleep(refresh_rate)

    source_folders = source_dirs.split(";")
    watch(
        source_folders,
        on_change,
        include_files,
        recursive,
        refresh_rate,
        dry_run=dry_run,
    )


def sync(
    target: str = typer.Argument(
        ..., help="The unit or app that you wish to sync to. " "Example: traefik/0."
                  "If syncing to an app, the changes will be pushed to every unit."
    ),
    source_dirs: str = typer.Option(
        "./src;./lib",
        "--source-dirs",
        "-s",
        help="Local directories to watch for changes. "
        "Semicolon-separated list of directories.",
    ),
    remote_root: str = typer.Option(
        None,
        "--remote-root",
        "-r",
        help="The remote path to be interpreted as root relative to which the local "
        "changes will be pushed. E.g. if the local `./src/charm.py` changes, and the "
        "remote-root is `/var/log/`, the file will be "
        "pushed to {unit}:/var/log/src/charm.py`",
    ),
    container_name: str = typer.Option(
        "charm", "--container", "-c", help="Container to scp to."
    ),
    machine_charm: bool = typer.Option(
        False,
        "--machine",
        "-m",
        is_flag=True,
        help="Is this a machine charm? Jhack cannot determine it on its own, "
        "and things behave slightly differently.",
    ),
    refresh_rate: float = typer.Option(
        1, "--refresh-rate", help="Rate at which we will check for changes, in seconds."
    ),
    recursive: bool = typer.Option(
        True,
        "--recursive",
        is_flag=True,
        help="Whether we should watch the directories recursively for changes.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        is_flag=True,
        help="Don't actually *do* anything, just print what you would have done.",
    ),
    include_files: str = typer.Option(
        r".*\.py$",
        "--include-files",
        "-i",
        help="A regex to filter the watchable files with. By defauly, we only sync *.py "
        "files.",
    ),
):
    """Syncs a local folder to a remote juju unit via juju scp.

    Example:
      suppose you're developing a tester-charm and the deployed app name is
      'tester-charm'; you can sync the local src with the remote src by
      running:

      jhack utils sync tester-charm/0 ./tests/integration/tester_charm/src

      The remote root defaults to whatever juju ssh defaults to; that is
      / for workload containers but /var/lib/juju for sidecar containers.
      If you wish to use a different remote root, keep in mind that the path
      you pass will be interpreted to this relative remote root which we have no
      control over.
    """
    return _sync(
        target=target,
        source_dirs=source_dirs,
        remote_root=remote_root,
        container_name=container_name,
        machine_charm=machine_charm,
        refresh_rate=refresh_rate,
        recursive=recursive,
        dry_run=dry_run,
        include_files=include_files,
    )


async def push_to_remote_juju_unit(
    file: Path,
    remote_root: str,
    app,
    unit: str,
    container_name,
    machine_charm: bool,
    dry_run: bool = False,
):
    remote_file_path = (remote_root + str(file)[len(os.getcwd()) + 1 :]).format(unit=unit, app=app)

    if not machine_charm:
        if dry_run:
            print(f"would scp: {file} --> {app}/{unit}:{remote_file_path}")
            return

        container_opt = f"--container {container_name} " if container_name else ""
        cmd = f"juju scp {container_opt}{file} {app}/{unit}:{remote_file_path}"
        proc = JPopen(cmd.split(" "))

    else:
        if dry_run:
            print(f"would scp: {file} --> {app}/{unit}:{remote_file_path}")
            return

        cmd = f"cat {file} | juju ssh {app}/{unit} sudo -i 'sudo tee -a {remote_file_path}'"
        proc = JPopen([cmd], shell=True)

    retcode = proc.returncode
    if retcode != None:
        logger.error(
            f"{cmd} errored with code {retcode}: "
            f"\nstdout={proc.stdout.read()}, "
            f"\nstderr={proc.stderr.read()}"
        )

    print(f"synced {file}")


if __name__ == "__main__":
    _sync(unit="traefik/0", dry_run=True)
