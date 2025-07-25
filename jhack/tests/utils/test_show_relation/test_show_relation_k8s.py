from jhack.tests.utils.test_show_relation.utils import load_mocks

import pytest

from jhack.utils.show_relation import _sync_show_relation


@pytest.fixture(autouse=True, scope="module")
def mock_all():
    with load_mocks("k8s"):
        yield


@pytest.mark.parametrize(
    "ep1, ep2, n",
    (
        ("traefik:ingress-per-unit", "prometheus:ingress", None),
        ("traefik/0:ingress-per-unit", "prometheus:ingress", None),
        ("traefik/0:ingress-per-unit", "prometheus/0:ingress", None),
        ("traefik:ingress-per-unit", "prometheus/0:ingress", None),
        ("prometheus/0:prometheus-peers", None, None),
        ("prometheus:prometheus-peers", None, None),
        (None, None, 0),
        (None, None, 1),
    ),
)
def test_show_unit_works(ep1, ep2, n):
    _sync_show_relation(endpoint1=ep1, endpoint2=ep2, n=n)
