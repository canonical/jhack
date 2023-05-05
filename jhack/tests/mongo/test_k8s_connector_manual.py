from jhack.mongo.mongo import K8sConnector


def test_k8s_connector():
    connector = K8sConnector()
    query = 'db.relations.find({"key": "loki:logging"}).pretty()'
    val = connector.query(query)
    assert val
