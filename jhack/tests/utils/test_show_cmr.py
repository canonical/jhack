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
    model_identifier = model.replace(':', '_').replace('/', '_') if model else model
    source = f"full_status_{model_identifier}" + ext
    mock_file = Path(__file__).parent / "show_relation_mocks" / "cmrs" / source
    raw = mock_file.read_text()
    if json:
        return json_.loads(raw)
    return raw


def fake_juju_show_unit(app_name, model=None):
    model_identifier = model.replace(':', '_').replace('/', '_') if model else model
    source = f"{app_name.replace('/','')}_{model_identifier}_show.txt"
    mock_file = Path(__file__).parent / "show_relation_mocks" / "cmrs" / source
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
        ("trfk:ingress", "alertmanager:ingress", None),
        ("trfk/0:ingress", "alertmanager:ingress", None),
        ("trfk/0:ingress", "alertmanager/0:ingress", None),
        ("trfk:ingress", "alertmanager/0:ingress", None),
        (None, None, 0),
    ),
)
def test_show_unit_works(ep1, ep2, n):
    _sync_show_relation(endpoint1=ep1, endpoint2=ep2, n=n)
