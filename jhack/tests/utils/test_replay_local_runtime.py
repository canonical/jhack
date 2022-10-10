import sys
from pathlib import Path
import random

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

MEMO_TOOLS_RESOURCES_FOLDER = Path(__file__).parent / 'memo_tools_test_files'


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

    MyCharm.handle_kind = f'MyCharm-test-{str(random.randint(10000000000, 99999999999))}'
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
    print(id(charm))
    runtime = Runtime(
        charm,
        meta={
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        },
        local_db_path=MEMO_TOOLS_RESOURCES_FOLDER / 'trfk-re-relate.json'
    )
    runtime.install()
    charm = runtime.run(evt_idx)
    assert charm._event.handle.kind == expected_name
