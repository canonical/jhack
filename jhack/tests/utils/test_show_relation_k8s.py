import json as json_
import sys
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

sys.path.append(str(Path(__file__).parent.parent.parent))

import pytest

from jhack.utils.show_relation import _sync_show_relation, get_interface


def fake_juju_status(model=None, json: bool = False):
    ext = ".json" if json else ".txt"
    source = "full_status" + ext
    mock_file = Path(__file__).parent / "show_relation_mocks" / "k8s" / source
    raw = mock_file.read_text()
    if json:
        return json_.loads(raw)
    return raw


def fake_juju_show_unit(app_name, model=None):
    source = f"{app_name.replace('/','')}_show.txt"
    mock_file = Path(__file__).parent / "show_relation_mocks" / "k8s" / source
    if not mock_file.exists():
        raise ValueError(app_name)
    return mock_file.read_text()


@pytest.fixture(autouse=True)
def mock_stdout():
    with patch("jhack.utils.show_relation._juju_status", wraps=fake_juju_status):
        with patch("jhack.utils.show_relation._show_unit", wraps=fake_juju_show_unit):
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


@pytest.mark.parametrize(
    "app_name, relation_name, other_app_name, other_relation_name, expected_interface_name",
    (
        ("postgresql", "database", "kratos", "pg-database", "postgresql_client"),
        (
            "postgresql",
            "database-peers",
            "postgresql",
            "database-peers",
            "postgresql_peers",
        ),
        ("postgresql", "restart", "postgresql", "restart", "rolling_op"),
    ),
)
def test_intf_re(
    app_name,
    relation_name,
    other_app_name,
    other_relation_name,
    expected_interface_name,
):
    status = dedent(
        """
    Model   Controller  Cloud/Region        Version  SLA          Timestamp
    kratos  micro       microk8s/localhost  2.9.34   unsupported  14:43:53-04:00


    App             Version  Status  Scale  Charm           Channel  Rev  Address         Exposed  Message
    kratos                   active      1  kratos                     2  10.152.183.124  no
    postgresql           active      1  postgresql  edge      25  10.152.183.219  no       Primary

    Unit               Workload  Agent  Address     Ports              Message
    kratos/0*          active    idle   10.1.64.94  4434/TCP,4433/TCP
    postgresql/0*  active    idle   10.1.64.89                     Primary

    Relation provider              Requirer                       Interface          Type     Message
    postgresql:database        kratos:pg-database             postgresql_client  regular
    postgresql:database-peers  postgresql:database-peers  postgresql_peers   peer
    postgresql:restart         postgresql:restart         rolling_op         peer
    """
    )

    interface = get_interface(
        status,
        app_name=app_name,
        relation_name=relation_name,
        other_app_name=other_app_name,
        other_relation_name=other_relation_name,
    )

    assert interface == expected_interface_name
