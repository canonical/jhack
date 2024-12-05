from ops import CharmBase
from scenario import Context, State

from jhack.scenario.integrations.darkroom import Darkroom


class MyCharm(CharmBase):
    META = {"name": "joseph", "requires": {"foo": {"interface": "bar"}}}


def test_attach():
    Darkroom.uninstall()  # ensure any previous run did not pollute Context.__init__

    logs = []
    Darkroom().attach(lambda e, s: logs.append((e, s)))
    c = Context(MyCharm, meta=MyCharm.META)
    c.run(c.on.start(), State())

    assert len(logs) == 1
    assert logs[0][0].name == "start"
