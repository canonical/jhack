import pytest

from scenario import State
from jhack.scenario.state_apply import (
    JujuUnitName,
    _gather_juju_exec_cmds,
    _gather_raw_calls,
)


@pytest.mark.parametrize(
    "state, expected_j_execs, expected_raw",
    (
        (State(), [], []),
        (State(), [], []),
        (State(), [], []),
    ),
)
def test_call_collect(state, expected_j_execs, expected_raw):
    j_exec_cmds = _gather_juju_exec_cmds(None, state)
    raws = _gather_raw_calls(None, state, JujuUnitName("foo/0"))
    assert j_exec_cmds == expected_j_execs + ['application-version-set ""']
    assert raws == expected_raw
