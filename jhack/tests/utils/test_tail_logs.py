from unittest.mock import MagicMock, patch

import pytest

from jhack.helpers import Target
from jhack.utils.tail_logs import _collect_log_sources, _Service, _parse_sources


@pytest.mark.parametrize(
    "found, sources, expected",
    (
        (
            ({"container1": ("svc1", "svc2")}),
            ("container1",),
            ({"container1": ("svc1", "svc2")}),
        ),
        (
            ({"container1": ("svc1", "svc2")}),
            ("container1", "container2"),
            ({"container1": ("svc1", "svc2")}),
        ),
        (
            ({"container1": ("svc1", "svc2"), "container2": ("svc3", "svc4")}),
            ("container1", "container2"),
            ({"container1": ("svc1", "svc2"), "container2": ("svc3", "svc4")}),
        ),
        (
            ({"container1": ("svc1", "svc2"), "container2": ("svc3", "svc4")}),
            ("container1", "container2:svc3"),
            ({"container1": ("svc1", "svc2"), "container2": ("svc3",)}),
        ),
        (
            ({"container1": ("svc1", "svc2"), "container2": ("svc3", "svc4")}),
            ("container1:svc2", "container2:svc3"),
            ({"container1": ("svc2",), "container2": ("svc3",)}),
        ),
        (
            ({"container1": ("svc1", "svc2"), "container2": ("svc3", "svc4")}),
            ("container1:svc2", "container2:nonexistingsvc"),
            ({"container1": ("svc2",)}),
        ),
    ),
)
def test_collect_sources(found, sources, expected):
    def get_svc_mock(_, container):
        return tuple(_Service(name, "foo", True) for name in found[container])

    def get_containers_mock(_):
        return tuple(found)

    with patch("jhack.utils.tail_logs.get_services", new=get_svc_mock):
        with patch(
            "jhack.utils.tail_logs.get_container_names", new=get_containers_mock
        ):

            out = _collect_log_sources(Target("foo", 1), _parse_sources(sources))
            assert {c: tuple(s.name for s in ss) for c, ss in out.items()} == expected


@pytest.mark.parametrize(
    "found, sources, expected",
    (
        (
            ({"container1": ("svc1", "svc2"), "container2": ("svc3", "svc4")}),
            ("container3",),
            ({}),
        ),
        (
            ({"container1": ("svc1", "svc2"), "container2": ("svc3", "svc4")}),
            ("container3:nonexistingsvc",),
            ({}),
        ),
    ),
)
def test_collect_sources_fail(found, sources, expected):
    def get_svc_mock(_, container):
        return tuple(_Service(name, "foo", True) for name in found[container])

    def get_containers_mock(_):
        return tuple(found)

    with patch("jhack.utils.tail_logs.get_services", new=get_svc_mock):
        with patch(
            "jhack.utils.tail_logs.get_container_names", new=get_containers_mock
        ):
            with pytest.raises(SystemExit):
                _collect_log_sources(Target("foo", 1), _parse_sources(sources))


def test_collect_sources_warns_if_unexpected_container(caplog):
    found = {"container1": ("svc1", "svc2"), "container2": ("svc3",)}

    def get_svc_mock(_, container):
        return tuple(_Service(name, "foo", True) for name in found[container])

    def get_containers_mock(_):
        return tuple(found)

    with patch("jhack.utils.tail_logs.get_services", new=get_svc_mock):
        with patch(
            "jhack.utils.tail_logs.get_container_names", new=get_containers_mock
        ):
            _collect_log_sources(
                Target("foo", 1), _parse_sources(["container3", "container1"])
            )

    assert "focused container 'container3' not found in 'foo/1'" in caplog.messages


def test_collect_sources_warns_if_unexpected_service(caplog):
    found = {"container1": ("svc1", "svc2"), "container2": ("svc3",)}

    def get_svc_mock(_, container):
        return tuple(_Service(name, "foo", True) for name in found[container])

    def get_containers_mock(_):
        return tuple(found)

    with patch("jhack.utils.tail_logs.get_services", new=get_svc_mock):
        with patch(
            "jhack.utils.tail_logs.get_container_names", new=get_containers_mock
        ):
            _collect_log_sources(
                Target("foo", 1),
                _parse_sources(["container1:nonexistentservice", "container2"]),
            )

    assert (
        "focused service name 'nonexistentservice' not found in container 'container1'"
        in caplog.messages
    )


def test_collect_sources_warns_if_inconsistent_sources_defined(caplog):
    found = {"container1": ("svc1", "svc2"), "container2": ("svc3",)}

    def get_svc_mock(_, container):
        return tuple(_Service(name, "foo", True) for name in found[container])

    def get_containers_mock(_):
        return tuple(found)

    with patch("jhack.utils.tail_logs.get_services", new=get_svc_mock):
        with patch(
            "jhack.utils.tail_logs.get_container_names", new=get_containers_mock
        ):
            _collect_log_sources(
                Target("foo", 1),
                _parse_sources(["container1:nonexistentservice", "container1"]),
            )

    assert (
        "inconsistent focus definition: container1 has multiple overlapping constraints (['nonexistentservice', None])"
        in caplog.messages
    )
