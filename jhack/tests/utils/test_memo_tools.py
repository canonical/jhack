import os
import random
import tempfile
from pathlib import Path

import pytest

from jhack.utils.event_recorder import recorder
from jhack.utils.event_recorder.memo_tools import inject_memoizer, memo_import_block
from jhack.utils.event_recorder.recorder import (
    Context,
    Event,
    Memo,
    Scene,
    _reset_replay_cursors,
    event_db,
    memo, MEMO_DATABASE_NAME_KEY, MEMO_MODE_KEY,
)

# we always replay the last event in the default test env.
os.environ["MEMO_REPLAY_IDX"] = "-1"

mock_ops_source = """
import random

class _ModelBackend:
    def _private_method(self):
        pass
    def other_method(self):
        pass
    def action_set(self, *args, **kwargs):
        return str(random.random())
    def action_get(self, *args, **kwargs):
        return str(random.random())
        

class Foo:
    def bar(self, *args, **kwargs):
        return str(random.random())
    def baz(self, *args, **kwargs):
        return str(random.random())
"""

expected_decorated_source = f"""{memo_import_block}
import random

class _ModelBackend():

    def _private_method(self):
        pass

    def other_method(self):
        pass

    @memo()
    def action_set(self, *args, **kwargs):
        return str(random.random())

    @memo()
    def action_get(self, *args, **kwargs):
        return str(random.random())

class Foo():

    @memo()
    def bar(self, *args, **kwargs):
        return str(random.random())

    def baz(self, *args, **kwargs):
        return str(random.random())
"""


def test_memoizer_injection():
    with tempfile.NamedTemporaryFile() as file:
        target_file = Path(file.name)
        target_file.write_text(mock_ops_source)

        inject_memoizer(target_file,
                        decorate={
                            '_ModelBackend': {'action_set', 'action_get'},
                            'Foo': {'bar'}}
                        )

        assert target_file.read_text() == expected_decorated_source


def test_memoizer_recording():
    with tempfile.NamedTemporaryFile() as temp_db_file:
        Path(temp_db_file.name).write_text("{}")
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name

        @memo()
        def my_fn(*args, retval=None, **kwargs):
            return retval

        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        my_fn(10, retval=10, foo="bar")

        with event_db(temp_db_file.name) as data:
            ctx = data.scenes[0].context
            assert ctx.memos
            assert ctx.memos["default.my_fn"].calls == [
                [[[10], {"retval": 10, "foo": "bar"}], 10]
            ]


def test_memoizer_replay():
    os.environ[MEMO_MODE_KEY] = "replay"

    with tempfile.NamedTemporaryFile() as temp_db_file:
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name
        @memo()
        def my_fn(*args, retval=None, **kwargs):
            return retval

        with event_db(temp_db_file.name) as data:
            data.scenes.append(
                Scene(
                    event=Event(env={}, timestamp="10:10"),
                    context=Context(
                        memos={
                            "default.my_fn": Memo(
                                calls=[
                                    [[[10], {"retval": 10, "foo": "bar"}], 20],
                                    [[[10], {"retval": 11, "foo": "baz"}], 21],
                                    [
                                        [[11], {"retval": 10, "foo": "baq", "a": "b"}],
                                        22,
                                    ],
                                ]
                            )
                        }
                    ),
                )
            )

        assert my_fn(10, retval=10, foo="bar") == 20
        assert my_fn(10, retval=11, foo="baz") == 21
        assert my_fn(11, retval=10, foo="baq", a="b") == 22
        # memos are all up! we run the actual function.
        assert my_fn(11, retval=10, foo="baq", a="b") == 10

        with event_db(temp_db_file.name) as data:
            ctx = data.scenes[0].context
            assert ctx.memos["default.my_fn"].cursor == 3


def test_memoizer_nonstrict_mode():
    with tempfile.NamedTemporaryFile() as temp_db_file:
        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name

        _backing = {x: x+1 for x in range(50)}

        @memo(strict=False)
        def my_fn(m):
            return _backing[m]

        os.environ[MEMO_MODE_KEY] = "record"
        for i in range(50):
            assert my_fn(i) == i + 1

        # clear the backing storage
        _backing.clear()

        os.environ[MEMO_MODE_KEY] = "replay"

        # check that the function still works, with unordered arguments and repeated ones.
        values = list(range(50)) * 2
        random.shuffle(values)
        for i in values:
            assert my_fn(i) == i + 1


def test_memoizer_classmethod_recording():
    os.environ[MEMO_MODE_KEY] = "record"

    with tempfile.NamedTemporaryFile() as temp_db_file:
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name

        class Foo:
            @memo('foo')
            def my_fn(*args, retval=None, **kwargs):
                return retval

        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        f = Foo()
        f.my_fn(10, retval=10, foo="bar")

        with event_db(temp_db_file.name) as data:
            memos = data.scenes[0].context.memos
            assert memos["foo.my_fn"].calls == [[[[10], {"retval": 10, "foo": "bar"}], 10]]

            # replace return_value for replay test
            memos["foo.my_fn"].calls = [[[[10], {"retval": 10, "foo": "bar"}], 20]]

        os.environ[MEMO_MODE_KEY] = "replay"
        assert f.my_fn(10, retval=10, foo="bar") == 20

        # memos are up
        assert f.my_fn(10, retval=10, foo="bar") == 10
        assert f.my_fn(10, retval=10, foo="bar") == 10


def test_reset_replay_cursor():
    os.environ[MEMO_MODE_KEY] = "replay"

    with tempfile.NamedTemporaryFile() as temp_db_file:
        Path(temp_db_file.name).write_text("{}")
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name
        @memo()
        def my_fn(*args, retval=None, **kwargs):
            return retval

        with event_db(temp_db_file.name) as data:
            calls = [
                [[[10], {"retval": 10, "foo": "bar"}], 20],
                [[[10], {"retval": 11, "foo": "baz"}], 21],
                [[[11], {"retval": 10, "foo": "baq", "a": "b"}], 22],
            ]

            data.scenes.append(
                Scene(
                    event=Event(env={}, timestamp="10:10"),
                    context=Context(memos={"my_fn": Memo(calls=calls, cursor=2)}),
                )
            )

        with event_db(temp_db_file.name) as data:
            _memo = data.scenes[0].context.memos["my_fn"]
            assert _memo.cursor == 2
            assert _memo.calls == calls

        _reset_replay_cursors(temp_db_file.name)

        with event_db(temp_db_file.name) as data:
            _memo = data.scenes[0].context.memos["my_fn"]
            assert _memo.cursor == 0
            assert _memo.calls == calls
