import tempfile
from pathlib import Path

from jhack.utils.event_recorder import recorder
from jhack.utils.event_recorder.memo_tools import inject_memoizer
from jhack.utils.event_recorder.recorder import memo, event_db, Scene, Event, Context

mock_ops = """
import random

class _ModelBackend:
    def _private_method(self):
        pass
    def other_method(self):
        pass
    def action_set(self, *args, **kwargs):
        return str(random.random())
    def action_get(self, *args, **kwargs):
        return str(random.random())"""

expected_memoized_ops = """from recorder import memo

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
"""


def test_memoizer_injection():
    with tempfile.NamedTemporaryFile() as file:
        target_file = Path(file.name)
        target_file.write_text(mock_ops)

        inject_memoizer(target_file)

        assert target_file.read_text() == expected_memoized_ops


def test_memoizer_recording():
    with tempfile.NamedTemporaryFile() as temp_db_file:
        Path(temp_db_file.name).write_text('{}')

        @memo(str(Path(temp_db_file.name).absolute()))
        def my_fn(*args, retval=None, **kwargs):
            return retval

        with event_db(temp_db_file.name) as data:
            data.scenes.append(
                Scene(event=Event(env={},
                                  timestamp='10:10')))

        my_fn(10, retval=10, foo='bar')

        with event_db(temp_db_file.name) as data:
            ctx = data.scenes[0].context
            assert ctx.memos
            assert ctx.memos['my_fn'] == [
                [[[10], {'retval': 10, 'foo': 'bar'}], 10]
            ]


def test_memoizer_replay():
    recorder._MEMO_MODE = 'replay'

    with tempfile.NamedTemporaryFile() as temp_db_file:
        Path(temp_db_file.name).write_text('{}')

        @memo(str(Path(temp_db_file.name).absolute()))
        def my_fn(*args, retval=None, **kwargs):
            return retval

        with event_db(temp_db_file.name) as data:
            data.scenes.append(
                Scene(
                    event=Event(env={},
                                timestamp='10:10'),
                    context=Context(
                        memos={'my_fn': [
                            [[[10], {'retval': 10, 'foo': 'bar'}], 20],
                            [[[10], {'retval': 11, 'foo': 'baz'}], 21],
                            [[[11], {'retval': 10, 'foo': 'baq', 'a': 'b'}], 22],
                        ]}
                    )))

        assert my_fn(10, retval=10, foo='bar') == 20
        assert my_fn(10, retval=11, foo='baz') == 21
        assert my_fn(11, retval=10, foo='baq', a='b') == 22
        # memos are all up! we run the actual function.
        assert my_fn(11, retval=10, foo='baq', a='b') == 10

        with event_db(temp_db_file.name) as data:
            ctx = data.scenes[0].context
            assert ctx.memos['my_fn'] == []