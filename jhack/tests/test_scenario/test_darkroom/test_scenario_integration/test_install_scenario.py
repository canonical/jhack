def test_install():
    from jhack.scenario.integrations.darkroom import Darkroom

    l = []
    Darkroom.install(l)

    from ops import CharmBase
    from scenario import Context, State, Relation

    class MyCharm(CharmBase):
        META = {"name": "joseph", "requires": {"foo": {"interface": "bar"}}}

    # unique states
    s1, s2, s3, s4, s5, s6, s7 = [State(unit_id=i) for i in range(7)]

    c = Context(MyCharm, meta=MyCharm.META)
    c.run("start", s1)
    c.run("install", s2)

    c = Context(MyCharm, meta=MyCharm.META)
    c.run("start", s3)
    c.run("update-status", s4)

    c = Context(MyCharm, meta=MyCharm.META)
    c.run("start", s5)
    c.run("install", s6)
    foo = Relation("foo")
    s7_mod = s7.replace(relations=[foo])
    c.run(foo.changed_event, s7_mod)

    assert len(l) == 3
    assert [len(x) for x in l] == [2, 2, 3]

    assert [s[0].name for s in l[0]] == ["start", "install"]
    assert [s[0].name for s in l[1]] == ["start", "update_status"]
    assert [s[0].name for s in l[2]] == ["start", "install", "foo_relation_changed"]

    # states-in == states-out
    assert [s[1] for s in l[0]] == [s1, s2]
    assert [s[1] for s in l[1]] == [s3, s4]
    assert [s[1] for s in l[2]] == [s5, s6, s7_mod]
