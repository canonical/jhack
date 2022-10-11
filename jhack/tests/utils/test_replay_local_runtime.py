import random
import sys
from pathlib import Path

import pytest

# keep this block before `ops` imports. This ensures that if you've called Runtime.install() on
# your current venv, ops.model won't break as it tries to import recorder.py

try:
    from runtime import Runtime
except ModuleNotFoundError:
    import os

    from jhack.utils.event_recorder.runtime import RECORDER_MODULE

    sys.path.append(str(RECORDER_MODULE.absolute()))

from ops.charm import CharmBase, CharmEvents
from runtime import Runtime

MEMO_TOOLS_RESOURCES_FOLDER = Path(__file__).parent / "memo_tools_test_files"


def charm_type():
    class _CharmEvents(CharmEvents):
        pass

    class MyCharm(CharmBase):
        on = _CharmEvents()

        def __init__(self, framework, key=None):
            super().__init__(framework, key)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._catchall)
            self._event = None

        def _catchall(self, e):
            self._event = e


    return MyCharm


@pytest.mark.parametrize(
    "evt_idx, expected_name",
    (
        (0, "ingress_per_unit_relation_departed"),
        (1, "ingress_per_unit_relation_broken"),
        (2, "ingress_per_unit_relation_created"),
        (3, "ingress_per_unit_relation_joined"),
        (4, "ingress_per_unit_relation_changed"),
    ),
)
def test_run(evt_idx, expected_name):
    charm = charm_type()
    runtime = Runtime(
        charm,
        meta={
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        },
        local_db_path=MEMO_TOOLS_RESOURCES_FOLDER / "trfk-re-relate.json",
    )
    runtime.install()
    charm, scene = runtime.run(evt_idx)
    assert charm.unit.name == 'trfk/0'
    assert charm.model.name == 'foo'
    assert charm._event.handle.kind == scene.event.name == expected_name


def test_relation_data():
    charm = charm_type()
    runtime = Runtime(
        charm,
        meta={
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        },
        local_db_path=MEMO_TOOLS_RESOURCES_FOLDER / "trfk-re-relate.json",
    )
    runtime.install()
    charm, scene = runtime.run(4)  # ipu-relation-changed

    assert scene.event.name == 'ingress-per-unit-relation-changed'

    rel = charm.model.relations['ingress-per-unit'][0]

    # fixme: we need to access the data in the same ORDER in which we did before.
    #  for relation-get, it should be safe to ignore the memo ordering,
    #  since the data is frozen for the hook duration.
    #  actually it should be fine for most hook tools, except leader and status.
    #  pebble is a different story.

    remote_unit_data = rel.data[list(rel.units)[0]]
    assert remote_unit_data['host'] == 'prom-0.prom-endpoints.foo.svc.cluster.local'
    assert remote_unit_data['port'] == '9090'
    assert remote_unit_data['model'] == 'foo'
    assert remote_unit_data['name'] == 'prom/0'

    local_app_data = rel.data[charm.app]
    assert local_app_data == {}
