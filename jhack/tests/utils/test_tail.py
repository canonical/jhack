import contextlib
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jhack.utils.tail_charms.core.juju_model_loglevel import Level
from jhack.utils.tail_charms.tail_charms import tail_charms
from jhack.utils.tail_charms.core.processor import Processor
from jhack.utils.tail_charms.core.deferral_status import DeferralStatus


@pytest.fixture(autouse=True, scope="module")
def patch_stdin():
    with patch("sys.stdin"):
        yield


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


@contextlib.contextmanager
def mock_uniter_events_only(value: bool = True):
    # if True: the parser will try to match "unit.myapp/0.juju-log Emitting Juju event..".
    # else: ... (via hook dispatching script: dispatch)
    with patch(
        "jhack.utils.tail_charms.core.juju_model_loglevel.model_loglevel",
        lambda model: "WARNING" if value else "TRACE",
    ):
        yield


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
MOCK_JDL["real"] = (mocks_dir / "real-trfk-log.txt").read_bytes()
MOCK_JDL["cropped"] = (mocks_dir / "real-trfk-cropped.txt").read_bytes()
MOCK_JDL["clite"] = (mocks_dir / "jdl_cos_lite.txt").read_bytes()
MOCK_JDL["real-pgql-machine-log"] = (mocks_dir / "real-pgql-machine-log.txt").read_bytes()


def _fake_log_proc(id_):
    data = MOCK_JDL[id_].split(b"\n")
    proc = MagicMock()
    proc.stdout.readline.side_effect = data
    return proc


@pytest.fixture(params=(1, 2, 3, 4))
def mock_stdout(request):
    n = request.param
    with patch(
        "jhack.utils.tail_charms.tail_charms._get_debug_log",
        wraps=lambda _: _fake_log_proc(n),
    ):

        def fake_find_leaders(apps, model=None):
            return {app: f"{app}/0" for app in apps}

        with patch(
            "jhack.utils.tail_charms.tail_charms.find_leaders",  # imported from jhack.helpers
            new=fake_find_leaders,
        ):
            yield


def test_jdl_cos_lite():
    with patch(
        "jhack.utils.tail_charms.tail_charms._get_debug_log",
        wraps=lambda _: _fake_log_proc("clite"),
    ):

        def fake_find_leaders(apps, model=None):
            return {app: f"{app}/0" for app in apps}

        with patch(
            "jhack.utils.tail_charms.tail_charms.find_leaders",  # imported from jhack.helpers
            new=fake_find_leaders,
        ):
            tail_charms()


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
    tail_charms(targets=["myapp/0"], length=length, show_defer=deferrals, watch=False)


# FIXME: very slow tests, and little value
# @pytest.mark.parametrize("deferrals", (True, False))
# @pytest.mark.parametrize("length", (3, 10, 100))
# @pytest.mark.parametrize("show_ns", (True, False))
# def test_with_real_trfk_log(deferrals, length, show_ns):
#     with mock_uniter_events_only(False):
#         with patch(
#             "jhack.utils.tail_charms.tail_charms._get_debug_log",
#             wraps=lambda _: _fake_log_proc("real"),
#         ):
#             tail_charms(
#                 targets=["trfk/0"],
#                 length=length,
#                 show_ns=show_ns,
#                 show_defer=deferrals,
#                 watch=False,
#                 level=Level.DEBUG,
#             )


# @pytest.mark.parametrize("deferrals", (True, False))
# @pytest.mark.parametrize("length", (3, 10, 100))
# def test_with_cropped_trfk_log(deferrals, length):
#     with patch(
#         "jhack.utils.tail_charms.tail_charms._get_debug_log",
#         wraps=lambda _: _fake_log_proc("cropped"),
#     ):
#         tail_charms(targets="trfk/0", length=length, show_defer=deferrals, watch=False)


def test_jhack_fire_log():
    # scenario 5: jhack fire
    with mock_uniter_events_only(False):
        proc = Processor([], level=Level.DEBUG)
        lines = [
            "unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event start.",
            "unit-myapp-0: 12:04:18 INFO unit.myapp/0.juju-log Emitting Juju event update_status.",
            "unit-myapp-0: 13:23:30 DEBUG unit.myapp/0.juju-log The previous update-status was fired by jhack.",
        ]
        for line in lines:
            proc.process(line)
    captured = proc._captured_logs
    assert len(captured) == 2
    assert captured[1].tags == ("jhack", "fire")

    out = proc.printer.render(proc._captured_logs, _debug=True)
    # out.columns[1].cells


def test_defer_log():
    # scenario 5: jhack fire
    with mock_uniter_events_only(False):
        proc = Processor([], show_defer=True)

        # we emit update status
        proc.process(
            "unit-traefik-0: 12:04:18 INFO unit.traefik/0.juju-log Emitting Juju event update_status."
        )
    e0 = proc._captured_logs[0]
    assert not proc._currently_deferred
    assert e0.event == "update_status"
    assert e0.deferred == DeferralStatus.null
    assert not e0.tags

    proc.process(
        "unit-traefik-0: 12:04:18 DEBUG unit.traefik/0.juju-log Deferring <UpdateStatusEvent via TraefikIngressCharm/on/update_status[318]>."
    )
    assert proc._currently_deferred
    assert e0.deferred == DeferralStatus.deferred
    assert not e0.tags

    proc.process(
        "unit-traefik-0: 12:04:18 DEBUG unit.traefik/0.juju-log The previous update-status was fired by jhack."
    )
    assert e0.deferred == DeferralStatus.deferred
    assert e0.tags == ("jhack", "fire")
    # the initial update_status has been marked as deferred and tagged with jhack+fire

    # we re-emit it and re-defer it when running start
    proc.process(
        "unit-traefik-0: 12:04:19 DEBUG unit.traefik/0.juju-log Re-emitting deferred event <UpdateStatusEvent via TraefikIngressCharm/on/update_status[318]>."
    )

    e1 = proc._captured_logs[1]
    assert e1.event == "update_status"
    # at this point we think it's consumed, as it's not been re-deferred yet
    assert not proc._currently_deferred
    assert e1.deferred == DeferralStatus.reemitted
    assert not e1.tags

    # now we see the re-deferral
    proc.process(
        "unit-traefik-0: 12:04:19 DEBUG unit.traefik/0.juju-log Deferring <UpdateStatusEvent via TraefikIngressCharm/on/update_status[318]>."
    )
    assert e1.deferred == DeferralStatus.bounced
    assert not e1.tags

    # and now we see what event we've been processing now
    proc.process(
        "unit-traefik-0: 12:04:19 INFO unit.traefik/0.juju-log Emitting Juju event start."
    )
    e1 = proc._captured_logs[2]
    assert e1.event == "start"


def test_tail_with_file_input():
    tail_charms(
        files=[
            mocks_dir / "real-prom-cropped-for-interlace.txt",
            mocks_dir / "real-trfk-cropped-for-interlace.txt",
        ]
    )


def test_tail_with_file_input_and_output(tmp_path):
    tail_charms(
        files=[
            mocks_dir / "real-prom-cropped-for-interlace.txt",
            mocks_dir / "real-trfk-cropped-for-interlace.txt",
        ],
        output=str(tmp_path),
    )


@pytest.mark.parametrize(
    "log",
    (
        "unit-trfk-0: 10:08:01 DEBUG unit.trfk/0.juju-log Emitting Juju event leader_elected.",
        "unit-postgresql-11: 2025-06-16 11:18:48 DEBUG unit.postgresql/11.juju-log restart:15: root:Emitting Juju event restart_relation_joined.",
    ),
)
def test_match_emitted(log):
    with mock_uniter_events_only(False):
        proc = Processor([])
        msg = proc.process(log)
        assert msg


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
    with mock_uniter_events_only(False):
        proc = Processor(targets=[], event_filter_re=(re.compile(pattern) if pattern else None))
        msg = proc.process(log)
    if match:
        assert msg
    else:
        assert msg is None


def test_machine_log_with_subordinates():
    with mock_uniter_events_only(False):
        proc = tail_charms(length=30, replay=True, files=[str(mocks_dir / "machine-sub-log.txt")])

    units = {log.unit for log in proc._captured_logs}
    assert len(units) == 4

    assert [log.event for log in proc._captured_logs if log.unit == "mongodb/0"] == [
        "testing_mock",
    ]  # mock event we added
    assert [log.event for log in proc._captured_logs if log.unit == "ceil/0"] == [
        "testing_mock"
    ]  # mock event we added
    assert [
        log.event for log in proc._captured_logs if log.unit == "prometheus-node-exporter/0"
    ] == [
        "install",
        "juju_info_relation_created",
        "leader_elected",
        "config_changed",
        "start",
        "juju_info_relation_joined",
        "juju_info_relation_changed",
    ]
    assert [log.event for log in proc._captured_logs if log.unit == "ubuntu/0"] == [
        "install",
        "leader_elected",
        "config_changed",
        "start",
        "update_status",
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
    with mock_uniter_events_only(False):
        p = Processor(["prom/1"])
        p.process(line)
    assert [log for log in p._captured_logs if log.unit == "prom/1"]


def test_borky_trfk_log_defer():
    tail_charms(
        length=30,
        replay=True,
        files=[str(mocks_dir / "trfk_mock_bork_defer.txt")],
        show_defer=True,
    )


def test_trace_ids_relation_evt():
    with mock_uniter_events_only(False):
        p = Processor(["prom/1"], show_trace_ids=True)
        for line in (
            "prom-1: 12:56:44 DEBUG unit.prom/1.juju-log ingress:1: Starting root trace with id='12312321412412312321'.",
            "prom-1: 12:56:44 DEBUG unit.prom/1.juju-log ingress:1: Emitting custom event "
            "<IngressPerUnitReadyForUnitEvent via A/B[ingress]"
            "/on/ready_for_unit[14]>.",
        ):
            p.process(line)
    evt = [log for log in p._captured_logs if log.unit == "prom/1"][0]
    assert evt.trace_id == "12312321412412312321"


def test_trace_ids_no_relation_evt():
    with mock_uniter_events_only(False):
        p = Processor(["prom/1"], show_trace_ids=True)
        for line in (
            "prom-1: 12:56:44 DEBUG unit.prom/1.juju-log Starting root trace with id='12312321412412312321'.",
            "prom-1: 12:56:44 DEBUG unit.prom/1.juju-log Emitting custom event "
            "<IngressPerUnitReadyForUnitEvent via A/B[ingress]"
            "/on/ready_for_unit[14]>.",
        ):
            p.process(line)
    evt = [log for log in p._captured_logs if log.unit == "prom/1"][0]
    assert evt.trace_id == "12312321412412312321"


def test_event_failed():
    with mock_uniter_events_only(True):
        p = Processor(["parca/1"], show_trace_ids=True)
    for line in (
        'unit-parca-1: 12:30:58 INFO juju.worker.uniter.operation ran "update-status" hook '
        "(via hook dispatching script: dispatch)",
        'unit-parca-1: 12:31:01 ERROR juju.worker.uniter.operation hook "update-status" '
        "(via hook dispatching script: dispatch) failed: exit status 444",
    ):
        p.process(line)

    captured = [log for log in p._captured_logs if log.unit == "parca/1"]
    assert len(captured) == 1
    evt = captured[0]
    assert evt.tags == ("failed",)
    assert evt.exit_code == 444


def test_event_failed2():
    with mock_uniter_events_only(False):
        p = Processor([], show_trace_ids=True)
        for line in (
            "unit-parca-0: 15:01:38 DEBUG unit.parca/0.juju-log profiling-endpoint:2: Emitting Juju event profiling_endpoint_relation_changed.",
            "unit-parca-0: 15:01:49 DEBUG unit.parca/0.juju-log profiling-endpoint:2: Emitting Juju event profiling_endpoint_relation_created.",
            "unit-parca-0: 15:01:38 DEBUG unit.parca/0.juju-log profiling-endpoint:2: Emitting Juju event profiling_endpoint_relation_joined.",
            'unit-parca-0: 15:01:49 ERROR juju.worker.uniter.operation hook "profiling-endpoint-relation-created" (via hook dispatching script: dispatch) failed: exit status 1',
        ):
            p.process(line)

    captured = p._captured_logs
    assert len(captured) == 3
    assert [e.tags for e in captured] == [(), ("failed",), ()]
    assert [e.exit_code for e in captured] == [0, 1, 0]


def test_machine_event_logs():
    with mock_uniter_events_only(False):
        p = Processor([], show_trace_ids=True)
        for line in (
            "unit-postgresql-1: 09:25:36 DEBUG unit.postgresql/1.juju-log root:Emitting Juju event leader_settings_changed.",
            "unit-postgresql-0: 2025-06-05 13:16:39 DEBUG unit.postgresql/0.juju-log refresh-v-three:0: root:Emitting Juju event refresh_v_three_relation_created.",
        ):
            p.process(line)

    captured = p._captured_logs
    assert len(captured) == 2


def test_machine_pgql_logs():
    with patch(
        "jhack.utils.tail_charms.tail_charms._get_debug_log",
        wraps=lambda _: _fake_log_proc("real-pgql-machine-log"),
    ):
        processor = tail_charms(
            watch=False,
        )

    assert [log.event for log in processor._captured_logs] == [
        "archive_storage_attached",
        "data_storage_attached",
        "temp_storage_attached",
        "logs_storage_attached",
        "install",
        "restart_relation_created",
        "database_peers_relation_created",
        "refresh_v_three_relation_created",
        "leader_elected",
        "config_changed",
        "start",
        "refresh_v_three_relation_changed",
        "database_peers_relation_changed",
        "update_status",
        "archive_storage_attached",
        "data_storage_attached",
        "temp_storage_attached",
        "logs_storage_attached",
        "install",
        "restart_relation_created",
        "database_peers_relation_created",
        "refresh_v_three_relation_created",
        "leader_elected",
        "config_changed",
        "start",
        "refresh_v_three_relation_changed",
        "database_peers_relation_changed",
        "update_status",
    ]
