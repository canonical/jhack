import datetime
import json
import sys
import tempfile
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_call
from typing import Optional, Union

import typer

from jhack.helpers import fetch_file, juju_log, modify_remote_file
from jhack.logger import logger
from jhack.utils.event_recorder.memo_tools import (
    DECORATE_MODEL,
    DECORATE_PEBBLE,
    inject_memoizer,
)
from jhack.utils.event_recorder.recorder import DEFAULT_DB_NAME, Event, event_db
from jhack.utils.simulate_event import _simulate_event

logger = logger.getChild("event_recorder.client")
RECORDER_SOURCE = Path(__file__).parent / "recorder.py"
BROKEN_ENV_KEYS = {
    # contain whitespace
    "JUJU_API_ADDRESSES",
    "JUJU_METER_INFO",
    # need to skip this one else juju exec will whine
    "JUJU_CONTEXT_ID",
}


def _check_installed(unit):
    if not _is_installed(unit):
        sys.exit(
            f"Recorder is not installed. Do so with `jhack replay install {unit}`."
        )


def fetch_db(unit: str, remote_path: str, local_path: Path = None):
    _check_installed(unit)

    try:
        return fetch_file(unit=unit, remote_path=remote_path, local_path=local_path)
    except RuntimeError as e:
        raise RuntimeError(
            "Probably no event has fired yet. " "Try simulating one with jhack fire."
        ) from e


def _print_events(db_path: Union[str, Path]):
    try:
        with event_db(db_path) as data:
            print("Listing recorded events:")
            for i, scene in enumerate(data.scenes):
                print(f"\t({i}) {scene.event.datetime} :: {scene.event.name}")
            if not data.scenes:
                print("\t<no scenes>")

    except json.JSONDecodeError as e:
        raise RuntimeError(
            "error decoding json db: it could be that the unit "
            "has not run any event yet and the db is therefore "
            "not initialized yet."
        ) from e


def _list_events(unit: str, db_path=DEFAULT_DB_NAME):
    with tempfile.NamedTemporaryFile() as temp_db:
        temp_db_file = Path(temp_db.name)
        fetch_db(unit, remote_path=db_path, local_path=temp_db_file)
        _print_events(temp_db_file)


def list_events(
    unit: str = typer.Argument(..., help="Target unit."), db_path=DEFAULT_DB_NAME
):
    """List the events that have been captured on the unit and are stored in the database."""
    _check_installed(unit)
    return _list_events(unit, db_path)


def _emit(
    unit: str,
    idx: int,
    db_path=DEFAULT_DB_NAME,
    dry_run: bool = False,
    operator_dispatch=False,
):
    # we need to fetch the database to know what event we're talking about, since we're using
    # _simulate_event to fire the event. We could also shortcut this by embedding the
    # 'simulate_event' logic in the recorder script.
    with tempfile.NamedTemporaryFile() as temp_db:
        temp_db = Path(temp_db.name)
        fetch_db(unit, remote_path=db_path, local_path=temp_db)

        with event_db(temp_db) as data:
            event: Event = data.scenes[idx].event

    print(
        f"{'Would replay' if dry_run else 'Replaying'} event ({idx}): "
        f"{event.name} as originally emitted at {event.timestamp}."
    )
    if dry_run:
        return

    # fixme: remove this filter when the simulate_event issue is fixed
    env = dict(event.env)
    env["MEMO_MODE"] = "replay"
    env["MEMO_REPLAY_IDX"] = str(idx)

    if operator_dispatch:
        env["OPERATOR_DISPATCH"] = "1"

    env_override = [f"{k}={v}" for k, v in env.items()]

    _simulate_event(
        unit,
        event.name,
        env_override=env_override,
        print_captured_stderr=True,
        print_captured_stdout=True,
        emit_juju_log=False,  # we emit our own
    )

    try:
        # e.g. 10/12/2022T13:30:05.998884
        ts_hr = event.timestamp.split("T")[1].split(".")[0]
    except IndexError:
        logger.error(
            f"event timestamp invalid: {event.timestamp}, "
            f'expected datetime.datetime.isoformat(sep="T").'
            f"Jhack tail will not be able to pick this up."
        )
        ts_hr = event.timestamp
    juju_log(unit, f"{event.name} ({ts_hr}) was replayed by jhack.")


def emit(
    unit: str = typer.Argument(..., help="Target unit."),
    idx: Optional[int] = typer.Argument(-1, help="Index of the event to re-fire"),
    operator_dispatch: Optional[bool] = typer.Option(
        False,
        "-O",
        "--use-operator-dispatch",
        help="Set the OPERATOR_DISPATCH flag. "
        "This will flag the event as 'fired by the charm itself.'.",
    ),
    db_path=DEFAULT_DB_NAME,
    dry_run: bool = False,
):
    """Select the `idx`th event stored on the unit db and re-fire it."""
    _check_installed(unit)
    _emit(unit, idx, db_path, dry_run=dry_run, operator_dispatch=operator_dispatch)


def _dump_db(unit: str, idx: Optional[int] = None, db_path=DEFAULT_DB_NAME):
    with tempfile.NamedTemporaryFile() as temp_db:
        temp_db = Path(temp_db.name)
        fetch_db(unit, db_path, temp_db)

        if idx is not None:
            evt = json.loads(temp_db.read_text()).get("scenes", {})[idx]
            print(json.dumps(evt, indent=2))

        else:
            print(temp_db.read_text())


def dump_db(
    unit: str = typer.Argument(..., help="Target unit."),
    idx: Optional[int] = typer.Argument(
        None,
        help="Index of the event to dump (as per `list`), or '' if you want "
        "to dump the full db.",
    ),
    db_path=DEFAULT_DB_NAME,
):
    """Dump the whole database or a specific scene as json."""
    _check_installed(unit)
    return _dump_db(unit, idx, db_path)


def _purge_db(unit: str, idxs: str, db_path: str):
    unit_sanitized = unit.replace("/", "-")
    charm_path = f"/var/lib/juju/agents/unit-{unit_sanitized}/charm/{db_path}"
    with modify_remote_file(unit, charm_path) as f:
        with event_db(f) as data:
            if idxs:
                for idx in idxs.split(","):
                    scene = data.scenes.pop(int(idx))
                    print(
                        f"Purged scene {idx}: {scene.event.name} ({scene.event.datetime})"
                    )
            else:
                n_s = len(data.scenes)
                data.scenes = []
                print(f"Purged db ({n_s} scenes).")


def purge_db(
    unit: str = typer.Argument(..., help="Target unit."),
    idx: Optional[str] = typer.Argument(
        None,
        help="Comma-separated list f indices of events to purge (as per `list`); "
        "leave blank to purge the whole db.",
    ),
    db_path=DEFAULT_DB_NAME,
):
    """Purge the database (by default, all of it) or a specific event."""
    _check_installed(unit)
    return _purge_db(unit, idx, db_path)


def _copy_recorder_script(unit: str):
    if "/" not in unit:
        exit(f"invalid unit name: {unit!r}; should contain `/<unit id>`")

    unit_sanitized = unit.replace("/", "-")
    cmd = (
        f"juju scp {RECORDER_SOURCE} "
        f"{unit}:/var/lib/juju/agents/unit-{unit_sanitized}/charm/src/recorder.py"
    )
    check_call(cmd.split())


def _inject_memoizer(unit: str):
    unit_sanitized = unit.replace("/", "-")

    ops_model_path = (
        f"/var/lib/juju/agents/unit-{unit_sanitized}/charm/venv/ops/model.py"
    )
    with modify_remote_file(unit, ops_model_path) as model_source:
        inject_memoizer(model_source, decorate=DECORATE_MODEL)

    ops_pebble_path = (
        f"/var/lib/juju/agents/unit-{unit_sanitized}/charm/venv/ops/pebble.py"
    )
    with modify_remote_file(unit, ops_pebble_path) as pebble_source:
        inject_memoizer(pebble_source, decorate=DECORATE_PEBBLE)


def _inject_record_current_event_call(file):
    charm_path = Path(file)
    charm_py = charm_path.read_text()

    recorder_call = (
        f"    import recorder; recorder.setup()  # record current event call, "
        f"injected by jhack.utils.replay @ {datetime.datetime.now().isoformat()}"
    )

    if recorder_call in charm_py:
        logger.info("recorder already installed, *I think*. Nothing to do...")
        return

    charm_py_lines = charm_path.read_text().split("\n")

    mainline = None
    for idx, line in enumerate(reversed(charm_py_lines)):
        if "__main__" in line:
            # presumably, the line immediately after this one is main(MyCharm)
            mainline = idx
            break

    if mainline is None:
        raise RuntimeError(
            "recorder installation failed: " f"could not find main clause in {file}"
        )

    charm_py_lines.insert(-mainline, recorder_call)
    # in between, somewhere, the `main(MyCharm)` call
    charm_path.write_text("\n".join(charm_py_lines))


def _insert_record_current_event_call(unit):
    unit_sanitized = unit.replace("/", "-")
    charm_path = f"/var/lib/juju/agents/unit-{unit_sanitized}/charm/src/charm.py"
    with modify_remote_file(unit, charm_path) as f:
        _inject_record_current_event_call(Path(f))

    # restore permissions:
    check_call(["juju", "ssh", unit, "chmod", "+x", charm_path])


def _is_installed(unit: str):
    unit_sanitized = unit.replace("/", "-")
    cmd = f"juju ssh {unit} ls /var/lib/juju/agents/unit-{unit_sanitized}/charm/src/recorder.py"

    try:
        check_call(cmd.split(), stderr=PIPE, stdout=PIPE)
    except CalledProcessError:
        return False
    return True


def _install(unit: str):
    recorder_only = False
    if _is_installed(unit):
        while True:
            choice = input(
                f"Recorder is already set up on {unit}. "
                f"Reinstalling it might (probably will) break stuff. You can: \n"
                f"\n\a - Proceed anyway [p]"
                f"\n\a - Only update the recorder [r]"
                f"\n\a - Abort [a]"
                f"\n\n your choice: "
            )
            if choice == "a":
                print("Aborted.")
                return
            elif choice == "r":
                recorder_only = True
                break
            elif choice == "p":
                break
            else:
                print(f"Invalid choice ({choice!r}. Possible options are ['p'|'r'|'a']")

        print("Alright.")

    print("Shelling over recorder script...")
    _copy_recorder_script(unit)

    if recorder_only:
        print("Recorder script refreshed. " "Skipping remaining steps.")
        return

    print("Injecting record_current_event call in charm source...")
    _insert_record_current_event_call(unit)

    print("Injecting @memo in ops source...")
    _inject_memoizer(unit)

    print("Recorder installed.")


def install(unit: str):
    """Install the record spyware on the given unit."""
    return _install(unit)


if __name__ == "__main__":
    # _copy_recorder_script("trfk/0")
    # _emit("trfk/0", 4)

    ts = datetime.datetime(hour=14, minute=53, second=3, day=10, month=10, year=2022)
    isotime = ts.isoformat()
    print(isotime)
    juju_log(
        "indico/0", f"update_status ({isotime.split('T')[1]}) was replayed by jhack."
    )
