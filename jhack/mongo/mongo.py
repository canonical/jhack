#!/bin/bash
import json
import os
import re
import shlex
from pathlib import Path
from subprocess import PIPE, Popen
from typing import List, Literal, Tuple

from jhack.helpers import JPopen, get_current_model, get_substrate


def escape_double_quotes(query):
    return query.replace('"', r"\"")


def numberlong(s: str):
    return re.sub(r"NumberLong\((\d+)\)", r"\1", s)


FILTERS = [numberlong]


def to_json(query_result: str):
    jsn_str = query_result
    for f in FILTERS:
        jsn_str = f(jsn_str)
    return json.loads(jsn_str)


class TooManyResults(RuntimeError):
    """Raised when a query returns more results than we handle."""


class EmptyQueryResult(RuntimeError):
    """Query returned no results."""


class ConnectorBase:
    args_getter_script: Path
    query_script: Path

    def __init__(self, controller: str = None, unit_id: int = 0):
        self.controller = controller
        self.model = f"{controller}:controller" if controller else "controller"
        self.unit_id = unit_id
        self.args = self.get_args()

    def _escape_query(self, query: str) -> str:
        return rf'"{escape_double_quotes(query)}"'

    def _get_output(self, cmd: str) -> str:
        return JPopen(shlex.split(cmd)).stdout.read().decode("utf-8")

    def get_args(self) -> Tuple[str, ...]:
        out = (
            Popen(
                shlex.split(
                    f"bash {self.args_getter_script.absolute()} {self.unit_id} {self.model}",
                ),
                stdout=PIPE,
            )
            .stdout.read()
            .decode("utf-8")
        )
        return tuple(out.split())  # noqa
        # return tuple(f"'{x}'" for x in out.split())  # noqa

    def get(self, query: str, n: int = None, query_filter: str = None) -> List[dict]:
        qfilter = query_filter or "{}"
        if n is None:
            q = query + fr".find({qfilter}).toArray()"
        else:
            q = query + fr".find({qfilter}).limit({n}).toArray()"
        escaped = self._escape_query(q)
        out = self._run_query(escaped)

        if not out:
            raise EmptyQueryResult(escaped)
        return out

    def _run_query(self, query: str):
        command = ["bash", str(self.query_script.absolute()), *self.args, query]
        proc = Popen(command, stdout=PIPE, stderr=PIPE)
        raw_output = proc.stdout.read().decode("utf-8")
        if not raw_output:
            err = proc.stderr.read().decode("utf-8")
            print(err)
            raise RuntimeError(f"unexpected result from command {command}; {err!r}")

        # stripped = "[" + "\n".join(filter(None, raw_output.split('\n')[1:])) + "]"
        stripped = "\n".join(filter(None, raw_output.split('\n')[1:]))
        try:
            return to_json(stripped)
        except Exception as e:
            err = proc.stderr.read().decode("utf-8")
            print(err)
            raise RuntimeError(
                f"failed deserializing query result {stripped} with {type(e)} {err}"
            ) from e


class K8sConnector(ConnectorBase):
    """Mongo database connector for kubernetes controllers."""

    args_getter_script = (
            Path(__file__).parent / "get_credentials_from_k8s_controller.sh"
    )
    query_script = Path(__file__).parent / "query_k8s_controller.sh"


class MachineConnector(ConnectorBase):
    """Mongo database connector for kubernetes controllers."""

    args_getter_script = (
            Path(__file__).parent / "get_credentials_from_machine_controller.sh"
    )
    query_script = Path(__file__).parent / "query_machine_controller.sh"

    def get_args(self):
        return super().get_args() + (self.model, str(self.unit_id))


class Mongo:
    def __init__(
            self,
            entity_id: int = 0,
            substrate: Literal["k8s", "machine"] = None,
            model: str = None,
    ):
        self.substrate = substrate or get_substrate()
        self.entity_id = entity_id
        self.model = model or get_current_model()

        if substrate == "k8s":
            self.connector = K8sConnector()

        elif substrate == "machine":
            self.connector = MachineConnector()

        else:
            raise TypeError(substrate)

    def _get(self, query: str, n: int = None, query_filter: str = None):
        return self.connector.get(query, n=n, query_filter=query_filter)


