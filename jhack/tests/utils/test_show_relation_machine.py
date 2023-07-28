import json as json_
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from jhack.utils.show_relation import _sync_show_relation

sys.path.append(str(Path(__file__).parent.parent.parent))


def fake_juju_status(model=None, json: bool = False):
    ext = ".json" if json else ".txt"
    source = "full_status" + ext
    mock_file = Path(__file__).parent / "show_relation_mocks" / "machine" / source
    raw = mock_file.read_text()
    if json:
        return json_.loads(raw)
    return raw


def fake_juju_show_unit(app_name, model=None, related_to=None, endpoint=None):
    if app_name == "kafka/0":
        source = "kafka0_show.txt"
    elif app_name == "zookeeper/0":
        source = "zookeeper0_show.txt"
    else:
        raise ValueError(app_name)
    mock_file = Path(__file__).parent / "show_relation_mocks" / "machine" / source
    return yaml.safe_load(mock_file.read_text())


@pytest.fixture(autouse=True)
def mock_stdout():
    with patch("jhack.utils.show_relation._juju_status", wraps=fake_juju_status):
        with patch("jhack.utils.show_relation._show_unit", wraps=fake_juju_show_unit):
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
