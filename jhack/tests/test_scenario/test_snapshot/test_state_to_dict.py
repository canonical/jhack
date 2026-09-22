import json

from scenario import Container, Mount, Network, State

from jhack.scenario.state_to_dict import state_to_dict


def test_state_to_dict_networks():
    state = State(networks={Network("juju-info")})
    result = state_to_dict(state)
    json.dumps(result)
    assert len(result["networks"]) == 1


def test_state_to_dict_container_basic():
    state = State(containers=[Container("redis", can_connect=True)])
    result = state_to_dict(state)
    json.dumps(result)
    assert result["containers"][0]["name"] == "redis"
    assert result["containers"][0]["can_connect"] is True


def test_state_to_dict_container_mounts():
    state = State(
        containers=[
            Container(
                "redis",
                can_connect=True,
                mounts={"data": Mount(location="/var/lib/redis", source="/tmp/redis")},
            )
        ]
    )
    result = state_to_dict(state)
    json.dumps(result)
    mounts = result["containers"][0]["mounts"]
    assert mounts == {"data": {"location": "/var/lib/redis", "source": "/tmp/redis"}}
