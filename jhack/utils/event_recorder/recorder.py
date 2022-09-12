import datetime
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Generator, List, Dict

DEFAULT_DB_NAME = 'event_db.json'


class DB:
    def __init__(self, file: Path) -> None:
        self._file = file
        self.data = None

    def load(self):
        text = self._file.read_text()
        raw = json.loads(text)
        events = [Event(**obj) for obj in raw.get('events', ())]
        self.data = Data(events)

    def commit(self):
        self._file.write_text(json.dumps(asdict(self.data), indent=2))


@dataclass
class Event:
    env: Dict[str, str]
    timestamp: str  # datetime.datetime

    @property
    def name(self):
        return self.env['JUJU_DISPATCH_PATH'].split('/')[1]

    @property
    def datetime(self):
        return datetime.datetime.fromisoformat(self.timestamp)


@dataclass
class Data:
    events: List[Event]


@contextmanager
def event_db(file=DEFAULT_DB_NAME) -> Generator[Data, None, None]:
    path = Path(file)
    if not path.exists():
        print(f'Initializing DB file at {path}...')
        path.touch(mode=0o666)
        path.write_text('{}')  # empty json obj

    db = DB(file=path)
    db.load()
    yield db.data
    db.commit()


def _capture() -> Event:
    return Event(
        env=dict(os.environ),
        timestamp=datetime.datetime.now().isoformat()
    )


def record(file=DEFAULT_DB_NAME):
    with event_db(file) as data:
        events = data.events
        event = _capture()
        events.append(event)
        print(f'Captured event: {event.name}')
