from jhack.mongo.mongo import MachineConnector


def test_machine_connector_base():
    connector = MachineConnector("lxdcloud")
    query = r"db.relations"
    val = connector.get(query, n=1)
    assert len(val) == 1


def test_machine_connector():
    connector = MachineConnector("lxdcloud")
    query = 'db.relations'
    val = connector.get(query, query_filter='{"key": "kafka:cluster"}')
    assert len(val) == 1
