import pytest

from jhack import utils
from jhack.tests.utils.test_show_relation.utils import load_mocks
from jhack.utils.show_relation import _sync_show_relation, get_databag_content


@pytest.fixture(autouse=True, scope="module")
def mock_all():
    with load_mocks("cmrs"):
        yield


@pytest.mark.parametrize(
    "ep1, ep2, n",
    (
        ("trfk:ingress", "alertmanager:ingress", None),
        ("trfk/0:ingress", "alertmanager:ingress", None),
        ("trfk/0:ingress", "alertmanager/0:ingress", None),
        ("trfk:ingress", "alertmanager/0:ingress", None),
        (None, None, 0),
    ),
)
def test_show_unit_works(ep1, ep2, n):
    _sync_show_relation(endpoint1=ep1, endpoint2=ep2, n=n)


def test_get_databag_content_remote():
    db_contents = get_databag_content(
        status=utils.show_relation._juju_status("clite", json=True),
        units=["alertmanager/0"],
        remote_unit="trfk/0",
        endpoint="ingress",
        remote_endpoint="ingress",
        model="clite",
    )

    assert db_contents.url == "alertmanager:ingress"
    assert db_contents.model == "clite"
    assert db_contents.relation_id == 0
    assert db_contents.units_data == {0: {}}
    # this is alertmanager's application databag in the ingress relation
    assert (
        db_contents.application_data["host"]
        == "alertmanager-0.alertmanager-endpoints.clite.svc.cluster.local"
    )
