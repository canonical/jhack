import os
import re
import stat
import subprocess
from pathlib import Path
from typing import List, Optional, Union, Sequence

import typer

from jhack.helpers import get_local_charm
from jhack.logger import logger

DIFF_CHANGED_RE = re.compile(r"Files (.+) and (.+) differ")
ONLY_IN_RE = re.compile(r"Only in (.+): (.+)")


def chmod_plusx(file):
    return os.chmod(file, os.stat(file).st_mode | stat.S_IEXEC)


def update(
    charm: Optional[Path] = typer.Argument(
        None,
        help="Charm package to update; will default to any .charm file found in the CWD.",
    ),
    location: List[str] = typer.Option(
        ["./src", "./lib"],
        "--location",
        "-l",
        help="Map source to destination paths.",
    ),
    dry_run: bool = False,
):
    """
    Force-push into a local .charm file one or more directories.

    E.g. ``jhack charm update my_charm.charm -l ./foo`` will grab
    ./foo/* and copy it to [the charm's root]/foo/*.

    >>> update('./my_local_charm-amd64.charm',
    ...        ["./src", "./lib"])

    If ``charm`` is None, it will scan the CWD for the first `*.charm` file
    and use that.
    """
    return _update(charm=charm, location=location, dry_run=dry_run)


def _update(
    charm: Optional[Union[str, Path]],
    location: Sequence[str] = None,
    dry_run: bool = False,
):
    charm = Path(charm) if charm else get_local_charm()
    if not charm.exists() and charm.is_file():
        exit(f"{charm} is not a valid charm file")

    if not location:
        logger.info("loading default locations")
        location = []
        cwd = Path(os.getcwd())
        for default_loc in ("src", "lib"):
            if (path := cwd / default_loc).exists():
                location.append(path)
        location.extend(cwd.glob("*.yaml"))
        logger.info(f"default locations: {location}")

    logger.info(f"updating charm with args:, {charm}, {location}, {dry_run}")
    for loc in location:
        if not Path(loc).exists():
            exit(f"invalid location: {loc!r}, should be a valid path")

        print(f"{'would sync' if dry_run else 'syncing'} {loc} --> {charm}...")

        if dry_run:
            continue

        proc = subprocess.run(["zip", "-ur", charm, loc], capture_output=True, text=True)
        print(proc.stdout)

    print("all done.")


if __name__ == "__main__":
    os.chdir("/home/pietro/hacking/jhack/jhack/tests/charm/update_tests_resource/src_tst")
    _update(charm="./dst_tst.zip", location=("baz:dst_tst/baz",))
