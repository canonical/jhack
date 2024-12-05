import dataclasses


def test_install():
    from jhack.scenario.integrations.darkroom import Darkroom

    logs = []
    Darkroom.install(logs)

    from ops import CharmBase
    from scenario import Context, Relation, State

    class MyCharm(CharmBase):
        META = {"name": "joseph", "requires": {"foo": {"interface": "bar"}}}

    # unique states
    s1, s2, s3, s4, s5, s6, s7 = [State() for _ in range(7)]

    c = Context(MyCharm, meta=MyCharm.META)
    c.run(c.on.start(), s1)
    c.run(c.on.install(), s2)

    c = Context(MyCharm, meta=MyCharm.META)
    c.run(c.on.start(), s3)
    c.run(c.on.update_status(), s4)

    c = Context(MyCharm, meta=MyCharm.META)
    c.run(c.on.start(), s5)
    c.run(c.on.install(), s6)
    foo = Relation("foo")
    s7_mod = dataclasses.replace(s7, relations=[foo])
    c.run(c.on.relation_changed(foo), s7_mod)

    assert len(logs) == 3
    assert [len(x) for x in logs] == [2, 2, 3]

    assert [s[0].name for s in logs[0]] == ["start", "install"]
    assert [s[0].name for s in logs[1]] == ["start", "update_status"]
    assert [s[0].name for s in logs[2]] == ["start", "install", "foo_relation_changed"]

    # states-in == states-out
    assert [s[1] for s in logs[0]] == [s1, s2]
    assert [s[1] for s in logs[1]] == [s3, s4]
    assert [s[1] for s in logs[2]] == [s5, s6, s7_mod]
