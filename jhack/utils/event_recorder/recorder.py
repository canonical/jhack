import datetime
import functools
import json
import os
import warnings
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Generator, List, Literal, Any

DEFAULT_DB_NAME = "event_db.json"

_MEMO_MODE: Literal['record', 'replay'] = 'record'


def memo(db_name: str = DEFAULT_DB_NAME):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            out = fn(*args, **kwargs)
            with event_db(db_name) as data:
                if not data.scenes:
                    raise RuntimeError('No scene: cannot memoize.')
                if _MEMO_MODE == 'record':
                    memo_ = ((args, kwargs), out)
                    memos = data.scenes[-1].context.memos.get(fn.__name__, [])
                    memos.append(memo_)
                    data.scenes[-1].context.memos[fn.__name__] = memos

                elif _MEMO_MODE == 'replay':
                    try:
                        memo = data.scenes[0].context.memos[fn.__name__].pop(0)
                    except (KeyError, IndexError):
                        # if no memo is present for this function, that might mean that
                        # in the recorded session it was not called (this path is new!)
                        warnings.warn(f'No memo found for {fn.__name__}: this path might be new.')
                        return out

                    (memo_args, memo_kwargs), memo_out = memo

                    # convert args to list for comparison purposes because memos are
                    # loaded from json, where tuples become lists.
                    if (memo_args, memo_kwargs) != (list(args), kwargs):
                        warnings.warn(f"memoized {fn.__name__} arguments don't match "
                                      f"the ones received at runtime. This path has diverged.")
                        return out

                    return memo_out  # happy path!

                else:
                    raise ValueError(_MEMO_MODE)

            return out

        return wrapper

    return decorator


class DB:
    def __init__(self, file: Path) -> None:
        self._file = file
        self.data = None

    def load(self):
        text = self._file.read_text()
        raw = json.loads(text)
        scenes = [Scene.from_dict(obj) for obj in raw.get("scenes", ())]
        self.data = Data(scenes)

    def commit(self):
        self._file.write_text(json.dumps(asdict(self.data), indent=2))


@dataclass
class Event:
    env: Dict[str, str]
    timestamp: str  # datetime.datetime

    @property
    def name(self):
        return self.env["JUJU_DISPATCH_PATH"].split("/")[1]

    @property
    def datetime(self):
        return datetime.datetime.fromisoformat(self.timestamp)


@dataclass
class Context:
    memos: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Scene:
    event: Event
    context: Context = Context()

    @staticmethod
    def from_dict(obj):
        return Scene(event=Event(**obj['event']),
                     context=Context(**obj.get('context', {})))


@dataclass
class Data:
    scenes: List[Scene]


@contextmanager
def event_db(file=DEFAULT_DB_NAME) -> Generator[Data, None, None]:
    path = Path(file)
    if not path.exists():
        print(f"Initializing DB file at {path}...")
        path.touch(mode=0o666)
        path.write_text("{}")  # empty json obj

    db = DB(file=path)
    db.load()
    yield db.data
    db.commit()


def _capture() -> Event:
    return Event(env=dict(os.environ), timestamp=datetime.datetime.now().isoformat())


def record(file=DEFAULT_DB_NAME):
    with event_db(file) as data:
        scenes = data.scenes
        event = _capture()
        scenes.append(Scene(event=event))
        print(f"Captured event: {event.name}")
