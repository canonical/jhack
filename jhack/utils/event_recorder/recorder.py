#!/usr/bin/env python3
import datetime
import functools
import json
import os
import typing
import warnings
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Literal, Tuple

try:
    from jhack.logger import logger as jhack_logger
except ModuleNotFoundError:
    # running in unit
    from logging import getLogger

    jhack_logger = getLogger()

DEFAULT_DB_NAME = "event_db.json"
logger = jhack_logger.getChild("recorder")

MemoModes = Literal["record", "replay"]


def _load_memo_mode() -> MemoModes:
    val = os.getenv("MEMO_MODE", "record")
    if val == "record":
        logger.info("MEMO: recording")
    elif val == "replay":
        logger.info("MEMO: replaying")
    else:
        logger.error(f"MEMO: invalid value ({val!r}). Defaulting to `record`.")
        return "record"
    return typing.cast(MemoModes, val)


_MEMO_MODE: MemoModes = _load_memo_mode()


def _is_json_serializable(obj: Any):
    try:
        json.dumps(obj)
        return True
    except TypeError:
        return False


def memo(db_name: str = DEFAULT_DB_NAME):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            def propagate():
                """Make the real wrapped call."""
                return fn(*args, **kwargs)

            memoizable_args = args
            if args:
                if not _is_json_serializable(args[0]):
                    # probably we're wrapping a method! which means args[0] is `self`
                    memoizable_args = args[1:]
                else:
                    memoizable_args = args

            with event_db(db_name) as data:
                if not data.scenes:
                    raise RuntimeError("No scene: cannot memoize.")

                if _MEMO_MODE == "record":
                    memo = data.scenes[-1].context.memos.get(fn.__name__, Memo())
                    memo.calls.append(((memoizable_args, kwargs), propagate()))
                    data.scenes[-1].context.memos[fn.__name__] = memo

                elif _MEMO_MODE == "replay":
                    idx = os.environ.get("MEMO_REPLAY_IDX", None)
                    if idx is None:
                        raise RuntimeError(
                            "provide a MEMO_REPLAY_IDX envvar"
                            "to tell the replay environ which scene to look at"
                        )
                    try:
                        idx = int(idx)
                    except TypeError:
                        raise RuntimeError(
                            f"invalid idx: ({idx}); expecting an integer."
                        )

                    try:
                        memo = data.scenes[idx].context.memos[fn.__name__]

                    except KeyError:
                        # if no memo is present for this function, that might mean that
                        # in the recorded session it was not called (this path is new!)
                        warnings.warn(
                            f"No memo found for {fn.__name__}: "
                            f"this path must be new."
                        )
                        return propagate()

                    try:
                        current_cursor = memo.cursor
                        reco = memo.calls[current_cursor]
                        memo.cursor += 1
                    except IndexError:
                        # There is a memo, but its cursor is out of bounds.
                        # this means the current path is calling the wrapped function
                        # more times than the recorded path did.
                        warnings.warn(
                            f"Memo cursor {current_cursor} out of bounds for {fn.__name__}: "
                            f"the path must have changed"
                        )
                        return propagate()

                    (reco_args, reco_kwargs), reco_out = reco

                    # convert args to list for comparison purposes because memos are
                    # loaded from json, where tuples become lists.
                    if (reco_args, reco_kwargs) != (list(memoizable_args), kwargs):
                        warnings.warn(
                            f"memoized {fn.__name__} arguments don't match "
                            f"the ones received at runtime. This path has diverged."
                        )
                        return propagate()

                    return reco_out  # happy path!

                else:
                    raise ValueError(_MEMO_MODE)
            return propagate()

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
class Memo:
    # list of (args, kwargs), return-value pairs for this memo
    # warning: in reality it's all lists, no tuples.
    calls: List[Tuple[Tuple[List, Dict], Any]] = field(default_factory=list)
    # indicates the position of the replay cursor if we're replaying the memo
    cursor: int = 0


@dataclass
class Context:
    memos: Dict[str, Memo] = field(default_factory=dict)

    @staticmethod
    def from_dict(obj: dict):
        return Context(
            memos={name: Memo(**content) for name, content in obj["memos"].items()}
        )


@dataclass
class Scene:
    event: Event
    context: Context = Context()

    @staticmethod
    def from_dict(obj):
        return Scene(
            event=Event(**obj["event"]),
            context=Context.from_dict(obj.get("context", {})),
        )


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


def _reset_replay_cursors(file=DEFAULT_DB_NAME):
    with event_db(file) as data:
        for scene in data.scenes:
            for memo in scene.context.memos.values():
                memo.cursor = 0

    print("reset all replay cursors")


def _record_current_event(file):
    with event_db(file) as data:
        scenes = data.scenes
        event = _capture()
        scenes.append(Scene(event=event))
        print(f"Captured event: {event.name}")


def setup(file=DEFAULT_DB_NAME):
    if _MEMO_MODE == "record":
        _record_current_event(file)
    if _MEMO_MODE == "replay":
        _reset_replay_cursors()
