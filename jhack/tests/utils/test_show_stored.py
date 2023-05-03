from pathlib import Path

import pytest

from jhack.utils.show_stored import StorageView

mocks = Path(__file__).parent / "show_stored_mocks"


@pytest.mark.parametrize("mock_db_path", (mocks / "trfk-0.dbdump",))
def test_state_view_db_file(mock_db_path):
    state_view = StorageView(live=False)
    state_view.render(mock_db_path)


@pytest.mark.parametrize(
    "snapshot, expected",
    (
        ("foo/bar[baz]", "foo.baz"),
        ("foo/bar/qux[baz]", "foo.bar.baz"),
    ),
)
def test_state_view_db_file_other(snapshot, expected):
    state_view = StorageView(live=False)
    assert state_view._get_name(snapshot) == expected
