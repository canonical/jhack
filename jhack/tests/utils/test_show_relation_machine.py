import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.append(str(Path(__file__).parent.parent.parent))

from jhack.utils.show_relation import sync_show_relation, get_content


def fake_juju_status(app_name, model=None):
    if app_name == 'ceilometer':
        source = 'ceil_status.txt'
    elif app_name == 'mongo':
        source = 'mongo_status.txt'
    else:
        raise ValueError(app_name)
    mock_file = Path(
        __file__).parent / 'show_relation_mocks' / 'machine' / source
    return mock_file.read_text()


def fake_juju_show_unit(app_name, model=None):
    if app_name == 'ceilometer/0':
        source = 'ceil0_show.txt'
    elif app_name == 'mongo/0':
        source = 'mongo0_show.txt'
    else:
        raise ValueError(app_name)
    mock_file = Path(
        __file__).parent / 'show_relation_mocks' / 'machine' / source
    return mock_file.read_text()


@pytest.fixture(autouse=True)
def mock_stdout():
    with patch("utils.show_relation._juju_status",
               wraps=fake_juju_status) as mock_status:
        with patch("utils.show_relation._show_unit",
                   wraps=fake_juju_show_unit) as mock_show_unit:
            yield


def test_show_unit_works():
    sync_show_relation("ceilometer:shared-db", "mongo:database",
                       n=None, model=None, show_juju_keys=False,
                       hide_empty_databags=False)


def test_databag_shape_ceil():
    content = get_content("ceilometer:shared-db", "mongo:database", False)
    assert content.app_name == 'ceilometer'
    assert content.endpoint == 'shared-db'
    assert content.application_data == {}
    assert content.units_data == {0: {'ceilometer_database': 'ceilometer'}}
    assert content.meta.leader_id == 0


def test_databag_shape_mongo():
    content = get_content("mongo:database", "ceilometer:shared-db", False)
    assert content.app_name == 'mongo'
    assert content.endpoint == 'database'
    assert content.application_data == {}
    assert content.units_data == {
        0: {'hostname': '10.1.70.128',
            'port': '27017',
            'type': 'database',
            'version': '3.6.8'}} != {
               0: {'ceilometer_database': 'ceilometer'}}
    assert content.meta.leader_id == 0
