def test_install():
    from jhack.scenario.integrations.darkroom import Darkroom

    logs = []
    Darkroom.install(logs)

    import yaml
    from ops import CharmBase
    from ops.testing import Harness

    class MyCharm(CharmBase):
        META = {"name": "joseph", "requires": {"foo": {"interface": "bar"}}}

    h = Harness(MyCharm, meta=yaml.safe_dump(MyCharm.META))
    h.begin_with_initial_hooks()

    h = Harness(MyCharm, meta=yaml.safe_dump(MyCharm.META))
    h.begin_with_initial_hooks()
    h.add_relation("foo", "remote")

    h = Harness(MyCharm, meta=yaml.safe_dump(MyCharm.META))
    h.begin_with_initial_hooks()
    h.add_relation("foo", "remote2")

    assert len(logs) == 3
    assert [len(x) for x in logs] == [4, 5, 5]
    assert logs[0][1][0].name == "leader_settings_changed"
    assert logs[1][-1][0].name == "foo_relation_created"
    assert logs[2][-1][0].name == "foo_relation_created"
