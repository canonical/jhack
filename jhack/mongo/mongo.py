#!/bin/bash
import json
import re
import shlex
from pathlib import Path
from subprocess import Popen, PIPE
from typing import Literal, Tuple

from jhack.helpers import get_current_model, get_substrate, JPopen


def escape_double_quotes(query):
    return query.replace('"', r'\"')


class ConnectorBase:
    args_getter_script: Path
    query_script: Path

    def __init__(self):
        self.args = self.get_args()

    def _get_output(self, cmd: str) -> str:
        return JPopen(shlex.split(cmd)).stdout.read().decode('utf-8')

    def get_args(self) -> Tuple[str, ...]:
        out = Popen(
            shlex.split(
                f"bash {self.args_getter_script.absolute()}",
            ), stdout=PIPE
        ).stdout.read().decode('utf-8')
        return tuple(f"'{x}'" for x in out.split())  # noqa

    def query(self, query: str):
        query = escape_double_quotes(query)
        command = ["bash", str(self.query_script.absolute()), *self.args, f""" "'{query}'" """]
        proc = Popen(command, stdout=PIPE, stderr=PIPE)
        out = proc.stdout.read().decode('utf-8')
        txt = out.split('\n')
        if len(txt) != 3:
            raise RuntimeError(f'unexpected result from command {command}; {proc.stderr.read()}')
        result = txt[1]
        return parse_eson(result)


class K8sConnector(ConnectorBase):
    """Mongo database connector for kubernetes controllers."""
    args_getter_script = Path(__file__).parent / 'get_credentials_from_k8s_controller.sh'
    query_script = Path(__file__).parent / 'query_k8s_controller.sh'

    def get_args(self):
        return ("microk8s.kubectl", ) + super().get_args()



class MachineConnector(ConnectorBase):
    """Mongo database connector for kubernetes controllers."""
    args_getter_script = Path(__file__).parent / 'get_credentials_from_machine_controller.sh'
    query_script = Path(__file__).parent / 'query_machine_controller.sh'

    def get_args(self):
        return super().get_args() + ("controller", "0")


class Mongo:
    def __init__(self,
                 entity_id: int = 0,
                 substrate: Literal['k8s', 'machine'] = None,
                 model: str = None):
        self.substrate = substrate or get_substrate()
        self.entity_id = entity_id
        self.model = model or get_current_model()

        if substrate == 'k8s':
            self.connector = K8sConnector()

        elif substrate == 'machine':
            self.connector = MachineConnector()

        else:
            raise TypeError(substrate)

    def query(self, q: str):
        return self.connector.query(q)
