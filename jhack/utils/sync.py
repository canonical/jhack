import asyncio
import configparser
import datetime
import os
import re
import shlex
import time
import typing
from itertools import product
from pathlib import Path
from typing import List, Optional

import toml
import typer
import yaml

from jhack.conf.conf import check_destructive_commands_allowed
from jhack.helpers import JSubprocess, _get_units, get_substrate, juju_status, push_file
from jhack.logger import logger

logger = logger.getChild(__file__)


def watch(
    paths: List[str],
    venv: Optional[Path],
    on_change: typing.Callable[[typing.Iterable[typing.Union[str, Path]], bool], None],
    include_files: str = None,
    recursive: bool = True,
    refresh_rate: float = 1.0,
    initial_sync: bool = False,
):
    """Watches a directory for changes; on any, calls on_change back with them."""
    include_files = re.compile(include_files) if include_files else None

    def check_file(file: Path):
        if not include_files:
            return True
        return include_files.match(file.name)

    def _walk(*path: typing.Union[str, Path]):
        resolved = [Path(p).resolve() for p in path]
        for p in resolved:
            if not p.is_dir():
                logger.warning(f"not a directory: cannot watch {p}. Skipping...")
                continue
            yield from walk(p, recursive, check_file)

    watch_list = list(_walk(*paths))
    venv_list = list(_walk(venv)) if venv else []

    if not (watch_list or venv_list):
        logger.error("nothing to watch. Configure --source-dirs or --venv")
        return

    if initial_sync:
        # todo: should we allow syncing the venv as well?
        print(f"beginning initial sync {' (venv *NOT* included)' if venv else ''}...")
        on_change(watch_list, False)
        print("remote up to speed with local. Starting watcher...")

    print("\nwatching: \n\t%s" % "\n\t".join(map(str, watch_list)))
    if venv_list:
        print(f"watching (venv): \n\t{venv}/**")
    print(
        "\nKill the process (Ctrl+C) to interrupt. "
        "Any local changes will be pushed to the remote(s).\n"
    )

    hashes = {}

    def _check_changed(file) -> bool:
        logger.debug(f"checking {file}")
        if old_tstamp := hashes.get(file, None):
            try:
                new_tstamp = os.path.getmtime(file)
            except FileNotFoundError:
                logger.error(f"skipping sync for {file}: cannot stat (file does not exist)")
                return False
            if new_tstamp == old_tstamp:
                logger.debug(f"timestamp unchanged {old_tstamp}")
                return False
            logger.debug(f"changed: {file}")
            hashes[file] = new_tstamp
            return True
        else:
            hashes[file] = os.path.getmtime(file)
        return False

    has_logged_first_elapsed = False

    while True:
        start_time = time.time()

        # determine which files have changed
        changed_files = (file for file in watch_list if _check_changed(file))
        if changed_files:
            on_change(changed_files, False)

        if venv:
            # determine which local python packages have changed
            changed_python_packages = (file for file in venv_list if _check_changed(file))
            if changed_python_packages:
                on_change(changed_python_packages, True)

        elapsed = time.time() - start_time
        if not has_logged_first_elapsed:
            # only log this once, it's unlikely to change much
            has_logged_first_elapsed = True
            logger.debug("--- check done in %s seconds ---" % round(elapsed, 2))

        time.sleep(max(0, int(refresh_rate - elapsed)))


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


def _resolve_package_name(pkg_path: Path) -> str:
    """Resolve the importable package name from a local Python package directory.

    Looks for pyproject.toml ``[project].name`` or ``[tool.poetry].name``,
    then setup.cfg ``[metadata].name``.  Normalizes per PEP 503
    (lowercase, hyphens → underscores).  Falls back to the directory name.
    """
    pyproject = pkg_path / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = toml.load(pyproject)
            name = data.get("project", {}).get("name") or data.get("tool", {}).get(
                "poetry", {}
            ).get("name")
            if name:
                return re.sub(r"[-_.]+", "_", name).lower()
        except Exception as e:
            logger.warning(f"failed to parse {pyproject}: {e}")

    setup_cfg = pkg_path / "setup.cfg"
    if setup_cfg.is_file():
        try:
            cfg = configparser.ConfigParser()
            cfg.read(str(setup_cfg))
            name = cfg.get("metadata", "name", fallback=None)
            if name:
                return re.sub(r"[-_.]+", "_", name).lower()
        except Exception as e:
            logger.warning(f"failed to parse {setup_cfg}: {e}")

    logger.info(
        f"no pyproject.toml/setup.cfg found in {pkg_path}; "
        f"using directory name {pkg_path.name!r} as package name"
    )
    return pkg_path.name


def _discover_remote_python_version(
    unit: str,
    model: Optional[str],
    container_name: str,
    venv_lib_path: str,
) -> str:
    """Discover the python3.X directory inside the remote charm venv.

    Lists ``<venv_lib_path>/`` via ``juju ssh`` and returns the first entry
    matching ``python3.*`` (highest version if multiple are found).
    """
    model_arg = f" -m {model}" if model else ""

    substrate = get_substrate(model)
    if substrate == "k8s":
        container_arg = f" --container {container_name}" if container_name else ""
        cmd = f"juju ssh{model_arg}{container_arg} {unit} ls {venv_lib_path}"
    else:
        cmd = f"juju ssh{model_arg} {unit} ls {venv_lib_path}"

    proc = JSubprocess.popen(shlex.split(cmd), wait=True)
    stdout = proc.stdout.read().decode("utf-8").strip()
    if proc.returncode:
        stderr = proc.stderr.read().decode("utf-8").strip()
        exit(
            f"Failed to list remote venv lib directory ({venv_lib_path}) on {unit}.\n"
            f"  stderr: {stderr}\n"
            f"Is the charm deployed with a virtualenv?"
        )

    candidates = sorted(
        [
            line.strip().rstrip("/")
            for line in stdout.splitlines()
            if line.strip().startswith("python3")
        ],
        reverse=True,
    )
    if not candidates:
        exit(
            f"No python3.X directory found in {venv_lib_path} on {unit}.\n"
            f"  ls output: {stdout!r}\n"
            f"Is the charm deployed with a virtualenv?"
        )

    if len(candidates) > 1:
        logger.warning(
            f"multiple python directories found in remote venv: {candidates}; "
            f"using {candidates[0]}"
        )

    return candidates[0]


# TODO: add --watch flag to switch between the one-shot force-feed functionality and the
#  legacy 'sync' mode
#  - plus change warning


def _sync(
    targets: List[str] = None,
    model: str = None,
    source_dirs: List[str] = None,
    touch: List[Path] = None,
    remote_root: str = None,
    container_name: str = "charm",
    refresh_rate: float = 1,
    recursive: bool = True,
    dry_run: bool = False,
    initial_sync: bool = False,
    include_files: str = ".*\.py$",
    venv: Optional[Path] = None,
    single_dependency: Optional[Path] = None,
):
    status = juju_status(json=True, model=model)
    apps_status = status.get("applications")
    if not apps_status:
        exit("no applications found in `juju status`. Is the model still being spun up?")

    if not targets:
        local_charm_meta = Path.cwd() / "charmcraft.yaml"
        if not local_charm_meta.exists():
            exit(
                "you need to cd to a charm repo root for `jhack sync` "
                "to work without targets argument. "
                "Alternatively, pass a juju unit/application name as first argument."
            )

        name = yaml.safe_load(local_charm_meta.read_text()).get("name")
        if not name:
            name = yaml.safe_load((Path.cwd() / "metadata.yaml").read_text()).get("name")
            if not name:
                exit(
                    "could not find name in charmcraft.yaml / metadata.yaml. "
                    "Specify a target manually."
                )

        targets = [app for app, appmeta in apps_status.items() if appmeta["charm-name"] == name]

    if "*" in targets:
        targets = list(apps_status)

    units: typing.Set[str] = set()
    for target in targets:
        if "/" in target:  # unit name
            units.add(target)
        else:  # app name
            unit_tgts = _get_units(target, status)
            units.update(t.unit_name for t in unit_tgts)

    if not units:
        exit("No targets found.")

    local_root_override = None

    if single_dependency:
        dep_path = Path(single_dependency).expanduser().resolve()
        if not dep_path.is_dir():
            exit(f"--single-dependency: not a directory: {single_dependency}")

        pkg_name = _resolve_package_name(dep_path)
        print(f"Resolved package name: {pkg_name!r}")

        # Pick the first unit to probe the remote venv structure.
        first_unit = next(iter(units))
        app, _, unit_id = first_unit.rpartition("/")

        venv_lib_path = f"/var/lib/juju/agents/unit-{app}-{unit_id}/charm/venv/lib"
        python_dir = _discover_remote_python_version(
            first_unit,
            model,
            container_name,
            venv_lib_path,
        )
        print(f"Detected remote Python: {python_dir}")

        # Build the remote root so that files inside dep_path are pushed to
        # <venv>/lib/<python_dir>/site-packages/<pkg_name>/...
        #
        # push_to_remote_juju_unit (with local_root_override) strips
        # the dep_path prefix from each file's absolute path, leaving only
        # the sub-path *within* the package.  remote_root already ends with
        # <pkg_name>/, so the final remote path becomes:
        #   <site_packages>/<pkg_name>/<sub_path>
        site_packages = (
            "/var/lib/juju/agents/unit-{{app}}-{{unit_id}}/charm/venv/"
            f"lib/{python_dir}/site-packages/"
        )
        remote_root = site_packages + pkg_name + "/"
        local_root_override = str(dep_path)
        source_dirs = [str(single_dependency)]

    venv = venv.expanduser().absolute() if venv else None

    remote_root = remote_root or "/var/lib/juju/agents/unit-{app}-{unit_id}/charm/"
    remote_venv_root = "/var/lib/juju/agents/unit-{app}-{unit_id}/charm/venv/"
    if remote_root == "__venv__":
        remote_root = remote_venv_root

    if touch:
        print("Touching: ")
        coros = []
        for file in touch:
            for unit in units:
                coros.append(
                    push_to_remote_juju_unit(
                        file,
                        remote_root=remote_root,
                        is_venv=False,
                        model=model,
                        remote_venv_root=remote_venv_root,
                        unit=unit,
                        container_name=container_name,
                        dry_run=dry_run,
                        local_root_override=local_root_override,
                    )
                )

        loop = asyncio.events.get_event_loop()
        loop.run_until_complete(asyncio.gather(*coros))
        print("Initial sync done.")

    def on_change(changed_files: typing.Iterable[typing.Union[str, Path]], is_venv: bool = False):
        loop = asyncio.events.get_event_loop()
        loop.run_until_complete(
            asyncio.gather(
                *(
                    push_to_remote_juju_unit(
                        changed,
                        remote_root=remote_root,
                        is_venv=is_venv,
                        remote_venv_root=remote_venv_root,
                        unit=unit,
                        model=model,
                        container_name=container_name,
                        dry_run=dry_run,
                        local_root_override=local_root_override,
                    )
                    for unit, changed in product(units, changed_files)
                )
            )
        )
        time.sleep(refresh_rate)

    print("Ready to sync to: \n\t%s" % "\n\t".join(units))
    if model:
        print(f"(In model {model}.)")

    watch_dirs = source_dirs or ["./src", "./lib"]

    watch(
        paths=watch_dirs,
        venv=venv,
        on_change=on_change,
        include_files=include_files,
        recursive=recursive,
        refresh_rate=refresh_rate,
        initial_sync=initial_sync,
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
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="The model in which the target lives. "
    ),
    source_dirs: List[str] = typer.Option(
        ["./src", "./lib"],
        "--source",
        "-s",
        help="Local directories to watch for changes. "
        "Repeat for each directory (e.g --source ./src --source ./lib).",
    ),
    remote_root: str = typer.Option(
        None,
        "--remote-root",
        "-r",
        help="The remote path to be interpreted as root relative to which the local "
        "changes will be pushed. E.g. if the local `./src/charm.py` changes, and the "
        "remote-root is `/var/log/`, the file will be "
        "pushed to {unit}:/var/log/src/charm.py`. "
        "If remote-root is `__venv__`, "
        "the remote path will be set to the charm's venv.",
    ),
    container_name: str = typer.Option("charm", "--container", "-c", help="Container to scp to."),
    refresh_rate: float = typer.Option(
        1, "--refresh-rate", help="Rate at which we will check for changes, in seconds."
    ),
    recursive: bool = typer.Option(
        True,
        "--non-recursive",
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
        help="A regex to filter the watchable files with. By defauly, we only sync *.py files.",
    ),
    skip_initial_sync: bool = typer.Option(
        None,
        "--skip-initial-sync",
        "-S",
        help="DEPRECATED flag. Use initial_sync instead.",
    ),
    initial_sync: bool = typer.Option(
        False,
        "--initial-sync",
        "-s",
        help="Perform an initial sync by pushing all local files to the remote. This can take a while. "
        "Without this flag, only the files you touch AFTER the process is started will be synced.",
        is_flag=True,
    ),
    venv: Optional[Path] = typer.Option(
        None,
        "--venv",
        "-v",
        help="Sync from this directory into the charm's venv. "
        "This feature is experimental and may cause irreparable damage to your computer.",
    ),
    touch: List[Path] = typer.Option(
        None,
        "--touch",
        help="Only push these files and exit. Overrules --skip-initial-sync and --source-dirs",
    ),
    single_dependency: Optional[Path] = typer.Option(
        None,
        "--single-dependency",
        "-d",
        help="Watch a local Python package directory and sync changes into the "
        "charm's remote venv site-packages. The package name is auto-detected "
        "from pyproject.toml/setup.cfg, or inferred from the directory name. "
        "Mutually exclusive with --venv, --remote-root, and --source.",
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
    check_destructive_commands_allowed("sync")

    if single_dependency:
        if venv is not None:
            exit(
                "Error: --single-dependency is mutually exclusive with --venv. "
                "--single-dependency already syncs into the charm's venv."
            )
        if remote_root is not None:
            exit(
                "Error: --single-dependency is mutually exclusive with --remote-root. "
                "--single-dependency automatically targets the charm's venv site-packages."
            )
        # Detect if --source was explicitly provided (differs from default)
        if source_dirs != ["./src", "./lib"]:
            exit(
                "Error: --single-dependency is mutually exclusive with --source. "
                "--single-dependency sets its own watch directory."
            )

    if skip_initial_sync:
        logger.warning(
            "the `skip_initial_sync` (default False) is deprecated in favour of `initial_sync` (default False). "
            "That is, initial sync used to be opt-out, now it's opt-in, because I figured out it was a bad idea."
            "That is, the default behaviour is flipped. This will work for now, but will be removed in a future version."
        )
        initial_sync = not skip_initial_sync

    return _sync(
        targets=target,
        model=model,
        source_dirs=source_dirs,
        touch=touch,
        remote_root=remote_root,
        container_name=container_name,
        refresh_rate=refresh_rate,
        recursive=recursive,
        dry_run=dry_run,
        include_files=include_files,
        initial_sync=initial_sync,
        venv=venv,
        single_dependency=single_dependency,
    )


async def push_to_remote_juju_unit(
    file: Path,
    remote_root: str,
    is_venv: bool,
    remote_venv_root: str,
    unit: str,
    container_name: str,
    model: str = None,
    dry_run: bool = False,
    local_root_override: str = None,
):
    app, _, unit_id = unit.rpartition("/")

    # if the file is in the venv:
    if is_venv:
        abspath = str(file.absolute())
        try:
            pkg_path = abspath.split("/site-packages/")[1]
        except IndexError:
            # TODO: how robust is this heuristic?
            logger.error(
                f"venv file {file!r} doesn't have expected `site-packages` parent directory."
                f" please report an issue."
            )
            return

        remote_file_path = (remote_venv_root + pkg_path).format(unit_id=unit_id, app=app)
    else:
        local_root = local_root_override or os.getcwd()
        remote_file_path = (remote_root + str(file.absolute())[len(local_root) + 1 :]).format(
            unit_id=unit_id, app=app
        )

    push_file(
        unit,
        file,
        remote_file_path,
        is_full_path=True,
        container=container_name,
        dry_run=dry_run,
        model=model,
        mkdir_remote=True,
    )
    if dry_run:
        return

    ts = time.time()
    timestamp = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    print(f"{timestamp}: synced {file} -> {unit}:{remote_file_path}")


if __name__ == "__main__":
    os.chdir("/home/pietro/canonical/tempo-worker-k8s-operator")
    _sync(
        initial_sync=True,
        dry_run=True,
        venv=Path("/home/pietro/canonical/tempo-worker-k8s-operator/.venv"),
    )
