#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Facilities to convert json to State."""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict

from ops import SecretRotate, pebble
from scenario import Model, State
from scenario.state import (
    Address,
    BindAddress,
    Container,
    DeferredEvent,
    Network,
    PeerRelation,
    Port,
    Relation,
    Secret,
    Storage,
    StoredState,
    SubordinateRelation,
    _EntityStatus,
)

if TYPE_CHECKING:
    from scenario.state import AnyRelation


def _dict_to_status(value: Dict) -> _EntityStatus:
    return _EntityStatus(**value)


def _dict_to_model(value: Dict) -> Model:
    return Model(**value)


def _dict_to_relation(value: Dict) -> "AnyRelation":
    relation_type = value.pop("relation_type")
    if relation_type == "Relation":
        return Relation(**value)
    if relation_type == "PeerRelation":
        return PeerRelation(**value)
    if relation_type == "SubordinateRelation":
        return SubordinateRelation(**value)
    raise TypeError(value)


def _dict_to_address(value: Dict) -> Address:
    return Address(**value)


def _dict_to_bindaddress(value: Dict) -> BindAddress:
    if addrs := value.get("addresses"):
        value["addresses"] = [_dict_to_address(addr) for addr in addrs]
    return BindAddress(**value)


def _dict_to_network(value: Dict) -> Network:
    if addrs := value.get("bind_addresses"):
        value["bind_addresses"] = [_dict_to_bindaddress(addr) for addr in addrs]
    return Network(**value)


def _dict_to_container(value: Dict) -> Container:
    if layers := value.get("layers"):
        value["layers"] = {
            l_name: pebble.Layer(l_raw) for l_name, l_raw in layers.items()
        }
    return Container(**value)


def _dict_to_opened_port(value: Dict) -> Port:
    return Port(**value)


def _dict_to_secret(value: Dict) -> Secret:
    if rotate := value.get("rotate"):
        value["rotate"] = SecretRotate(rotate)
    if expire := value.get("expire"):
        value["expire"] = datetime.fromisoformat(expire)
    return Secret(**value)


def _dict_to_stored_state(value: Dict) -> StoredState:
    return StoredState(**value)


def _dict_to_deferred(value: Dict) -> DeferredEvent:
    return DeferredEvent(**value)


def _dict_to_storage(value: Dict) -> Storage:
    return Storage(**value)


def dict_to_state(state_json: Dict) -> State:
    overrides = {}
    for key, value in state_json.items():
        if key in [
            "leader",
            "config",
            "planned_units",
            "unit_id",
            "workload_version",
        ]:  # all state components that can be used as-is
            overrides[key] = value
        elif key in [
            "app_status",
            "unit_status",
        ]:  # all state components that can be used as-is
            overrides[key] = _dict_to_status(value)
        elif key == "model":
            overrides[key] = _dict_to_model(value)
        elif key == "relations":
            overrides[key] = [_dict_to_relation(obj) for obj in value]
        elif key == "networks":
            overrides[key] = {
                name: _dict_to_network(obj) for name, obj in value.items()
            }
        elif key == "resources":
            overrides[key] = {name: Path(obj) for name, obj in value.items()}
        elif key == "containers":
            overrides[key] = [_dict_to_container(obj) for obj in value]
        elif key == "storage":
            overrides[key] = [_dict_to_storage(obj) for obj in value]
        elif key == "opened_ports":
            overrides[key] = [_dict_to_opened_port(obj) for obj in value]
        elif key == "secrets":
            overrides[key] = [_dict_to_secret(obj) for obj in value]
        elif key == "stored_state":
            overrides[key] = [_dict_to_stored_state(obj) for obj in value]
        elif key == "deferred":
            overrides[key] = [_dict_to_deferred(obj) for obj in value]
        else:
            raise KeyError(key)

    return State().replace(**overrides)
