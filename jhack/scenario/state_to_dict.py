#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Facilities to convert State to json."""

from dataclasses import asdict, fields, is_dataclass
from typing import TYPE_CHECKING, Dict

from scenario import State
from scenario.state import Container, Mount

if TYPE_CHECKING:
    from scenario.state import AnyRelation


def _relation_to_dict(value: "AnyRelation") -> Dict:
    dct = asdict(value)
    dct["relation_type"] = type(value).__name__
    return dct


def _mount_to_dict(value: "Mount") -> Dict:
    dct = asdict(value)
    # asdict cannot recurse into Path objects.
    dct["location"] = str(value.location)
    dct["source"] = str(value.source)
    return dct


def _container_to_dict(value: "Container") -> Dict:
    dct = asdict(value)
    # asdict leaves frozenset fields as frozenset, which is not JSON-serializable.
    # Container.execs and Container.check_infos are frozensets.
    # snapshot doesn't populate them now, so they are always empty frozensets.
    # TODO: update this when we populate execs and check_infos in snapshot.
    dct["execs"] = list()
    dct["check_infos"] = list()
    # snapshot populates mounts, however. And Mount now stores Path objects.
    dct["mounts"] = {name: _mount_to_dict(m) for name, m in value.mounts.items()}
    return dct


def state_to_dict(state: State) -> Dict:
    out = {}
    for f in fields(state):
        key = f.name
        raw_value = getattr(state, f.name)
        if key == "relations":
            serialized_value = [_relation_to_dict(r) for r in raw_value]
        elif key == "containers":
            serialized_value = [_container_to_dict(c) for c in raw_value]
        else:
            if isinstance(raw_value, (list, frozenset)):
                serialized_value = [asdict(raw_obj) for raw_obj in raw_value]
            elif is_dataclass(raw_value):
                serialized_value = asdict(raw_value)
            else:
                serialized_value = raw_value

        out[key] = serialized_value
    return out
