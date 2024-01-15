import pytest
from scenario import (
    Container,
    Network,
    PeerRelation,
    Relation,
    State,
    SubordinateRelation,
)

from jhack.scenario.dict_to_state import dict_to_state
from jhack.scenario.state_to_dict import state_to_dict


@pytest.mark.parametrize(
    "state",
    (
        State(),
        State(leader=True),
        # TODO: support pebble layers
        # State(
        #     containers=[
        #         Container("foo", layers={"foo": pebble.Layer()}, can_connect=True)
        #     ]
        # ),
        State(containers=[Container("foo", can_connect=True)]),
        State(networks=[Network.default("foo")]),
        State(
            relations=[Relation("foo"), PeerRelation("bar"), SubordinateRelation("baz")]
        ),
    ),
)
def test_roundtrip(state):
    roundtripped_state = dict_to_state(state_to_dict(state))
    assert roundtripped_state == state
