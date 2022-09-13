import json
import tempfile
from pathlib import Path
from subprocess import check_call, check_output
from typing import Union, Optional

import typer

from jhack.utils.event_recorder.recorder import event_db, DEFAULT_DB_NAME
from jhack.utils.simulate_event import _simulate_event


def _fetch_db(unit: str, remote_db_path: str, local_db_path: Path):
    unit_sanitized = unit.replace('/', '-')
    cmd = f"juju ssh {unit} cat /var/lib/juju/agents/unit-{unit_sanitized}/charm/{remote_db_path}"
    raw = check_output(cmd.split())
    local_db_path.write_bytes(raw)


def _print_events(db_path: Union[str, Path]):
    try:
        with event_db(db_path) as data:
            print('Listing recorded events:')
            for i, event in enumerate(data.events):
                print(f"\t({i}) {event.datetime} :: {event.name}")
            if not data.events:
                print('\t<no events>')

    except json.JSONDecodeError as e:
        raise RuntimeError('error decoding json db: it could be that the unit '
                           'has not run any event yet and the db is therefore '
                           'not initialized yet.') from e


def _list_events(unit: str, db_path=DEFAULT_DB_NAME):
    with tempfile.NamedTemporaryFile() as temp_db:
        temp_db_file = Path(temp_db.name)
        _fetch_db(unit, remote_db_path=db_path, local_db_path=temp_db_file)
        _print_events(temp_db_file)


def list_events(
        unit: str = typer.Argument(
            ..., help="Target unit."),
        db_path=DEFAULT_DB_NAME):
    """List the events that have been captured on the unit and are stored in the database."""
    return _list_events(unit, db_path)


def _emit(unit: str, idx: int, db_path=DEFAULT_DB_NAME, dry_run: bool = False):
    with tempfile.NamedTemporaryFile() as temp_db:
        temp_db = Path(temp_db.name)
        _fetch_db(unit, remote_db_path=db_path, local_db_path=temp_db)

        with event_db(temp_db) as data:
            event = data.events[idx]

    print(f"{'Would replay' if dry_run else 'Replaying'} event ({idx}): {event.name} as originally emitted at {event.timestamp}.")
    if dry_run:
        return

    return _simulate_event(unit, event.name,
                           env_override=[f"{k}='{v}'" for k, v in event.env.items()])


def emit(
        unit: str = typer.Argument(
            ..., help="Target unit."),
        idx: Optional[int] = typer.Argument(
            -1,
            help="Index of the event to re-fire"),
        db_path=DEFAULT_DB_NAME,
        dry_run: bool = False):
    """Select the `idx`th event stored on the unit db and re-fire it."""
    _emit(unit, idx, db_path, dry_run=dry_run)


def _dump_db(unit: str, idx: int = -1, db_path=DEFAULT_DB_NAME):
    with tempfile.NamedTemporaryFile() as temp_db:
        temp_db = Path(temp_db.name)
        _fetch_db(unit, db_path, temp_db)

        if idx is not None:
            evt = json.loads(temp_db.read_text()).get('events', {})[idx]
            print(json.dumps(evt, indent=2))

        else:
            print(temp_db.read_text())


def dump_db(
        unit: str = typer.Argument(
            ..., help="Target unit."),
        idx: Optional[int] = typer.Argument(
            -1,
            help="Index of the event to dump (as per `list`), or '' if you want "
                 "to dump the full db."),
        db_path=DEFAULT_DB_NAME):
    """Dump a single event (by default, the last one).

    Or the whole the db as json (if idx is 'db').
    """
    return _dump_db(unit, idx, db_path)


if __name__ == '__main__':
    _emit('trfk/0', 15)
