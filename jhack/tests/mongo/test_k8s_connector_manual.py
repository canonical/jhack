from jhack.mongo.mongo import K8sConnector


def test_k8s_connector_base():
    connector = K8sConnector()
    query = r"db.relations"
    val = connector.get(query, n=1)
    assert len(val) == 1


def test_k8s_connector_get_all():
    connector = K8sConnector()
    query = r"db.relations"
    val = connector.get(query)
    assert len(val) == 26


def test_k8s_connector_relation():
    connector = K8sConnector()
    query = r'db.relations'
    val = connector.get(query, query_filter='{"key": "grafana:catalogue catalogue:catalogue"}')
    assert len(val) == 1