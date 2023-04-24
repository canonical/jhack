import json as _json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from jhack.utils.show_relation import _sync_show_relation, get_content

sys.path.append(str(Path(__file__).parent.parent.parent))


def fake_juju_status(app_name, model=None, json: bool = False):
    ext = ".jsn" if json else ".txt"
    if app_name == "ceilometer":
        source = "ceil_status" + ext
    elif app_name == "mongodb":
        source = "mongo_status" + ext
    else:
        raise ValueError(app_name)
    mock_file = Path(__file__).parent / "show_relation_mocks" / "machine" / source
    raw = mock_file.read_text()

    if json:
        return _json.loads(raw)
    return raw


def fake_juju_show_unit(app_name, model=None):
    if app_name == "ceilometer/0":
        source = "ceil0_show.txt"
    elif app_name == "mongodb/1":
        source = "mongo0_show.txt"
    else:
        raise ValueError(app_name)
    mock_file = Path(__file__).parent / "show_relation_mocks" / "machine" / source
    return mock_file.read_text()


@pytest.fixture(autouse=True)
def mock_stdout():
    with patch("jhack.utils.show_relation._juju_status", wraps=fake_juju_status):
        with patch("jhack.utils.show_relation._show_unit", wraps=fake_juju_show_unit):
            yield


def test_show_unit_works():
    _sync_show_relation("ceilometer:shared-db", "mongodb:database")


def test_databag_shape_ceil():
    content = get_content("ceilometer:shared-db", "mongodb:database", False)
    assert content.app_name == "ceilometer"
    assert content.endpoint == "shared-db"
    assert content.application_data == {}
    assert content.units_data == {0: {"ceilometer_database": "ceilometer"}}
    assert content.meta.leader_id == 0


def test_databag_shape_mongo():
    content = get_content("mongodb:database", "ceilometer:shared-db", False)
    assert content.app_name == "mongodb"
    assert content.endpoint == "database"
    assert content.application_data == {}
    assert (
        content.units_data
        == {
            1: {
                "hostname": "10.1.70.128",
                "port": "27017",
                "type": "database",
                "version": "3.6.8",
            }
        }
        != {0: {"ceilometer_database": "ceilometer"}}
    )
    assert content.meta.leader_id == 1
