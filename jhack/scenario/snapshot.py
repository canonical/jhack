#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
import datetime
import json
import os
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from importlib import metadata
from itertools import chain
from pathlib import Path
from subprocess import run
from typing import Any, BinaryIO, Dict, Iterable, List, Optional, TextIO, Tuple, Union

import ops.pebble
import typer
import yaml
from ops.storage import SQLiteStorage
from scenario.runtime import UnitStateDB
from scenario.state import (
    Address,
    BindAddress,
    Container,
    Model,
    Mount,
    Network,
    Port,
    Relation,
    Secret,
    State,
    _EntityStatus,
    _Event,
)

from jhack.conf.conf import check_destructive_commands_allowed
from jhack.logger import logger as jhack_logger
from jhack.scenario.errors import InvalidTargetModelName, InvalidTargetUnitName
from jhack.scenario.integrations.darkroom import ops_port_to_scenario
from jhack.scenario.state_to_dict import state_to_dict
from jhack.scenario.utils import JujuUnitName

logger = jhack_logger.getChild(__file__)

JUJU_RELATION_KEYS = frozenset({"egress-subnets", "ingress-address", "private-address"})
JUJU_CONFIG_KEYS = frozenset({})


try:
    getcwd = os.getcwd()
except FileNotFoundError as e:
    raise Exception("cannot run jhack from a deleted folder") from e


SNAPSHOT_OUTPUT_DIR = (Path(getcwd).parent / "snapshot_storage").absolute()
CHARM_SUBCLASS_REGEX = re.compile(r"class (\D+)\(CharmBase\):")


def _try_format(string: str):
    try:
        import black

        try:
            return black.format_str(string, mode=black.Mode())
        except black.parsing.InvalidInput as e:
            logger.error(f"error parsing {string}: {e}")
            return string
    except ModuleNotFoundError:
        logger.warning("install black for formatting")
        return string


def format_state(state: State):
    """Stringify this State as nicely as possible."""
    return _try_format(repr(state))


PYTEST_TEST_TEMPLATE = """
from scenario import *
from charm import {ct}

def test_case():
    # Arrange: prepare the state
    state = {state}

    #Act: trigger an event on the state
    ctx = Context(
        {ct},
        juju_version="{jv}")

    out = ctx.run(
        {en}
        state,
        )

    # Assert: verify that the output state is the way you want it to be
    # TODO: add assertions
"""


class BindFailedError(Exception):
    """Raised by bind_event_to_state on failure to bind."""


def bind_event_to_state(event: _Event, state: State):
    """Attach to this event the state component it needs.

    For example, a relation event initialized without a Relation instance will search for
    a suitable relation in the provided state and return a copy of itself with that
    relation attached.

    In case of ambiguity (e.g. multiple relations found on 'foo' for event
    'foo-relation-changed', we pop a warning and bind the first one. Use with care!
    """
    entity_name = event._path.prefix  # noqa

    if event._is_workload_event and not event.container:  # noqa
        try:
            container = state.get_container(entity_name)
        except ValueError:
            raise BindFailedError(f"no container found with name {entity_name}")
        return dataclasses.replace(event, container=container)

    if event._is_secret_event and not event.secret:  # noqa
        secrets = list(state.secrets)
        if len(secrets) < 1:
            raise BindFailedError(f"no secrets found in state: cannot bind {event}")
        if len(secrets) > 1:
            raise BindFailedError(
                f"too many secrets found in state: cannot automatically bind {event}",
            )
        return dataclasses.replace(event, secret=secrets[0])

    if event._is_storage_event and not event.storage:  # noqa
        storages = state.get_storages(entity_name)
        if len(storages) < 1:
            raise BindFailedError(
                f"no storages called {entity_name} found in state",
            )
        if len(storages) > 1:
            logger.warning(
                f"too many storages called {entity_name}: binding to first one",
            )
        storage = storages[0]
        return dataclasses.replace(event, storage=storage)

    if event._is_relation_event and not event.relation:  # noqa
        ep_name = entity_name
        relations = state.get_relations(ep_name)
        if len(relations) < 1:
            raise BindFailedError(f"no relations on {ep_name} found in state")
        if len(relations) > 1:
            logger.warning(f"too many relations on {ep_name}: binding to first one")
        return dataclasses.replace(event, relation=relations[0])

    if event._is_action_event and not event.action:  # noqa
        raise BindFailedError(
            "cannot automatically bind action events: if the action has mandatory parameters "
            "this would probably result in horrible, undebuggable failures downstream.",
        )

    else:
        raise BindFailedError(
            f"cannot bind {event}: only relation, secret, or workload events can be bound.",
        )


def format_test_case(
    state: State,
    charm_type_name: str = None,
    event_name: str = None,
    juju_version: str = None,
):
    """Format this State as a pytest test case."""
    ct = charm_type_name or "CHARM_TYPE,  # TODO: replace with charm type name"
    en = "EVENT_NAME,  # TODO: replace with event name"
    if event_name:
        try:
            en = _Event(event_name)
        except BindFailedError:
            logger.error(
                f"Failed to bind {event_name} to {state}; leaving placeholder instead",
            )

    jv = juju_version or "3.0,  # TODO: check juju version is correct"
    state_fmt = repr(state)
    return _try_format(
        PYTEST_TEST_TEMPLATE.format(state=state_fmt, ct=ct, en=en, jv=jv),
    )


def _juju_run(cmd: str, model=None) -> Dict[str, Any]:
    """Execute juju {command} in a given model."""
    _model = f" -m {model}" if model else ""
    cmd = f"juju {cmd}{_model} --format json"
    raw = run(shlex.split(cmd), capture_output=True, text=True).stdout
    return json.loads(raw)


def _juju_ssh(target: JujuUnitName, cmd: str, model: Optional[str] = None) -> str:
    _model = f" -m {model}" if model else ""
    command = f"juju ssh{_model} {target.unit_name} {cmd}"
    raw = run(shlex.split(command), capture_output=True, text=True).stdout
    return raw


def _juju_exec(target: JujuUnitName, model: Optional[str], cmd: str) -> str:
    """Execute a juju command.

    Notes:
        Visit the Juju documentation to view all possible Juju commands:
        https://juju.is/docs/olm/juju-cli-commands
    """
    _model = f" -m {model}" if model else ""
    _target = f" -u {target}" if target else ""
    return run(
        shlex.split(f"juju exec{_model}{_target} -- {cmd}"),
        capture_output=True,
        text=True,
    ).stdout


def get_leader(target: JujuUnitName, model: Optional[str]):
    # could also get it from _juju_run('status')...
    logger.info("getting leader...")
    return _juju_exec(target, model, "is-leader") == "True"


def get_network(target: JujuUnitName, model: Optional[str], endpoint: str) -> Network:
    """Get the Network data structure for this endpoint."""
    raw = _juju_exec(target, model, f"network-get {endpoint}")
    json_data = yaml.safe_load(raw)

    bind_addresses = []
    for raw_bind in json_data["bind-addresses"]:
        addresses = []
        for raw_adds in raw_bind["addresses"]:
            addresses.append(
                Address(
                    hostname=raw_adds["hostname"],
                    # older jujus used 'address'
                    value=raw_adds.get("address", raw_adds["value"]),
                    cidr=raw_adds["cidr"],
                ),
            )

        bind_addresses.append(
            BindAddress(
                interface_name=raw_bind.get("interface-name", ""),
                addresses=addresses,
            ),
        )
    return Network(
        binding_name=endpoint,
        bind_addresses=bind_addresses,
        egress_subnets=json_data.get("egress-subnets", None),
        ingress_addresses=json_data.get("ingress-addresses", None),
    )


def get_secrets(
    target: JujuUnitName,  # noqa: U100
    model: Optional[str],  # noqa: U100
    metadata: Dict,  # noqa: U100
    relations: Tuple[str, ...] = (),  # noqa: U100
) -> List[Secret]:
    """Get Secret list from the charm."""
    logger.warning("Secrets snapshotting not implemented yet. Also, are you *sure*?")
    return []


def get_networks(
    target: JujuUnitName,
    model: Optional[str],
    metadata: Dict,
    include_dead: bool = False,
    relations: Tuple[str, ...] = (),
) -> Dict[str, Network]:
    """Get all Networks from this unit."""
    logger.info("getting networks...")
    networks = {"juju-info": get_network(target, model, "juju-info")}

    endpoints = relations  # only alive relations
    if include_dead:
        endpoints = chain(
            metadata.get("provides", ()),
            metadata.get("requires", ()),
            metadata.get("peers", ()),
        )

    for endpoint in endpoints:
        logger.debug(f"  getting network for endpoint {endpoint!r}")
        networks[endpoint] = get_network(target, model, endpoint)
    return networks


def get_metadata(target: JujuUnitName, model: Model):
    """Get metadata.yaml from this target."""
    logger.info("fetching metadata...")

    meta_path = target.remote_charm_root / "metadata.yaml"

    raw_meta = _juju_ssh(
        target,
        f"cat {meta_path}",
        model=model.name,
    )
    return yaml.safe_load(raw_meta)


class PebbleClientError(Exception):
    """Error raised by RemotePebbleClient._run."""


class InvalidContainerNameError(PebbleClientError):
    """Raised when you attempt RemotePebbleClient operations on a bad container name."""


class RemotePebbleClient:
    """Clever little class that wraps calls to a remote pebble client."""

    def __init__(
        self,
        container: str,
        target: JujuUnitName,
        model: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.socket_path = f"/charm/containers/{container}/pebble.socket"
        self.container = container
        self.target = target
        self.model = model
        self._dry_run = dry_run

    def _run(self, cmd: str) -> str:
        _model = f" -m {self.model}" if self.model else ""

        # charm container commands go straight to the charm container's pebble; no need to set a socket.
        socket_var = f" PEBBLE_SOCKET={self.socket_path}" if self.container != "charm" else ""
        command = f"juju ssh{_model} {self.target.unit_name}{socket_var} /charm/bin/pebble {cmd}"

        if self._dry_run:
            print(f"would run:\n\t{command!r}")
            return ""
        else:
            check_destructive_commands_allowed("sync", dry_run_cmd=command)

        proc = run(shlex.split(command), capture_output=True, text=True)
        if proc.returncode == 0:
            return proc.stdout

        if re.compile(
            rf"error: cannot communicate with server: Get (\S+): socket \"{self.socket_path}\" not found"
        ).match(proc.stdout):
            raise InvalidContainerNameError(self.container)

        raise RuntimeError(
            f"error wrapping pebble call with {command}: "
            f"process exited with {proc.returncode}; "
            f"stdout = {proc.stdout}; "
            f"stderr = {proc.stderr}",
        )

    def run(self, command: List[str]):
        """Run a command on this pebble."""
        return self._run(shlex.join(command))

    def can_connect(self) -> bool:
        try:
            version = self.get_system_info()
        except Exception:  # noqa
            return False
        return bool(version)

    def get_system_info(self):
        return self._run("version")

    def get_plan(self) -> dict:
        plan_raw = self._run("plan")
        return yaml.safe_load(plan_raw)

    def pull(
        self,
        path: str,  # noqa: U100
        *,
        encoding: Optional[str] = "utf-8",  # noqa: U100
    ) -> Union[BinaryIO, TextIO]:
        raise NotImplementedError()

    def list_files(
        self,
        path: str,  # noqa: U100
        *,
        pattern: Optional[str] = None,  # noqa: U100
        itself: bool = False,  # noqa: U100
    ) -> List[ops.pebble.FileInfo]:
        raise NotImplementedError()

    def get_checks(
        self,
        level: Optional[ops.pebble.CheckLevel] = None,
        names: Optional[Iterable[str]] = None,
    ) -> List[ops.pebble.CheckInfo]:
        _level = f" --level={level}" if level else ""
        _names = (" " + " ".join(names)) if names else ""
        out = self._run(f"checks{_level}{_names}")
        if out == "Plan has no health checks.":
            return []
        raise NotImplementedError()


def fetch_file(
    *,
    target: JujuUnitName,
    remote_path: Union[Path, str],
    container_name: str,
    local_path: Union[Path, str],
    model: Optional[str] = None,
) -> None:
    """Download a file from a live unit to a local path."""
    model_arg = f" -m {model}" if model else ""
    scp_cmd = (
        f"juju scp --container {container_name}{model_arg} "
        f"{target.unit_name}:{remote_path} {local_path}"
    )
    run(shlex.split(scp_cmd))


def get_mounts(
    target: JujuUnitName,
    model: Optional[str],
    container_name: str,
    container_meta: Dict,
    fetch_files: Optional[Dict[Path, Path]] = None,
    temp_dir_base_path: Path = SNAPSHOT_OUTPUT_DIR,
) -> Dict[str, Mount]:
    """Get named Mounts from a container's metadata, and download specified files from the unit."""
    mount_meta = container_meta.get("mounts")

    if fetch_files and not mount_meta:
        logger.error(
            f"No mounts defined for container {container_name} in metadata.yaml. "
            f"Cannot fetch files {fetch_files} for this container.",
        )
        return {}

    mount_spec = {}
    for mt in mount_meta or ():
        if name := mt.get("storage"):
            mount_spec[name] = mt["location"]
        else:
            logger.error(f"unknown mount type: {mt}")

    mounts = {}
    for remote_path in fetch_files or ():
        found = None
        for mn, mt in mount_spec.items():
            if str(remote_path).startswith(mt):
                found = mn, mt

        if not found:
            logger.error(
                "could not find mount corresponding to requested remote_path "
                f"{remote_path}: skipping...",
            )
            continue

        mount_name, src = found
        mount = mounts.get(mount_name)
        if not mount:
            # create the mount obj and tempdir
            location = tempfile.TemporaryDirectory(dir=str(temp_dir_base_path)).name
            mount = Mount(source=src, location=location)
            mounts[mount_name] = mount

        # populate the local tempdir
        filepath = Path(mount.location).joinpath(*remote_path.parts[1:])
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        try:
            fetch_file(
                target=target,
                container_name=container_name,
                model=model,
                remote_path=remote_path,
                local_path=filepath,
            )

        except RuntimeError:
            logger.exception()

    return mounts


def get_container(
    target: JujuUnitName,
    model: Optional[str],
    container_name: str,
    container_meta: Dict,
    fetch_files: Optional[List[Path]] = None,
    temp_dir_base_path: Path = SNAPSHOT_OUTPUT_DIR,
) -> Container:
    """Get container data structure from the target."""
    remote_client = RemotePebbleClient(container_name, target, model)
    plan = remote_client.get_plan()

    # todo find a way to include pebble layers?
    return Container(
        name=container_name,
        _base_plan=plan,
        can_connect=remote_client.can_connect(),
        mounts=get_mounts(
            target,
            model,
            container_name,
            container_meta,
            fetch_files,
            temp_dir_base_path=temp_dir_base_path,
        ),
    )


def get_containers(
    target: JujuUnitName,
    model: Optional[str],
    metadata: Optional[Dict],
    fetch_files: Dict[str, List[Path]] = None,
    temp_dir_base_path: Path = SNAPSHOT_OUTPUT_DIR,
) -> List[Container]:
    """Get all containers from this unit."""
    fetch_files = fetch_files or {}
    logger.info("getting containers...")

    if not metadata:
        logger.warning("no metadata: unable to get containers")
        return []

    containers = []
    for container_name, container_meta in metadata.get("containers", {}).items():
        container = get_container(
            target,
            model,
            container_name,
            container_meta,
            fetch_files=fetch_files.get(container_name),
            temp_dir_base_path=temp_dir_base_path,
        )
        containers.append(container)
    return containers


def get_juju_status(model: Optional[str]) -> Dict:
    """Return juju status as json."""
    logger.info("getting status...")
    return _juju_run("status --relations", model=model)


@dataclass
class Status:
    app: _EntityStatus
    unit: _EntityStatus
    workload_version: str


def get_status(juju_status: Dict, target: JujuUnitName) -> Status:
    """Parse `juju status` to get the Status data structure and some relation information."""
    app = juju_status["applications"][target.app_name]

    app_status_raw = app["application-status"]
    app_status = app_status_raw["current"], app_status_raw.get("message", "")

    unit_status_raw = app["units"][target]["workload-status"]
    unit_status = unit_status_raw["current"], unit_status_raw.get("message", "")

    workload_version = app.get("version", "")
    return Status(
        app=_EntityStatus(*app_status),
        unit=_EntityStatus(*unit_status),
        workload_version=workload_version,
    )


def get_endpoints(juju_status: Dict, target: JujuUnitName) -> Tuple[str, ...]:
    """Parse `juju status` to get the relation names owned by the target."""
    app = juju_status["applications"][target.app_name]
    relations_raw = app.get("relations", None)
    if not relations_raw:
        return ()
    relations = tuple(relations_raw.keys())
    return relations


def get_opened_ports(
    target: JujuUnitName,
    model: Optional[str],
) -> List[Port]:
    """Get opened ports list from target."""
    logger.info("getting opened ports...")

    opened_ports_raw = _juju_exec(
        target,
        model,
        "opened-ports --format json",
    )
    ports = []

    for raw_port in json.loads(opened_ports_raw):
        _port_n, _proto = raw_port.split("/")
        # ugly but can't be arsed to do that switch again
        ports.append(ops_port_to_scenario(ops.Port(_proto, int(_port_n))))

    return ports


def get_config(
    target: JujuUnitName,
    model: Optional[str],
) -> Dict[str, Union[str, int, float, bool]]:
    """Get config dict from target."""

    logger.info("getting config...")
    json_data = _juju_run(f"config {target.app_name}", model=model)

    # dispatch table for builtin config options
    converters = {
        "string": str,
        "int": int,
        "integer": int,  # fixme: which one is it?
        "number": float,
        "boolean": lambda x: x == "true",
        "attrs": lambda x: x,  # fixme: wot?
    }

    cfg = {}
    for name, option in json_data.get("settings", {}).items():
        if value := option.get("value"):
            try:
                converter = converters[option["type"]]
            except KeyError:
                raise ValueError(f"unrecognized type {option['type']}")
            cfg[name] = converter(value)

        else:
            logger.debug(f"skipped {name}: no value.")

    return cfg


def _get_interface_from_metadata(endpoint: str, metadata: Dict) -> Optional[str]:
    """Get the name of the interface used by endpoint."""
    for role in ["provides", "requires"]:
        for ep, ep_meta in metadata.get(role, {}).items():
            if ep == endpoint:
                return ep_meta["interface"]

    logger.error(f"No interface for endpoint {endpoint} found in charm metadata.")
    return None


def _get_local_relation_data(relation_id: int, target: JujuUnitName, model: str):
    local_unit_data_raw = _juju_exec(
        target,
        model,
        f"relation-get -r {relation_id} - {target} --format json",
    )
    local_unit_data = json.loads(local_unit_data_raw)
    local_app_data_raw = _juju_exec(
        target,
        model,
        f"relation-get -r {relation_id} - {target} --format json --app",
    )
    local_app_data = json.loads(local_app_data_raw)
    return local_unit_data, local_app_data


def get_relations(
    target: JujuUnitName,
    model: Optional[str],
    metadata: Dict,
    include_juju_relation_data=False,
) -> List[Relation]:
    """Get the list of relations active for this target."""
    logger.info("getting relations...")

    try:
        json_data = _juju_run(f"show-unit {target}", model=model)
    except json.JSONDecodeError:
        raise InvalidTargetUnitName(target)

    def _clean(relation_data: dict):
        if include_juju_relation_data:
            return relation_data
        else:
            for key in JUJU_RELATION_KEYS:
                if key in relation_data:
                    del relation_data[key]
        return relation_data

    relations = []
    for raw_relation in json_data[target].get("relation-info", ()):
        logger.debug(
            f"  getting relation data for endpoint {raw_relation.get('endpoint')!r}",
        )
        related_units = raw_relation.get("related-units")
        if not related_units:
            continue
        #    related-units:
        #      owner/0:
        #        in-scope: true
        #        data:
        #          egress-subnets: 10.152.183.130/32
        #          ingress-address: 10.152.183.130
        #          private-address: 10.152.183.130

        relation_id = raw_relation["relation-id"]

        try:
            local_unit_data, local_app_data = _get_local_relation_data(
                relation_id,
                target,
                model,
            )
        except json.JSONDecodeError:
            logger.error(
                f"error decoding relation data for {target}: relation with ID {relation_id} "
                f"is probably dead but juju doesn't know yet.",
            )
            continue

        some_remote_unit_id = JujuUnitName(next(iter(related_units)))

        # fixme: at the moment the juju CLI offers no way to see what type of relation this is;
        #  if it's a peer relation or a subordinate, we should use the corresponding
        #  scenario.state types instead of a regular Relation.

        relations.append(
            Relation(
                endpoint=raw_relation["endpoint"],
                interface=_get_interface_from_metadata(
                    raw_relation["endpoint"],
                    metadata,
                ),
                id=relation_id,
                remote_app_data=raw_relation["application-data"],
                remote_app_name=some_remote_unit_id.app_name,
                remote_units_data={
                    JujuUnitName(tgt).unit_id: _clean(val["data"])
                    for tgt, val in related_units.items()
                },
                local_app_data=local_app_data,
                local_unit_data=_clean(local_unit_data),
            ),
        )
    return relations


def get_model(name: str = None) -> Model:
    """Get the Model data structure."""
    logger.info("getting model...")

    json_data = _juju_run("models")
    model_name = name or json_data["current-model"]
    try:
        model_info = next(
            filter(lambda m: m["short-name"] == model_name, json_data["models"]),
        )
    except StopIteration:
        raise InvalidTargetModelName(name)

    model_uuid = model_info["model-uuid"]
    model_type = model_info["type"]

    return Model(name=model_name, uuid=model_uuid, type=model_type)


def try_guess_charm_type_name() -> Optional[str]:
    """If we are running this from a charm project root, get the charm type name from charm.py."""
    try:
        charm_path = Path(os.getcwd()) / "src" / "charm.py"
        if charm_path.exists():
            source = charm_path.read_text()
            charms = CHARM_SUBCLASS_REGEX.findall(source)
            if len(charms) < 1:
                raise RuntimeError(f"Not enough charms at {charm_path}.")
            elif len(charms) > 1:
                raise RuntimeError(f"Too many charms at {charm_path}.")
            return charms[0]
    except Exception as _err:
        logger.warning(f"unable to guess charm type: {_err}")
    return None


class FormatOption(
    str,
    Enum,
):  # Enum for typer support, str for native comparison and ==.
    """Output formatting options for snapshot."""

    state = "state"  # the default: will print the python repr of the State dataclass.
    json = "json"
    pytest = "pytest"


def get_juju_version(juju_status: Dict) -> str:
    """Get juju agent version from juju status output."""
    return juju_status["model"]["version"]


def get_charm_version(target: JujuUnitName, juju_status: Dict) -> str:
    """Get charm version info from juju status output."""
    app_info = juju_status["applications"][target.app_name]
    channel = app_info.get("charm-channel", "<local charm>")
    charm_name = app_info.get("charm-name", "n/a")
    workload_version = app_info.get("version", "n/a")
    charm_rev = app_info.get("charm-rev", "n/a")
    charm_origin = app_info.get("charm-origin", "n/a")
    return (
        f"charm {charm_name!r} ({channel}/{charm_rev}); "
        f"origin := {charm_origin}; app version := {workload_version}."
    )


class RemoteUnitStateDB(UnitStateDB):
    """Represents a remote unit's state db."""

    def __init__(self, model: Optional[str], target: JujuUnitName):
        self._tempfile = tempfile.NamedTemporaryFile()
        super().__init__(self._tempfile.name)

        self._model = model
        self._target = target

    def _fetch_state(self):
        fetch_file(
            target=self._target,
            remote_path=self._target.remote_charm_root / ".unit-state.db",
            container_name="charm",
            local_path=self._state_file,
            model=self._model,
        )

    @property
    def _has_state(self):
        """Whether the state file exists."""
        return self._state_file.exists() and self._state_file.read_bytes()

    def _open_db(self) -> SQLiteStorage:
        if not self._has_state:
            self._fetch_state()
        return super()._open_db()


def get_scenario_version():
    return metadata.metadata("ops-scenario")["Version"]


def _snapshot(
    target: str,
    model: Optional[str] = None,
    pprint: bool = True,
    include: Optional[str] = None,
    include_juju_relation_data=False,
    include_dead_relation_networks=False,
    format_: FormatOption = "state",
    event_name: Optional[str] = None,
    fetch_files: Optional[Dict[str, Dict[Path, Path]]] = None,
    temp_dir_base_path: Path = SNAPSHOT_OUTPUT_DIR,
):
    """see snapshot's docstring"""

    try:
        target = JujuUnitName(target)
    except InvalidTargetUnitName:
        logger.critical(
            f"invalid target: {target!r} is not a valid unit name. Should be formatted like so:"
            f"`foo/1`, or `database/0`, or `myapp-foo-bar/42`.",
        )
        sys.exit(1)

    logger.info(f"beginning snapshot of {target} in model {model or '<current>'}...")

    def if_include(key, fn, default):
        if include is None or key in include:
            return fn()
        return default

    try:
        state_model = get_model(model)
    except InvalidTargetModelName:
        logger.critical(f"unable to get Model from name {model}.", exc_info=True)
        sys.exit(1)

    # todo: what about controller?
    model = state_model.name

    metadata = get_metadata(target, state_model)
    if not metadata:
        logger.critical(f"could not fetch metadata from {target}.")
        sys.exit(1)

    try:
        unit_state_db = RemoteUnitStateDB(model, target)
        juju_status = get_juju_status(model)
        endpoints = get_endpoints(juju_status, target)
        status = get_status(juju_status, target=target)

        state = State(
            leader=get_leader(target, model),
            unit_status=status.unit,
            app_status=status.app,
            workload_version=status.workload_version,
            model=state_model,
            config=if_include("c", lambda: get_config(target, model), {}),
            opened_ports=if_include(
                "p",
                lambda: get_opened_ports(target, model),
                [],
            ),
            relations=if_include(
                "r",
                lambda: get_relations(
                    target,
                    model,
                    metadata=metadata,
                    include_juju_relation_data=include_juju_relation_data,
                ),
                [],
            ),
            containers=if_include(
                "k",
                lambda: get_containers(
                    target,
                    model,
                    metadata,
                    fetch_files=fetch_files,
                    temp_dir_base_path=temp_dir_base_path,
                ),
                [],
            ),
            networks=if_include(
                "n",
                lambda: get_networks(
                    target,
                    model,
                    metadata,
                    include_dead=include_dead_relation_networks,
                    relations=endpoints,
                ),
                {},
            ),
            secrets=if_include(
                "S",
                lambda: get_secrets(
                    target,
                    model,
                    metadata,
                    relations=endpoints,
                ),
                [],
            ),
            deferred=if_include(
                "d",
                unit_state_db.get_deferred_events,
                [],
            ),
            stored_states=if_include(
                "t",
                unit_state_db.get_stored_states,
                [],
            ),
        )

        # todo: these errors should surface earlier.
    except InvalidTargetUnitName:
        _model = f"model {model}" or "the current model"
        logger.critical(f"invalid target: {target!r} not found in {_model}")
        sys.exit(1)
    except InvalidTargetModelName:
        logger.critical(f"invalid model: {model!r} not found.")
        sys.exit(1)

    logger.info("snapshot done.")

    if pprint:
        charm_version = get_charm_version(target, juju_status)
        scenario_version = get_scenario_version()
        juju_version = get_juju_version(juju_status)
        if format_ == FormatOption.pytest:
            charm_type_name = try_guess_charm_type_name()
            txt = format_test_case(
                state,
                event_name=event_name,
                charm_type_name=charm_type_name,
                juju_version=juju_version,
            )
        elif format_ == FormatOption.state:
            txt = format_state(state)
        elif format_ == FormatOption.json:
            txt = json.dumps(state_to_dict(state), indent=2)
        else:
            raise ValueError(f"unknown format {format_}")

        # json does not support comments, so it would be invalid output.
        if format_ != FormatOption.json:
            # print out some metadata
            controller_timestamp = juju_status["controller"]["timestamp"]
            local_timestamp = datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
            print(
                f"# Generated by jhack.scenario.snapshot. \n"
                f"# Snapshot of {state_model.name}:{target.unit_name} at {local_timestamp}. \n"
                f"# Controller timestamp := {controller_timestamp}. \n"
                f"# Juju version := {juju_version} \n"
                f"# Scenario version := {scenario_version} \n"
                f"# Charm fingerprint := {charm_version} \n",
            )

        print(txt)

    return state


def snapshot(
    target: str = typer.Argument(..., help="Target unit."),
    model: Optional[str] = typer.Option(
        None,
        "-m",
        "--model",
        help="Which model to look at.",
    ),
    format_: FormatOption = typer.Option(
        "state",
        "-f",
        "--format",
        help="How to format the output. "
        "``state``: Outputs a black-formatted repr() of the State object (if black is installed! "
        "else it will be ugly but valid python code). All you need to do then is import the "
        "necessary objects from scenario.state, and you should have a valid State object. "
        "``json``: Outputs a Jsonified State object. Perfect for storage. "
        "``pytest``: Outputs a full-blown pytest scenario test based on this State. "
        "Pipe it to a file and fill in the blanks.",
    ),
    event_name: str = typer.Option(
        None,
        "--event_name",
        "-e",
        help="Event to include in the generate test file; only applicable "
        "if the output format is 'pytest'.",
    ),
    include: str = typer.Option(
        "rckndtp",
        "--include",
        "-i",
        help="What data to include in the state. "
        "``r``: relation, ``c``: config, ``k``: containers, "
        "``n``: networks, ``S``: secrets(!), ``p``: opened ports, "
        "``d``: deferred events, ``t``: stored state.",
    ),
    include_dead_relation_networks: bool = typer.Option(
        False,
        "--include-dead-relation-networks",
        help="Whether to gather networks of inactive relation endpoints.",
        is_flag=True,
    ),
    include_juju_relation_data: bool = typer.Option(
        False,
        "--include-juju-relation-data",
        help="Whether to include in the relation data the default juju keys (egress-subnets,"
        "ingress-address, private-address).",
        is_flag=True,
    ),
    fetch: Path = typer.Option(
        None,
        "--fetch",
        help="Path to a local file containing a json spec of files to be fetched from the unit. "
        "For k8s units, it's supposed to be a {container_name: List[Path]} mapping listing "
        "the files that need to be fetched from the existing containers.",
    ),
    # TODO: generalize "fetch" to allow passing '.' for the 'charm' container or 'the machine'.
    output_dir: Path = typer.Option(
        SNAPSHOT_OUTPUT_DIR,
        "--output-dir",
        help="Directory in which to store any files fetched as part of the state. In the case "
        "of k8s charms, this might mean files obtained through Mounts,",
    ),
) -> State:
    """Gather and output the State of a remote target unit.

    If black is available, the output will be piped through it for formatting.

    Usage: snapshot myapp/0 > ./tests/scenario/case1.py
    """

    fetch_files = json.loads(fetch.read_text()) if fetch else None

    return _snapshot(
        target=target,
        model=model,
        format_=format_,
        event_name=event_name,
        include=include,
        include_juju_relation_data=include_juju_relation_data,
        include_dead_relation_networks=include_dead_relation_networks,
        temp_dir_base_path=output_dir,
        fetch_files=fetch_files,
    )


# for the benefit of script usage
_snapshot.__doc__ = snapshot.__doc__

if __name__ == "__main__":
    # print(_snapshot("zookeeper/0", model="foo", format=FormatOption.pytest))

    print(
        _snapshot(
            "traefik/0",
            format_=FormatOption.state,
            include="r",
            # fetch_files={
            #     "traefik": [
            #         Path("/opt/traefik/juju/certificates.yaml"),
            #         Path("/opt/traefik/juju/certificate.cert"),
            #         Path("/opt/traefik/juju/certificate.key"),
            #         Path("/etc/traefik/traefik.yaml"),
            #     ]
            # },
        ),
    )
