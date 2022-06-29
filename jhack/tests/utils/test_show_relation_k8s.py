import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).parent.parent.parent))

import pytest

from jhack.utils.show_relation import sync_show_relation


def fake_juju_status(app_name, model=None):
    if app_name == 'traefik-k8s':
        source = 'traefik_status.txt'
    elif app_name == 'prometheus-k8s':
        source = 'prom_status.txt'
    elif app_name == '':
        source = 'full_status.txt'
    else:
        raise ValueError(app_name)
    mock_file = Path(__file__).parent / 'show_relation_mocks' / 'k8s' / source
    return mock_file.read_text()


def fake_juju_show_unit(app_name, model=None):
    if app_name == 'traefik-k8s/0':
        source = 'traefik0_show.txt'
    elif app_name == 'prometheus-k8s/0':
        source = 'prom0_show.txt'
    elif app_name == 'prometheus-k8s/1':
        source = 'prom1_show.txt'
    else:
        raise ValueError(app_name)
    mock_file = Path(__file__).parent / 'show_relation_mocks' / 'k8s' / source
    return mock_file.read_text()


@pytest.fixture(autouse=True)
def mock_stdout():
    with patch("utils.show_relation._juju_status", wraps=fake_juju_status) as mock_status:
        with patch("utils.show_relation._show_unit", wraps=fake_juju_show_unit) as mock_show_unit:
            yield


@pytest.mark.parametrize('ep1, ep2, n', (
        ("traefik-k8s:ingress-per-unit", "prometheus-k8s:ingress", None),
        ("traefik-k8s/0:ingress-per-unit", "prometheus-k8s:ingress", None),
        ("traefik-k8s/0:ingress-per-unit", "prometheus-k8s/0:ingress", None),
        ("traefik-k8s:ingress-per-unit", "prometheus-k8s/0:ingress", None),
        ("prometheus-k8s/0:prometheus-peers", None, None),
        ("prometheus-k8s:prometheus-peers", None, None),
        (None, None, 0),
        (None, None, 1),
))
def test_show_unit_works(ep1, ep2, n):
    sync_show_relation(endpoint1=ep1, endpoint2=ep2,
                       n=n, model=None, show_juju_keys=False,
                       hide_empty_databags=False)

