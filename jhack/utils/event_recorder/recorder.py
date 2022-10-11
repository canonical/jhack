#!/usr/bin/env python3
import datetime
import functools
import inspect
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
MEMO_REPLAY_INDEX_KEY = "MEMO_REPLAY_IDX"
MEMO_DATABASE_NAME_KEY = "MEMO_DATABASE_NAME"
MEMO_MODE_KEY = "MEMO_MODE"


logger = jhack_logger.getChild("recorder")

MemoModes = Literal["record", "replay"]


def _load_memo_mode() -> MemoModes:
    val = os.getenv(MEMO_MODE_KEY, "record")
    if val == "record":
        logger.info("MEMO: recording")
    elif val == "replay":
        logger.info("MEMO: replaying")
    else:
        logger.error(f"MEMO: invalid value ({val!r}). Defaulting to `record`.")
        return "record"
    return typing.cast(MemoModes, val)


def _is_json_serializable(obj: Any):
    try:
        json.dumps(obj)
        return True
    except TypeError:
        return False


def memo(namespace: str = 'default'):
    def decorator(fn):
        if not inspect.isfunction(fn):
            raise RuntimeError(f'Cannot memoize non-function obj {fn!r}.')

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            def propagate():
                """Make the real wrapped call."""
                return fn(*args, **kwargs)

            memoizable_args = args
            if args:
                if not _is_json_serializable(args[0]):
                    # probably we're wrapping a method! which means args[0] is `self`
                    # we can't use `inspect.ismethod(fn)` because at @memo-execution-time, `fn` isn't a method yet!
                    memoizable_args = args[1:]
                else:
                    memoizable_args = args

            database = os.environ.get(
                MEMO_DATABASE_NAME_KEY, DEFAULT_DB_NAME
            )
            with event_db(database) as data:
                if not data.scenes:
                    raise RuntimeError("No scenes: cannot memoize.")
                idx = int(os.environ.get(MEMO_REPLAY_INDEX_KEY, None))

                _MEMO_MODE: MemoModes = _load_memo_mode()

                memo_name = f"{namespace}.{fn.__name__}"
                if _MEMO_MODE == "record":
                    memo = data.scenes[-1].context.memos.get(memo_name, Memo())
                    output = propagate()
                    memo.calls.append(((memoizable_args, kwargs), output))
                    data.scenes[-1].context.memos[memo_name] = memo

                elif _MEMO_MODE == "replay":
                    if idx is None:
                        raise RuntimeError(
                            f"provide a {MEMO_REPLAY_INDEX_KEY} envvar"
                            "to tell the replay environ which scene to look at"
                        )
                    try:
                        idx = int(idx)
                    except TypeError:
                        raise RuntimeError(
                            f"invalid idx: ({idx}); expecting an integer."
                        )

                    try:
                        memo = data.scenes[idx].context.memos[memo_name]

                    except KeyError:
                        # if no memo is present for this function, that might mean that
                        # in the recorded session it was not called (this path is new!)
                        warnings.warn(
                            f"No memo found for {memo_name}: "
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
                            f"Memo cursor {current_cursor} out of bounds for {memo_name}: "
                            f"the path must have changed"
                        )
                        return propagate()

                    (reco_args, reco_kwargs), reco_out = reco

                    # convert args to list for comparison purposes because memos are
                    # loaded from json, where tuples become lists.
                    if (reco_args, reco_kwargs) != (list(memoizable_args), kwargs):
                        warnings.warn(
                            f"memoized {memo_name} arguments don't match "
                            f"the ones received at runtime. This path has diverged."
                        )
                        # fixme: we could relax this strict ordering req for most hook tool calls.
                        return propagate()

                    return reco_out  # happy path! good for you, path.

                else:
                    raise ValueError(f"invalid memo mode: {_MEMO_MODE}")

            return output

        return wrapper

    return decorator


class DB:
    def __init__(self, file: Path) -> None:
        self._file = file
        self.data = None

    def load(self):
        text = self._file.read_text()
        if not text:
            logger.debug("database empty; initializing with data=[]")
            self.data = Data([])
            return

        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f"database invalid: could not json-decode {self._file}")

        try:
            scenes = [Scene.from_dict(obj) for obj in raw.get("scenes", ())]
        except Exception as e:
            raise RuntimeError(
                f"database invalid: could not parse Scenes from {raw[:100]!r}..."
            ) from e

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


def _reset_replay_cursors(file=DEFAULT_DB_NAME, *scene_idx: int):
    """Reset the replay cursor for all scenes, or the specified ones."""
    with event_db(file) as data:
        to_reset = (data.scenes[idx] for idx in scene_idx) if scene_idx else data.scenes
        for scene in to_reset:
            for memo in scene.context.memos.values():
                memo.cursor = 0


def _record_current_event(file) -> Event:
    with event_db(file) as data:
        scenes = data.scenes
        event = _capture()
        scenes.append(Scene(event=event))
    return event


def setup(file=DEFAULT_DB_NAME):
    _MEMO_MODE: MemoModes = _load_memo_mode()

    if _MEMO_MODE == "record":
        event = _record_current_event(file)
        print(f"Captured event: {event.name}.")

    if _MEMO_MODE == "replay":
        _reset_replay_cursors()
        print(f"Replaying: reset replay cursors.")
