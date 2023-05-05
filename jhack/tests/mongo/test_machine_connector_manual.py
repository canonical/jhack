from jhack.mongo.mongo import MachineConnector


def test_machine_connector_base():
    connector = MachineConnector("lxdcloud")
    query = r"db.relations.find()"
    val = connector.get_many(query)
    assert val


def test_machine_connector():
    connector = MachineConnector("lxdcloud")
    query = 'db.relations.find({"key": "kafka:cluster"})'
    val = connector.get_one(query)
    assert val
