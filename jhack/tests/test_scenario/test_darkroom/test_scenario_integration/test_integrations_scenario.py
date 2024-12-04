import ops
import pytest
import scenario
import yaml
from ops import BlockedStatus, CharmBase, WaitingStatus
from ops.testing import Harness
from scenario import Model

from jhack.scenario.integrations.darkroom import Darkroom, ops_port_to_scenario


class MyCharm(CharmBase):
    META = {"name": "joseph"}


@pytest.fixture
def harness():
    return Harness(MyCharm, meta=yaml.safe_dump(MyCharm.META))


def test_base(harness):
    harness.begin()
    Darkroom().capture(harness.model._backend)


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize("model_name", ("foo", "bar-baz"))
@pytest.mark.parametrize("model_uuid", ("qux", "fiz"))
def test_static_attributes(harness, leader, model_name, model_uuid):
    harness.set_model_info(model_name, model_uuid)
    harness.begin()
    harness.charm.unit.set_workload_version("42.42")
    harness.set_leader(leader)

    state = Darkroom().capture(harness.model._backend)

    assert state.leader is leader
    assert state.model == Model(name=model_name, uuid=model_uuid, type="lxd")
    assert state.workload_version == "42.42"


def test_status(harness):
    harness.begin()
    harness.set_leader(True)  # so we can set app status
    harness.charm.app.status = BlockedStatus("foo")
    harness.charm.unit.status = WaitingStatus("hol' up")

    state = Darkroom().capture(harness.model._backend)

    assert state.unit_status == WaitingStatus("hol' up")
    assert state.app_status == BlockedStatus("foo")


@pytest.mark.parametrize(
    "ports",
    (
        [
            ops.Port("tcp", 2032),
            ops.Port("udp", 2033),
        ],
        [
            ops.Port("tcp", 2032),
            ops.Port("tcp", 2035),
            ops.Port("icmp", None),
        ],
    ),
)
def test_opened_ports(harness, ports):
    harness.begin()
    harness.charm.unit.set_ports(*ports)
    state = Darkroom().capture(harness.model._backend)
    assert set(state.opened_ports) == set(map(ops_port_to_scenario, ports))


# todo add tests for all other State components
