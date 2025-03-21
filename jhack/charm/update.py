import dataclasses
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from enum import Enum
from pathlib import Path
from typing import List, Optional, Union, Sequence
from zipfile import ZipFile

import typer

from jhack.helpers import get_local_charm
from jhack.logger import logger

DIFF_CHANGED_RE = re.compile(r"Files (.+) and (.+) differ")
ONLY_IN_RE = re.compile(r"Only in (.+): (.+)")


def chmod_plusx(file):
    return os.chmod(file, os.stat(file).st_mode | stat.S_IEXEC)


class _ChangeType(Enum):
    delete = "delete"
    copy = "copy"
    change = "change"


@dataclasses.dataclass(unsafe_hash=True)
class _Change:
    dst: Path
    typ: _ChangeType
    src: Optional[Path] = None

    def apply(
        self,
        src_path: Path,
        dst_filepath: Path,
        destination,
        dry_run: bool,
    ):
        if self.typ in (_ChangeType.copy, _ChangeType.change):
            subpath = str(self.src)[len(str(src_path)) + 1 :]
            print(
                f"{'would copy' if dry_run else 'copying'} {src_path} --> <zipped charm root>/{destination}/{subpath}"
            )
            if dry_run:
                return

            # todo: handle subpath
            dst_path.write(src_path)

        elif self.typ == _ChangeType.delete:
            # zipfile has no builtin for this...
            print(
                f"{'would delete' if dry_run else 'deleting'} <zipped charm root>/{destination}"
            )
            if dry_run:
                return

            subprocess.run(["zip", "-d", dst_filepath, destination])
        else:
            raise ValueError(f"unknown change type: {self.typ}")


def dir_diff(src: Path, dst: Path) -> List[_Change]:
    """Walk two directories and return a list of differences."""
    diffs = []

    cmd = subprocess.run(["diff", "-rq", src, dst], text=True, capture_output=True)

    for line in cmd.stdout.splitlines():

        if match := ONLY_IN_RE.match(line):
            only_in_dir, only_in_file = map(Path, match.groups())
            if str(src) in str(only_in_dir):
                change_type = _ChangeType.copy
                src_path = Path(only_in_dir) / only_in_file
            else:
                change_type = _ChangeType.delete
                src_path = None

            subdir = str(only_in_dir)[len(str(dst)) + 1 :]
            dst_path = dst / subdir / only_in_file
            diffs.append(_Change(src=src_path, dst=dst_path, typ=change_type))

        elif match := DIFF_CHANGED_RE.match(line):
            file_changed_src, file_changed_dst = match.groups()
            diffs.append(
                _Change(
                    src=Path(file_changed_src),
                    dst=Path(file_changed_dst),
                    typ=_ChangeType.change,
                )
            )

    return diffs


def update(
    charm: Optional[Path] = typer.Argument(
        None,
        help="Charm package to update; will default to any .charm file found in the CWD.",
    ),
    location: List[str] = typer.Option(
        ["./src", "./lib"],
        "location",
        "l",
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
    location: Sequence[str] = ("./src", "./lib"),
    dry_run: bool = False,
):
    charm = Path(charm) if charm else get_local_charm()
    if not charm.exists() and charm.is_file():
        exit(f"{charm} is not a valid charm file")

    logger.info(f"updating charm with args:, {charm}, {location}, {dry_run}")

    for loc in location:
        if not Path(loc).exists():
            exit(
                f"invalid location: {loc!r}, should be a valid path"
            )

        print(f"syncing {loc}-->{charm}...")


    print("all done.")


if __name__ == "__main__":
    os.chdir(
        "/home/pietro/hacking/jhack/jhack/tests/charm/update_tests_resource/src_tst"
    )
    _update(charm="./dst_tst.zip", location=("baz:dst_tst/baz",))
