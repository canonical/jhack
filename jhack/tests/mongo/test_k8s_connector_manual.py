from jhack.mongo.mongo import K8sConnector


def test_k8s_connector_base():
    connector = K8sConnector()
    query = r"db.relations.find()"
    val = connector.get_one(query)
    assert val


def test_k8s_connector_relation():
    connector = K8sConnector()
    query = r'db.relations.find({"key": "grafana:catalogue catalogue:catalogue"})'
    val = connector.get_one(query)
    assert val
