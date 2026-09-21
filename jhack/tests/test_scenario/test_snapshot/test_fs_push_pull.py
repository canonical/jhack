from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ops.storage import SQLiteStorage
from scenario import Container, Mount

from jhack.scenario.snapshot import RemoteUnitStateDB, get_container
from jhack.scenario.state_apply import _gather_push_file_calls
from jhack.scenario.utils import JujuUnitName


def _fetch_file(*args, **kwargs):
    local_path = kwargs["local_path"]
    Path(local_path).write_text("hello world")


def _get_plan(*args, **kwargs):
    return {"foo": "bar"}


@patch("jhack.scenario.snapshot.fetch_file", new=_fetch_file)
@patch("jhack.scenario.snapshot.RemotePebbleClient.get_plan", new=_get_plan)
@patch("jhack.scenario.snapshot.RemotePebbleClient.can_connect", return_value=True)
def test_get_container(can_connect):
    tempdir = TemporaryDirectory()

    local_storage = Path(tempdir.name)
    container = get_container(
        JujuUnitName("foo/0"),
        None,
        "workload",
        {
            "type": "oci-image",
            "mounts": [{"type": "filesystem", "storage": "opt", "location": "/opt/"}],
        },
        [Path("/opt/foo/bar.txt")],
        temp_dir_base_path=local_storage,
    )

    mount_location = container.mounts["opt"].location
    local_file = Path(mount_location) / "opt" / "foo" / "bar.txt"
    assert local_file.read_text() == "hello world"


def test_gather_push_file_calls():
    td = TemporaryDirectory()
    td_path = Path(td.name)
    mount_path = td_path / "mount0"
    mount_path.mkdir()

    # put some files in there, to simulate state
    (mount_path / "foo.bar").write_text("hello")
    (mount_path / "bar.baz").write_text("world")
    sub = mount_path / "subdir"
    sub.mkdir()
    (sub / "qux.txt").write_text("and multiverse!")

    calls = _gather_push_file_calls(
        [Container("foo", mounts={"opt": Mount(location="/opt", source=mount_path)})],
        "unit/0",
        "model",
    )
    assert set(calls) == {
        f"juju scp -m model {mount_path}/foo.bar unit/0:/opt/foo.bar",
        f"juju scp -m model {mount_path}/bar.baz unit/0:/opt/bar.baz",
        f"juju scp -m model {mount_path}/subdir/qux.txt unit/0:/opt/subdir/qux.txt",
    }


def _make_unit_state_db(path: Path):
    storage = SQLiteStorage(path)
    event_handle = "MyCharm/on/update_status[1]"
    storage.save_notice(event_handle, "MyCharm", "_on_update_status")
    storage.save_snapshot(
        "MyCharm/StoredStateData[_stored]", {"counter": 5, "msg": "hi"}
    )
    storage.commit()
    storage.close()


def test_get_deferred_events():
    def _fetch_blob(*args, **kwargs):
        _make_unit_state_db(Path(kwargs["local_path"]))

    with patch("jhack.scenario.snapshot.fetch_blob", new=_fetch_blob):
        # RemoteUnitStateDB stores the db file to a temporary directory
        # already.
        db = RemoteUnitStateDB(None, JujuUnitName("foo/0"))
        deferred = db.get_deferred_events()
        stored_states = list(db.get_stored_states())

    assert len(deferred) == 1
    event = deferred[0]
    assert event.handle_path == "MyCharm/on/update_status[1]"
    assert event.owner == "MyCharm"
    assert event.observer == "_on_update_status"

    assert len(stored_states) == 1
    stored_state = stored_states[0]
    assert stored_state.owner_path == "MyCharm"
    assert stored_state.name == "_stored"
    assert stored_state.content == {"counter": 5, "msg": "hi"}