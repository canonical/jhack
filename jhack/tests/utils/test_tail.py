from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from jhack.utils.tail_charms import _tail_events, Processor, Target

MOCK_JDL = {
    # scenario 1: emit, defer, reemit
    1:
        b"""unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "start" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "update-status" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/update_status[0]>.
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/update_status[0]>.
        """,
    # scenario 2: defer "the same event" twice.
    2:
        b"""unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "a" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/a[0]>.
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "b" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/a[0]>.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/a[0]>.
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "c" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/a[0]>.
        """,
    3:
    # scenario 3: defer "the same event" twice, but messily.
        b"""unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "a" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "b" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/b[0]>.
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "c" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/b[0]>.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/b[0]>.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/c[1]>.
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "d" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/b[0]>.
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/c[1]>.
        """,
    # scenario 4: interleaving.
    4:
        b"""unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "start" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "install" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "update-status" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/update_status[0]>.
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "bork" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/update_status[0]>.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/update_status[0]>.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/bork[1]>.
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "update-status" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/bork[1]>.
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/update_status[0]>.
        """,
}

with open(Path(__file__).parent / 'tail_mocks' / 'real-trfk-log.txt',
          mode='rb') as f:
    logs = f.read()
    MOCK_JDL['real'] = logs

with open(Path(__file__).parent / 'tail_mocks' / 'real-trfk-cropped.txt',
          mode='rb') as f:
    logs = f.read()
    MOCK_JDL['cropped'] = logs


def _fake_log_proc(n):
    proc = MagicMock()
    proc.stdout.readlines.return_value = MOCK_JDL[n].split(b'\n')
    return proc


@pytest.fixture(autouse=True, params=(1, 2, 3, 4))
def mock_stdout(request):
    n = request.param
    with patch("jhack.utils.tail_charms._get_debug_log",
               wraps=lambda _: _fake_log_proc(n)) as mock_status:
        yield


# expected scenario 1:
#  ┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
#  ┃ timestamp ┃ myapp/0              ┃
#  ┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
#  │ 12:17:50  │ (0) update_status ❮┐ │
#  │ 12:04:18  │ (0) update_status ❯┘ │
#  │ 12:04:18  │ start                │
#  └───────────┴──────────────────────┘

@pytest.mark.parametrize('deferrals', (True, False))
@pytest.mark.parametrize('length', (3, 10, 100))
def test_tail(deferrals, length):
    _tail_events(targets='myapp/0', length=length, show_defer=deferrals,
                watch=False)


@pytest.mark.parametrize('deferrals', (True, False))
@pytest.mark.parametrize('length', (3, 10, 100))
@pytest.mark.parametrize('show_ns', (True, False))
def test_with_real_trfk_log(deferrals, length, show_ns):
    with patch("jhack.utils.tail_charms._get_debug_log",
               wraps=lambda _: _fake_log_proc('real')) as mock_status:
        _tail_events(targets='trfk/0', length=length,
                    show_ns=show_ns,
                    show_defer=deferrals, watch=False)


@pytest.mark.parametrize('deferrals', (True, False))
@pytest.mark.parametrize('length', (3, 10, 100))
def test_with_cropped_trfk_log(deferrals, length):
    with patch("jhack.utils.tail_charms._get_debug_log",
               wraps=lambda _: _fake_log_proc('cropped')) as mock_status:
        _tail_events(targets='trfk/0', length=length,
                    show_defer=deferrals, watch=False)


def test_tracking():
    p = Processor([Target('myapp', 0)], show_defer=True)
    l1, l2, l3, l4 = [
        line.decode('utf-8').strip() for line in MOCK_JDL[1].split(b'\n')[:-1]
    ]
    raw_table = p._raw_tables['myapp/0']

    p.process(l1)
    assert raw_table.deferrals == [p._dpad]
    assert raw_table.ns == [None]
    assert raw_table.events == ['start']
    assert raw_table.currently_deferred == []

    p.process(l2)
    assert raw_table.deferrals == [p._dpad, p._dpad]
    assert raw_table.ns == [None, None]
    assert raw_table.events == ['update_status', 'start']
    assert raw_table.currently_deferred == []

    p.process(l3)
    assert raw_table.deferrals == [p._open + p._hline + p._lup, p._dpad]
    assert raw_table.ns == ['0', None]
    assert raw_table.events == ['update_status', 'start']
    assert len(raw_table.currently_deferred) == 1

    p.process(l4)
    assert raw_table.deferrals == [
        p._close + p._hline + p._ldown,
        p._open + p._hline + p._lup,
        p._dpad]
    assert raw_table.ns == ['0', '0', None]
    assert raw_table.events == ['update_status', 'update_status', 'start']
    assert len(raw_table.currently_deferred) == 0



