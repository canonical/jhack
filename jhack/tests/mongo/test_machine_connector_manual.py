from jhack.mongo.mongo import MachineConnector


def test_k8s_connector():
    connector = MachineConnector()
    query = 'db.relations.find({"key": "kafka:cluster"})'
    val = connector.query(query)
    assert val
