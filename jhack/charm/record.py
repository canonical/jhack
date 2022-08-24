import json
from subprocess import check_output

import typer
from typing import List, Dict, Protocol
from dataclasses import dataclass, asdict

from jhack.helpers import current_model
from jhack.utils.show_relation import RelationData, get_relations, \
    get_relation_data
from jhack.utils.tail_charms import _tail_events, EventLogMsg
from jhack.logger import logger


KeyValueMapping = Dict[str, str]


class HasWrite(Protocol):
    def write(self, text: str): ...


logger = logger.getChild(__file__)

@dataclass
class State:
    event: EventLogMsg  # event which triggered a state transition
    databags: List[RelationData]  # relation databags at this point in time
    config: KeyValueMapping  # config at this point in time


class Recorder:
    def __init__(self, unit: str, model: str = None, output: HasWrite = None):
        self._unit = unit
        self._app = unit.split('/')[0]
        self._model = model or current_model()
        self._state_history: List[State] = []
        self._ignored_events = {'update_status'}
        self._output = output

    def record(self):
        tail = _tail_events(self._unit, replay=False, add_new_targets=False,
                            _on_event=self._on_event)
        self._dump_json()
        return self._state_history

    def _dump_json(self):
        states = []
        for state in self._state_history:
            states.append(asdict(state))
        jsn = json.dumps(states, indent=2)
        if self._output:
            self._output.write(jsn)
        else:
            print(jsn)

    def _relations_state(self) -> List[RelationData]:
        state = []
        model = self._model
        app = self._app
        for relation in get_relations(model):
            logger.debug(f'found relation {relation}')
            if (relation.requirer.split(':')[0] == app or
                    relation.provider.split(':')[0] == app):
                relation_data = get_relation_data(
                    provider_endpoint=relation.provider,
                    requirer_endpoint=relation.requirer,
                    include_default_juju_keys=True,
                    model=model)
                logger.debug(f'extracted data: {relation_data}')
                state.append(relation_data)
        return state

    def _config_state(self) -> KeyValueMapping:
        config_raw = check_output(
            f'juju config {self._app} --output=json'.split())
        config = json.loads(config_raw or "{}").get('settings', {})
        cfg = {key: value['value'] for key, value in config.items()}
        return cfg

    def _snapshot(self, event: EventLogMsg):
        relations = self._relations_state()
        config = self._config_state()
        state = State(event, relations, config)
        self._state_history.append(state)

    def _on_event(self, event: EventLogMsg):
        if event.event in self._ignored_events:
            logger.debug(f'skipped ignored event {event.event}')
            return

        logger.debug(f'{event.timestamp}: {event.event}')
        self._snapshot(event)


def record(unit: str = typer.Argument(
    ..., help='The unit you wish to record.')):
    """Record the events and state for a juju unit, to be able to replay it later.
    """
    Recorder(unit).record()
