from jhack.helpers import juju_version, JPopen, show_unit
from jhack.logger import logger as jhack_logger

# note juju-exec is juju-run in juju<3.0
_J_EXEC_CMD = 'juju-exec' if juju_version() >= "0.3" else 'juju-run'
_RELATION_EVENT_SUFFIXES = {
    '-relation-changed',
    '-relation-created',
    '-relation-joined',
    '-relation-broken',
    '-relation-departed',
}

logger = jhack_logger.getChild('simulate_event')

def _get_relation_id(unit: str, endpoint: str):
    unit = show_unit(unit)
    for binding in unit['relation-info']:
        if binding['endpoint'] == endpoint:
            return binding['relation-id']
    raise RuntimeError(f'unit {unit} has no active bindings to {endpoint}')


def _get_relation_endpoint(event: str):
    for suffix in _RELATION_EVENT_SUFFIXES:
        if suffix in event:
            return event[:-len(suffix)]
    return False


def _get_env(unit, event, relation_id: int = None):
    env = {"JUJU_DISPATCH_PATH": f"hooks/{event}"}

    if endpoint := _get_relation_endpoint(event):
        relation_id = relation_id if relation_id is not None else _get_relation_id(unit, endpoint)
        env["JUJU_RELATION"] = endpoint
        env["JUJU_RELATION_ID"] = relation_id

    return ' '.join(f"{k}={v}" for k, v in env.items())


def _simulate_event(unit, event):
    env = _get_env(unit, event)
    cmd = f"juju ssh {unit} /usr/bin/{_J_EXEC_CMD} -u {unit} {env} ./dispatch"
    logger.info(cmd)
    proc = JPopen(cmd.split())
    proc.wait()
    return


def simulate_event(unit: str, event: str):
    """Simulates an event on a unit."""
    return _simulate_event(unit, event)


if __name__ == '__main__':
    _simulate_event('trfk/0', 'update-status')