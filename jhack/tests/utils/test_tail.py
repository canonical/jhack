import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import jhack.utils.tail_charms

jhack.utils.tail_charms.MODEL_LOGLEVEL = "DEBUG"
from jhack.utils.tail_charms import Processor, Target, _tail_events


def _mock_emit(
    event_name,
    app_name="myapp",
    unit_number=0,
    event_n=0,
    timestamp="12:17:50",
    loglevel="DEBUG",
):
    defaults = {}
    defaults.update(
        {
            "app_name": app_name,
            "unit_number": unit_number,
            "event_name": event_name,
            "event_n": event_n,
            "timestamp": timestamp,
            "loglevel": loglevel,
        }
    )
    emit = (
        "unit-{app_name}-{unit_number}: {timestamp} "
        "DEBUG unit.{app_name}/{unit_number}.juju-log "
        "Emitting Juju event {event_name}."
    )

    return emit.format(**defaults)


def mock_uniter_events_only(value: bool = True):
    def _mock_loglevel(model=None):
        return "WARNING" if value else "TRACE"

    jhack.utils.tail_charms.model_loglevel = _mock_loglevel
    # this will make the parser only try to match "unit.myapp/0.juju-log Emitting Juju event..".


MOCK_JDL = {
    # scenario 1: emit, defer, reemit
    1: b"""unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event start.
        unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event update_status.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/update_status[0]>.
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/update_status[0]>.
        """,
    # scenario 2: defer "the same event" twice.
    2: b"""unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event a.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/a[0]>.
        unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event b.
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/a[0]>.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/a[0]>.
        unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event c.
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/a[0]>.
        """,
    3:
    # scenario 3: defer "the same event" twice, but messily.
    b"""unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event a.
                unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event b.
                unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/b[0]>.
                unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event c.
                unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/b[0]>.
                unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/b[0]>.
                unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/c[1]>.
                unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event d.
                unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/b[0]>.
                unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/c[1]>.
                """,
    # scenario 4: interleaving.
    4: b"""unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event start.
        unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event install.
        unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event update_status.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/update_status[0]>.
        unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event bork.
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/update_status[0]>.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/update_status[0]>.
        unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log Deferring <EVT via Charm/on/bork[1]>.
        unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event update_status.
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/bork[1]>.
        unit-myapp-0: 12:17:50 DEBUG unit.myapp/0.juju-log Re-emitting <EVT via Charm/on/update_status[0]>.
        """,
}

MOCK_JDL_UNITER_EVTS_ONLY = {
    1: b"""unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "start" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "install" hook (via hook dispatching script: dispatch)
        unit-myapp-0: 12:04:18 INFO juju.worker.uniter.operation ran "update-status" hook (via hook dispatching script: dispatch)
        """,
}

mocks_dir = Path(__file__).parent / "tail_mocks"
with open(mocks_dir / "real-trfk-log.txt", mode="rb") as f:
    logs = f.read()
    MOCK_JDL["real"] = logs

with open(mocks_dir / "real-trfk-cropped.txt", mode="rb") as f:
    logs = f.read()
    MOCK_JDL["cropped"] = logs


def _fake_log_proc(n):
    proc = MagicMock()
    proc.stdout.readlines.return_value = MOCK_JDL[n].split(b"\n")
    return proc


@pytest.fixture(params=(1, 2, 3, 4))
def mock_stdout(request):
    n = request.param
    with patch(
        "jhack.utils.tail_charms._get_debug_log", wraps=lambda _: _fake_log_proc(n)
    ):
        yield


@pytest.fixture(autouse=True)
def silence_console_prints():
    with patch("rich.console.Console.print", wraps=lambda _: None):
        yield


# expected scenario 1:
#  ┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
#  ┃ timestamp ┃ myapp/0              ┃
#  ┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
#  │ 12:17:50  │ (0) update_status ❮┐ │
#  │ 12:04:18  │ (0) update_status ❯┘ │
#  │ 12:04:18  │ start                │
#  └───────────┴──────────────────────┘


@pytest.mark.parametrize("deferrals", (True, False))
@pytest.mark.parametrize("length", (3, 10, 100))
def test_tail(deferrals, length, mock_stdout):
    _tail_events(targets="myapp/0", length=length, show_defer=deferrals, watch=False)


@pytest.mark.parametrize("deferrals", (True, False))
@pytest.mark.parametrize("length", (3, 10, 100))
@pytest.mark.parametrize("show_ns", (True, False))
def test_with_real_trfk_log(deferrals, length, show_ns):
    with patch(
        "jhack.utils.tail_charms._get_debug_log", wraps=lambda _: _fake_log_proc("real")
    ):
        _tail_events(
            targets="trfk/0",
            length=length,
            show_ns=show_ns,
            show_defer=deferrals,
            watch=False,
        )


@pytest.mark.parametrize("deferrals", (True, False))
@pytest.mark.parametrize("length", (3, 10, 100))
def test_with_cropped_trfk_log(deferrals, length):
    with patch(
        "jhack.utils.tail_charms._get_debug_log",
        wraps=lambda _: _fake_log_proc("cropped"),
    ):
        _tail_events(targets="trfk/0", length=length, show_defer=deferrals, watch=False)


def test_tracking():
    mock_uniter_events_only(False)
    p = Processor([Target("myapp", 0)], show_defer=True)
    l1, l2, l3, l4 = [
        line.decode("utf-8").strip() for line in MOCK_JDL[1].split(b"\n")[:-1]
    ]
    raw_table = p._raw_tables["myapp/0"]

    p.process(l1)
    assert raw_table.deferrals == [None]
    assert raw_table.ns == [None]
    assert raw_table.events == ["start"]
    assert raw_table.currently_deferred == []

    p.process(l2)
    assert raw_table.deferrals == [None, None]
    assert raw_table.ns == [None, None]
    assert raw_table.events == ["update_status", "start"]
    assert raw_table.currently_deferred == []

    p.process(l3)
    assert raw_table.deferrals == ["deferred", None]
    assert raw_table.ns == ["0", None]
    assert raw_table.events == ["update_status", "start"]
    assert len(raw_table.currently_deferred) == 1

    p.process(l4)
    assert raw_table.deferrals == [
        "reemitted",
        "deferred",
        None,
    ]
    assert raw_table.ns == ["0", "0", None]
    assert raw_table.events == ["update_status", "update_status", "start"]
    assert len(raw_table.currently_deferred) == 0


def test_tracking_uniter_logs():
    mock_uniter_events_only()
    p = Processor([Target("myapp", 0)], show_defer=True)
    l1, l2, l3 = [
        line.decode("utf-8").strip()
        for line in MOCK_JDL_UNITER_EVTS_ONLY[1].split(b"\n")[:-1]
    ]
    raw_table = p._raw_tables["myapp/0"]

    p.process(l1)
    assert raw_table.deferrals == [None]
    assert raw_table.ns == [None]
    assert raw_table.events == ["start"]
    assert raw_table.currently_deferred == []

    p.process(l2)
    assert raw_table.deferrals == [None, None]
    assert raw_table.ns == [None, None]
    assert raw_table.events == ["install", "start"]
    assert raw_table.currently_deferred == []

    p.process(l3)
    assert raw_table.deferrals == [None, None, None]
    assert raw_table.ns == [None, None, None]
    assert raw_table.events == ["update_status", "install", "start"]
    assert raw_table.currently_deferred == []


def test_tracking_reemit_only():
    mock_uniter_events_only(False)

    # we only process a `Re-emitting` log, this should cause Processor to mock a defer,
    # and mock an emit before that.
    p = Processor([Target("myapp", 0)], show_defer=True)
    reemittal = MOCK_JDL[1].split(b"\n")[-2].decode("utf-8").strip()
    raw_table = p._raw_tables["myapp/0"]

    p.process(reemittal)
    assert raw_table.deferrals == [
        "reemitted",
        "deferred",
    ]
    assert raw_table.ns == ["0", "0"]
    assert raw_table.events == ["update_status", "update_status"]
    assert len(raw_table.currently_deferred) == 0


def test_tail_with_file_input():
    _tail_events(
        files=[
            mocks_dir / "real-prom-cropped-for-interlace.txt",
            mocks_dir / "real-trfk-cropped-for-interlace.txt",
        ]
    )


@pytest.mark.parametrize(
    "pattern, log, match",
    (
        (None, _mock_emit("foo"), True),
        ("bar", _mock_emit("foo"), False),
        ("foo", _mock_emit("foo"), True),
        ("(?!foo)", _mock_emit("foo"), False),
        ("(?!foo)", _mock_emit("foob"), False),
        ("(?!foo)", _mock_emit("boof"), True),
    ),
)
def test_tail_event_filter(pattern, log, match):
    proc = Processor(
        targets=[], event_filter_re=(re.compile(pattern) if pattern else None)
    )
    msg = proc.process(log)
    if match:
        assert msg
    else:
        assert msg is None


def test_machine_log_with_subordinates():
    mock_uniter_events_only(False)
    proc = _tail_events(
        length=30, replay=True, files=[str(mocks_dir / "machine-sub-log.txt")]
    )
    assert len(proc.targets) == 4

    assert proc._raw_tables["mongodb/0"].events == [
        None,
        "testing_mock",
    ]  # mock event we added
    assert proc._raw_tables["ceil/0"].events == ["testing_mock"]  # mock event we added
    assert proc._raw_tables["prometheus-node-exporter/0"].events == [
        None,
        None,
        "juju_info_relation_changed",
        "juju_info_relation_joined",
        "start",
        "config_changed",
        "leader_elected",
        "juju_info_relation_created",
        "install",
    ]
    assert proc._raw_tables["ubuntu/0"].events == [
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "update_status",
        "start",
        "config_changed",
        "leader_elected",
        "install",
    ]


@pytest.mark.parametrize(
    "line, expected_event",
    (
        (
            "unit-prom-1: 12:56:44 DEBUG unit.prom/1.juju-log ingress:1: Emitting custom event "
            "<IngressPerUnitReadyForUnitEvent via PrometheusCharm/IngressPerUnitRequirer[ingress]"
            "/on/ready_for_unit[14]>.",
            "ready_for_unit",
        ),
        (
            "unit-prom-1: 12:56:44 DEBUG unit.prom/1.juju-log ingress:1: Emitting custom event "
            "<Foo via PrometheusCharm/IngressPerUnitRequirer[ingress]"
            "/on/bar[14]>.",
            "bar",
        ),
    ),
)
def test_custom_event(line, expected_event):
    p = Processor([Target("prom", 1)])
    p.process(line)
    assert p._raw_tables["prom/1"].events


def test_borky_trfk_log_defer():
    _tail_events(
        length=30,
        replay=True,
        files=[str(mocks_dir / "trfk_mock_bork_defer.txt")],
        show_defer=True,
    )


def test_trace_ids_relation_evt():
    p = Processor([Target("prom", 1)], show_trace_ids=True)
    for line in (
        "prom-1: 12:56:44 DEBUG unit.prom/1.juju-log ingress:1: Starting root trace with id=12312321412412312321.",
        "prom-1: 12:56:44 DEBUG unit.prom/1.juju-log ingress:1: Emitting custom event "
        "<IngressPerUnitReadyForUnitEvent via A/B[ingress]"
        "/on/ready_for_unit[14]>.",
    ):
        p.process(line)
    evt = p._raw_tables["prom/1"].msgs[0]
    assert evt.trace_id == "12312321412412312321"


def test_trace_ids_no_relation_evt():
    p = Processor([Target("prom", 1)], show_trace_ids=True)
    for line in (
        "prom-1: 12:56:44 DEBUG unit.prom/1.juju-log Starting root trace with id=12312321412412312321.",
        "prom-1: 12:56:44 DEBUG unit.prom/1.juju-log Emitting custom event "
        "<IngressPerUnitReadyForUnitEvent via A/B[ingress]"
        "/on/ready_for_unit[14]>.",
    ):
        p.process(line)
    evt = p._raw_tables["prom/1"].msgs[0]
    assert evt.trace_id == "12312321412412312321"
