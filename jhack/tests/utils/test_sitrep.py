from jhack.utils.sitrep import _Status, _StatusTree


def test_tree_gen():
    statuses = [
        _Status({"name": "blocked", "message": "foo"}),
        _Status({"name": "active", "message": "[a] bar"}),
        _Status({"name": "active", "message": "[a.b] baz"}),
        _Status({"name": "active", "message": "[a.b] qux"}),
        _Status({"name": "active", "message": "[a.c] bor"}),
        _Status({"name": "active", "message": "[a.c.lob.panda] bor"}),
        _Status({"name": "active", "message": "[a.c.lob.panda.lost.in.space.x] bor"}),
        _Status({"name": "active", "message": "[d] bor"}),
        _Status({"name": "active", "message": "[d.e] ked"}),
    ]

    tree = _StatusTree(statuses)

    raw = tree._tree
    assert raw[("",)][0].message == "foo"
    assert raw[("a",)][0].message == "bar"
    assert raw[("a", "b")][0].message == "baz"
    assert raw[("a", "b")][1].message == "qux"
    assert raw[("a", "c")][0].message == "bor"
    assert raw[("d",)][0].message == "bor"
    assert raw[("d", "e")][0].message == "ked"
