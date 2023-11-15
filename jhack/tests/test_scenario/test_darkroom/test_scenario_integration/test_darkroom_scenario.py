import yaml
from ops import CharmBase
from ops.testing import Harness
from scenario import Context, State

from jhack.scenario.integrations.darkroom import Darkroom


class MyCharm(CharmBase):
    META = {"name": "joseph", "requires": {"foo": {"interface": "bar"}}}


def test_attach():
    l = []
    d = Darkroom().attach(lambda e, s: l.append((e, s)))
    c = Context(MyCharm, meta=MyCharm.META)
    c.run("start", State())

    assert len(l) == 1
    assert l[0][0].name == "start"
