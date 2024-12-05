import json as json_
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from jhack.helpers import JujuVersion, LibInfo
from jhack.utils.list_endpoints import _list_endpoints

sys.path.append(str(Path(__file__).parent.parent.parent))


def fake_juju_status(model=None, json: bool = False):
    ext = ".json" if json else ".txt"
    source = "full_status" + ext
    mock_file = Path(__file__).parent / "list_endpoints_mocks" / source
    raw = mock_file.read_text()
    if json:
        return json_.loads(raw)
    return raw


def fake_fetch_file(unit, remote_path, model):
    if unit == "keystone/0":
        source = "keystone_metadata.yaml"
    else:
        raise ValueError(unit)
    mock_file = Path(__file__).parent / "list_endpoints_mocks" / source
    return mock_file.read_text()


def fake_libinfo(*args, **kwargs):
    # owner, version, lib_name, revision
    return [
        LibInfo("keystone", "0", "hacluster", "4"),
    ]


@pytest.fixture(autouse=True)
def mock_stdout():
    with (
        patch("jhack.utils.helpers.gather_endpoints.juju_status", wraps=fake_juju_status),
        patch("jhack.utils.helpers.gather_endpoints.fetch_file", wraps=fake_fetch_file),
        patch(
            "jhack.utils.list_endpoints.juju_version",
            wraps=lambda: JujuVersion((3, 2), ""),
        ),
        patch("jhack.utils.list_endpoints.get_libinfo", wraps=fake_libinfo),
    ):
        yield


@pytest.mark.parametrize("show_versions", (True, False))
def test_list_endpoints(show_versions):
    _list_endpoints("keystone", show_versions=show_versions)
