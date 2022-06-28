from pathlib import Path
from unittest.mock import patch

import pytest
from unittest import mock

from utils.show_relation import sync_show_relation


def fake_juju_status(app_name):
    if app_name == 'traefik-k8s':
        source = 'traefik_status.txt'
    elif app_name == 'prometheus-k8s':
        source = 'prom_status.txt'
    else:
        raise ValueError(app_name)
    mock_file = Path(__file__).parent / 'show_relation_mocks' / 'k8s' / source
    return mock_file.read_text()


def fake_juju_show_unit(app_name):
    if app_name == 'traefik-k8s/0':
        source = 'traefik0_show.txt'
    elif app_name == 'prometheus-k8s/0':
        source = 'prom0_show.txt'
    else:
        raise ValueError(app_name)
    mock_file = Path(__file__).parent / 'show_relation_mocks' / 'k8s' / source
    return mock_file.read_text()


@pytest.fixture(autouse=True)
def mock_stdout():
    with patch("utils.show_relation._juju_status", wraps=fake_juju_status) as mock_status:
        with patch("utils.show_relation._show_unit", wraps=fake_juju_show_unit) as mock_show_unit:
            yield


def test_show_unit_works():
    sync_show_relation("traefik-k8s:ingress-per-unit", "prometheus-k8s:ingress")
