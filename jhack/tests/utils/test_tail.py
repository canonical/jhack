from unittest.mock import patch, MagicMock

import pytest

from jhack.utils.tail_charms import tail_events

MOCK_JDL = b"""unit-traefik-k8s-0: 12:04:18 INFO juju.worker.uniter.operation ran "start" hook (via hook dispatching script: dispatch)
unit-traefik-k8s-0: 12:04:18 INFO juju.worker.uniter.operation ran "install" hook (via hook dispatching script: dispatch)
unit-traefik-k8s-0: 12:04:18 INFO juju.worker.uniter.operation ran "update-status" hook (via hook dispatching script: dispatch)
unit-traefik-k8s-0: 13:23:30 DEBUG unit.traefik-k8s/0.juju-log Deferring <UpdateStatusEvent via TraefikIngressCharm/on/update_status[247]>.
unit-traefik-k8s-0: 12:04:18 INFO juju.worker.uniter.operation ran "bork" hook (via hook dispatching script: dispatch)
unit-traefik-k8s-0: 12:17:50 DEBUG unit.traefik-k8s/0.juju-log Re-emitting <UpdateStatusEvent via TraefikIngressCharm/on/update_status[166]>.
unit-traefik-k8s-0: 13:23:30 DEBUG unit.traefik-k8s/0.juju-log Deferring <UpdateStatusEvent via TraefikIngressCharm/on/bork[247]>.
unit-traefik-k8s-0: 12:04:18 INFO juju.worker.uniter.operation ran "update-status" hook (via hook dispatching script: dispatch)
unit-traefik-k8s-0: 12:17:50 DEBUG unit.traefik-k8s/0.juju-log Re-emitting <UpdateStatusEvent via TraefikIngressCharm/on/bork[166]>.
"""


def _fake_log_proc(cmd):
    proc = MagicMock()
    proc.stdout.readlines.return_value = MOCK_JDL.split(b'\n')
    return proc


@pytest.fixture(autouse=True)
def mock_stdout():
    with patch("jhack.utils.tail_charms._get_debug_log", wraps=_fake_log_proc) as mock_status:
        yield


def test_tail_():
    tail_events(targets='traefik-k8s/0', length=10000, watch=False)
