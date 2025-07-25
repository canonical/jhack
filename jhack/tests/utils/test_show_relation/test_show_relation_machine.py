import pytest

from jhack.utils.show_relation import _sync_show_relation

from jhack.tests.utils.test_show_relation.utils import load_mocks


@pytest.fixture(autouse=True, scope="module")
def mock_all():
    with load_mocks("machine"):
        yield


@pytest.mark.parametrize(
    "ep1, ep2, n",
    (
        ("kafka:zookeeper", "zookeeper:zookeeper", None),
        ("kafka:zookeeper", "zookeeper/0:zookeeper", None),
        ("kafka/0:zookeeper", "zookeeper/0:zookeeper", None),
        ("kafka/0:cluster", None, None),
        ("zookeeper/0:restart", None, None),
        ("zookeeper:restart", None, None),
        (None, None, 0),
        (None, None, 1),
        (None, None, 2),
        (None, None, 3),
        (None, None, 4),
    ),
)
def test_show_unit_works(ep1, ep2, n):
    _sync_show_relation(endpoint1=ep1, endpoint2=ep2, n=n)
