import yaml
from ops import CharmBase
from ops.testing import Harness

from jhack.scenario.integrations.darkroom import Darkroom


class MyCharm(CharmBase):
    META = {"name": "joseph", "requires": {"foo": {"interface": "bar"}}}


def test_attach():
    h = Harness(MyCharm, meta=yaml.safe_dump(MyCharm.META))
    logs = []
    Darkroom().attach(lambda e, s: logs.append((e, s)))
    h.begin()
    h.add_relation("foo", "remote")

    assert len(logs) == 1
    assert logs[0][0].name == "foo_relation_created"
