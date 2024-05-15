import asyncio
import os
import re
import time
import typing
from itertools import product
from pathlib import Path
from typing import List, Optional

import typer
import yaml

from jhack.helpers import juju_status, push_file
from jhack.logger import logger

logger = logger.getChild(__file__)


def watch(
    paths,
    on_change: typing.Callable,
    include_files: str = None,
    recursive: bool = True,
    refresh_rate: float = 1.0,
    skip_initial_sync: bool = False,
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
            logger.warning(f"not a directory: cannot watch {path}. Skipping...")
            continue
        watch_list += walk(path, recursive, check_file)

    if not watch_list:
        logger.error("nothing to watch. Pass something to --source-dirs")
        return

    if not skip_initial_sync:
        print("initiating initial sync...")
        on_change(watch_list)
        print("remote up to speed with local. Starting watcher...")

    print("watching: \n\t%s" % "\n\t".join(map(str, watch_list)))
    print(
        "Kill the process (Ctrl+C) to interrupt. "
        "Any local changes will be pushed to the remote(s)."
    )

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
                logger.debug(f"skipped {path_}: not a dir or invalid pattern")
    return walked


# TODO: add --watch flag to switch between the one-shot force-feed functionality and the legacy 'sync' mode
#  - plus change warning


def _sync(
    targets: List[str] = None,
    source_dirs: str = "./src;./lib",
    touch: List[Path] = None,
    remote_root: str = None,
    container_name: str = "charm",
    refresh_rate: float = 1,
    recursive: bool = True,
    dry_run: bool = False,
    skip_initial_sync: bool = False,
    include_files: str = ".*\.py$",
):
    status = juju_status(json=True)

    if not targets:
        local_charm_meta = Path.cwd() / "charmcraft.yaml"
        if not local_charm_meta.exists():
            exit(
                "you need to cd to a charm repo root for `jhack sync` to work without targets argument. "
                "Alternatively, pass a juju unit/application name as first argument."
            )

        name = yaml.safe_load(local_charm_meta.read_text()).get("name")
        if not name:
            name = yaml.safe_load((Path.cwd() / "metadata.yaml").read_text()).get(
                "name"
            )
            if not name:
                exit(
                    "could not find name in charmcraft.yaml / metadata.yaml. "
                    "Specify a target manually."
                )

        targets = [
            app
            for app, appmeta in status["applications"].items()
            if appmeta["charm-name"] == name
        ]

    if "*" in targets:
        targets = list(status["applications"])

    units = set()
    for target in targets:
        _app_name, _, unit_tgt = target.rpartition("/")

        if not _app_name:
            _app_name = unit_tgt
            if _app_name == "*":
                units.update(
                    unit_name
                    for app in status["applications"].values()
                    for unit_name in app.get("units", {})
                )
            else:
                units.update(
                    unit_name
                    for unit_name in status["applications"][_app_name].get("units", {})
                )
        else:
            units.add(target)

    if not units:
        exit("No targets found.")

    remote_root = remote_root or "/var/lib/juju/agents/unit-{app}-{unit_id}/charm/"

    if touch:
        coros = []
        for file in touch:
            for unit in units:
                coros.append(
                    push_to_remote_juju_unit(
                        file,
                        remote_root,
                        unit,
                        container_name,
                        dry_run=dry_run,
                    )
                )

        loop = asyncio.events.get_event_loop()
        loop.run_until_complete(asyncio.gather(*coros))
        print("done.")
        return

    def on_change(changed_files):
        if not changed_files:
            return
        loop = asyncio.events.get_event_loop()
        loop.run_until_complete(
            asyncio.gather(
                *(
                    push_to_remote_juju_unit(
                        changed,
                        remote_root,
                        unit,
                        container_name,
                        dry_run=dry_run,
                    )
                    for unit, changed in product(units, changed_files)
                )
            )
        )
        time.sleep(refresh_rate)

    print("Ready to sync to: \n\t%s" % "\n\t".join(units))

    source_folders = source_dirs.split(";")
    watch(
        source_folders,
        on_change,
        include_files,
        recursive,
        refresh_rate,
        skip_initial_sync=skip_initial_sync,
    )


def sync(
    target: Optional[List[str]] = typer.Argument(
        None,
        help="The units or apps that you wish to sync to. "
        "Example: traefik/0."
        "If syncing to an app, the changes will be pushed to every unit."
        "If you omit the target altogether, it will try to determine what app to sync to "
        "based on the CWD. If you pass ``*``, it will sync to ALL apps.",
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
    refresh_rate: float = typer.Option(
        1, "--refresh-rate", help="Rate at which we will check for changes, in seconds."
    ),
    recursive: bool = typer.Option(
        True,
        "/--non-recursive",
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
    skip_initial_sync: bool = typer.Option(
        False,
        "--skip-initial-sync",
        "-S",
        help="Skip the initial sync. "
        "This means only the files you touch AFTER the process is started will be synced.",
    ),
    touch: List[Path] = typer.Option(
        None,
        "--touch",
        help="Only push these files and exit. "
        "Overrules --skip-initial-sync and --source-dirs",
    ),
):
    """Syncs a local folder to a remote juju unit via juju scp.

    Example:
      suppose you're developing a tester-charm and the deployed app name is
      'tester-charm'; you can sync the local src with the remote src by
      running:

      jhack sync tester-charm/0 ./tests/integration/tester_charm/src

      The remote root defaults to whatever juju ssh defaults to; that is
      / for workload containers but /var/lib/juju for sidecar containers.
      If you wish to use a different remote root, keep in mind that the path
      you pass will be interpreted to this relative remote root which we have no
      control over.
    """
    return _sync(
        targets=target,
        source_dirs=source_dirs,
        touch=touch,
        remote_root=remote_root,
        container_name=container_name,
        refresh_rate=refresh_rate,
        recursive=recursive,
        dry_run=dry_run,
        include_files=include_files,
        skip_initial_sync=skip_initial_sync,
    )


async def push_to_remote_juju_unit(
    file: Path,
    remote_root: str,
    unit: str,
    container_name,
    dry_run: bool = False,
):
    app, _, unit_id = unit.rpartition("/")
    remote_file_path = (
        remote_root + str(file.absolute())[len(os.getcwd()) + 1 :]
    ).format(unit_id=unit_id, app=app)

    push_file(
        unit,
        file,
        remote_file_path,
        is_full_path=True,
        container=container_name,
        dry_run=dry_run,
        mkdir_remote=True,
    )
    if dry_run:
        return

    print(f"synced {file} -> {unit}")


if __name__ == "__main__":
    os.chdir("/home/pietro/canonical/tempo-k8s")
    _sync(dry_run=True)
