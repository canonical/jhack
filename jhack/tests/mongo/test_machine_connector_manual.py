from jhack.mongo.mongo import MachineConnector


def test_machine_connector_base():
    connector = MachineConnector("lxdcloud")
    query = r"db.relations.find()"
    val = connector.query(query)
    assert val


def test_machine_connector():
    connector = MachineConnector("lxdcloud")
    query = 'db.relations.find({"key": "kafka:cluster"})'
    val = connector.query(query)
    assert val
