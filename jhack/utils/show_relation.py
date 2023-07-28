import asyncio
import dataclasses
import json
import re
import sys
import time
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import typer

from jhack.helpers import (
    ColorOption,
    Format,
    FormatOption,
    FormatUnavailable,
    JPopen,
    RichSupportedColorOptions,
    juju_status,
)
from jhack.logger import logger

logger = logger.getChild(__file__)

_JUJU_DATA_CACHE = {}
_JUJU_KEYS = ("egress-subnets", "ingress-address", "private-address")
_UNIT_ID_RE = re.compile(r"/\d")
_RELATIONS_RE = re.compile(
    r"([\w\-]+):([\w\-]+)\s+([\w\-]+):([\w\-]+)\s+([\w\-]+)\s+([\w\-]+).*"
)


class RelationType(str, Enum):
    regular = "regular"
    subordinate = "subordinate"
    peer = "peer"
    cross_model = "cross_model"


@dataclass
class Relation:
    provider: str
    provider_endpoint: str
    requirer: str
    requirer_endpoint: str
    interface: str
    raw_type: str

    @property
    def type(self) -> RelationType:
        return RelationType(self.raw_type)


class RelationEndpointURL(str):
    def __init__(self, s):
        super().__init__()
        if ":" in s:
            u, endpoint = s.split(":")
        else:
            u, endpoint = s, None

        if "/" in u:
            app_name, unit_id = u.split("/")
        else:
            app_name, unit_id = u, None

        self.app_name = app_name
        self.unit_id = unit_id
        self.endpoint = endpoint

    @property
    def unit_name(self):
        if self.unit_id is None:
            raise ValueError(f"no unit id set on {self}")
        return f"{self.app_name}/{self.unit_id}"

    @property
    def full_endpoint_name(self):
        if not self.endpoint:
            raise ValueError(f"no endpoint set on {self}")
        return f"{self.app_name}:{self.endpoint}"

    def with_unit_id(self, unit_id: int) -> "RelationEndpointURL":
        ep = RelationEndpointURL(str(self))
        ep.unit_id = unit_id
        return ep


class InterfaceNotFoundError(RuntimeError):
    pass


def purge(data: dict):
    for key in _JUJU_KEYS:
        if key in data:
            del data[key]


@lru_cache
def _juju_status(*args, **kwargs):
    # to facilitate mocking in utests
    return juju_status(*args, **kwargs)


def _show_unit(
    unit_name, related_to: str = None, endpoint: str = None, model: str = None
):
    args = ["juju", "show-unit", "--format", "json"]
    if model:
        args.extend(["-m", model])
    if related_to:
        args.extend(["--related-unit", related_to])
    if endpoint:
        args.extend(["--endpoint", endpoint])
    args.append(unit_name)
    proc = JPopen(args)
    raw = proc.stdout.read().decode("utf-8").strip()
    return json.loads(raw)


def _find_model_if_CMR(app_name, current_model: str = None):
    """Find out if app_name is in current_model, if not, return the SAAS-exposed model it is in."""
    status = _juju_status(model=current_model, json=True)
    if app_name not in status["applications"]:
        logger.info(
            f"app_name {app_name!r} not found in "
            f"{current_model or '<current model>'!r}: this must be a CMR"
        )
        saas_url = status["application-endpoints"][app_name]["url"]
        other_model = saas_url.split(".")[0]
        logger.info(f"other app is in model {other_model!r}.")
        return other_model
    return current_model


def get_unit_info(
    unit_name: str,
    related_to: str = None,
    endpoint: str = None,
    model: str = None,
) -> dict:
    """Returns unit-info data structure.

     for example:

    traefik-k8s/0:
      opened-ports: []
      charm: local:focal/traefik-k8s-1
      leader: true
      relation-info:
      - endpoint: ingress-per-unit
        related-endpoint: ingress
        application-data:
          _supported_versions: '- v1'
        related-units:
          prometheus-k8s/0:
            in-scope: true
            data:
              egress-subnets: 10.152.183.150/32
              ingress-address: 10.152.183.150
              private-address: 10.152.183.150
      provider-id: traefik-k8s-0
      address: 10.1.232.144
    """
    signature = hash((unit_name, related_to, endpoint, model))
    if cached_data := _JUJU_DATA_CACHE.get(signature):
        return cached_data

    data = _show_unit(unit_name, related_to=related_to, endpoint=endpoint, model=model)
    if not data:
        raise ValueError(
            f"no unit info could be grabbed for {unit_name}; "
            f"are you sure it's a valid unit name?"
        )
    if unit_name not in data:
        raise KeyError(
            f"{unit_name} not in {data!r}: {unit_name} is not related to {related_to}"
        )

    unit_data = data[unit_name]
    _JUJU_DATA_CACHE[signature] = unit_data
    return unit_data


def get_relation_by_endpoint(
    relations,
    obj: RelationEndpointURL,
    other_obj: RelationEndpointURL,
    relation: "Relation",
):
    local_endpoint = obj.endpoint
    remote_endpoint = other_obj.endpoint

    matches = [
        r
        for r in relations
        if (
            (
                r["endpoint"] == local_endpoint
                and r["related-endpoint"] == remote_endpoint
            )
            or (
                r["endpoint"] == remote_endpoint
                and r["related-endpoint"] == local_endpoint
            )
        )
    ]
    if relation.type == RelationType.regular:
        matches = [
            r
            for r in matches
            if obj.unit_name in r.get("related-units", set())
            or r.get("cross-model", False)
        ]

    if not matches:
        raise ValueError(
            f"no relations found with remote endpoint={remote_endpoint!r} "
            f"and local endpoint={local_endpoint!r} "
            f"in {other_obj.app_name!r}"
        )
    if len(matches) > 1:
        raise ValueError(
            f"multiple relations found with remote endpoint={remote_endpoint!r} "
            f"and local endpoint={local_endpoint!r} "
            f"in {other_obj.app_name!r} (relations={matches})"
        )
    return matches[0]


@dataclass
class Metadata:
    scale: int
    units: Tuple[int, ...]
    leader_id: int


@dataclass
class AppRelationData:
    url: RelationEndpointURL
    relation_id: int

    meta: Metadata
    application_data: dict
    units_data: Dict[int, dict]

    model: str = None
    other_model: str = None


def get_metadata_from_status(
    endpoint: RelationEndpointURL,
    other_endpoint: RelationEndpointURL,
    model: str = None,
):
    status = _juju_status(model=model, json=True)
    # machine status json output apparently has no 'scale'... -_-
    app_status = status["applications"][endpoint.app_name]
    if app_status.get("subordinate-to"):
        units = {}
        other_app_meta = status["applications"][other_endpoint.app_name]
        other_app_meta.get("units")

        # todo: need to scavenge unit names from OTHER units' .subordinates field
        for app in status["applications"].values():
            for unit in app.get("units", {}).values():
                if subs := unit.get("subordinates"):
                    for subn, subv in subs.items():
                        if subn.startswith(endpoint.app_name):
                            units[subn] = subv

    elif app_status.get("units"):
        units = app_status["units"]

    else:
        raise ValueError(
            f"App {endpoint.app_name} has no units; is this a disintegrated "
            f"subordinate or an app that is not done deploying yet?"
        )

    scale = len(units)

    leader_id: int = -1
    unit_ids: List[int] = []

    for u, v in units.items():
        unit_id = int(u.split("/")[1])
        if v.get("leader", False):
            leader_id = unit_id
        unit_ids.append(unit_id)

    if leader_id == -1:
        if len(unit_ids) > 1:
            raise RuntimeError(
                f"could not identify leader among units {unit_ids}. "
                f"You might need to wait for all units to be allocated."
            )
        leader_id = unit_ids[0]
        logger.debug(
            f"no leader elected yet, guessing it's the only unit out there: {leader_id}"
        )
    return Metadata(scale, tuple(unit_ids), leader_id)


def get_units_and_meta(
    endpoint: RelationEndpointURL,
    other_endpoint: RelationEndpointURL,
    model: str = None,
):
    """Get app name and unit count from url; url is either `app_name/0` or `app_name`."""
    meta = get_metadata_from_status(endpoint, other_endpoint, model=model)
    if endpoint.unit_id is not None:
        units = (int(endpoint.unit_id),)
    else:
        units = meta.units
    return units, meta


def get_content(
    obj: RelationEndpointURL,
    other_obj: RelationEndpointURL,
    relation: "Relation",
    include_default_juju_keys: bool = False,
    model: str = None,
    other_model: str = None,
    assume_local: bool = False,
) -> AppRelationData:
    """Get the content of the databag of `obj`, as seen from `other_obj`."""
    # in k8s there's always a 0 unit, in machine that's not the case.
    # so even though we need 'any' remote unit name, we still need to query the status
    # to find out what units there are.
    status = _juju_status(model=model, json=True)
    if not other_model:
        if relation.type is RelationType.cross_model and assume_local:
            other_model = _find_model_if_CMR(other_obj.app_name, current_model=model)
        elif relation.type is RelationType.cross_model:
            other_model = None  # current model.
        else:
            other_model = model

    units, meta = get_units_and_meta(obj, other_obj, model)

    if other_model != model:
        logger.info(f"other app is in model {other_model!r}. Pulling status...")
        other_model_status = _juju_status(model=other_model, json=True)
        other_app_status = other_model_status["applications"][other_obj.app_name]
    else:
        other_app_status = status["applications"][other_obj.app_name]

    if relation.type == RelationType.peer:
        other_unit_id = units[0]

    elif primaries := other_app_status.get("subordinate-to"):
        # the remote end is a subordinate!
        # primary is our this_url.
        if obj.app_name in primaries:
            # this app is primary, other is subordinate
            sub_unit_found = ""
            for unit in status["applications"][obj.app_name]["units"].values():
                subs = unit["subordinates"]
                for sub in subs:
                    if sub.startswith(other_obj.app_name + "/"):
                        sub_unit_found = sub
                        break
                if sub_unit_found:
                    break

            if not sub_unit_found:
                raise RuntimeError(
                    f"unable to find primary with a subordinate unit of {other_obj.app_name}"
                )

        else:
            raise NotImplementedError(
                "relations between subordinates? Is that even a thing?"
            )

        other_unit_id = RelationEndpointURL(sub_unit_found).unit_id
    else:
        other_unit_id = RelationEndpointURL(
            next(iter(other_app_status["units"]))
        ).unit_id
        # we might have a different number of units and other units, and it doesn't
        # matter which 'other' we pass to get the databags for 'this one'.

    app_data = None

    if relation.type is RelationType.peer:
        # in peer relations, show-unit luckily reports 'local-unit', so we're good.
        obj.unit_id = units[0]
        units_data, app_data, r_id = get_databags(
            obj.with_unit_id(units[0]),  # any unit will do
            other_obj.with_unit_id(other_unit_id),  # any unit will do
            relation,
        )
        if not include_default_juju_keys:
            for unit_data in units_data.values():
                purge(unit_data)

    elif relation.type in [
        RelationType.regular,
        RelationType.subordinate,
        RelationType.cross_model,
    ]:
        units_data = {}
        r_id = None
        for unit_id in units:
            unit_data, app_data, r_id_ = get_databags(
                obj.with_unit_id(unit_id),
                other_obj.with_unit_id(other_unit_id),  # any unit will do
                other_model=other_model,
                relation=relation,
            )

            if r_id is not None:
                assert r_id == r_id_, f"mismatching relation IDs: {r_id, r_id_}"
            r_id = r_id_
            if not include_default_juju_keys:
                purge(unit_data)
            units_data[unit_id] = unit_data

    else:
        raise TypeError(relation.type)

    return AppRelationData(
        url=obj,
        meta=meta,
        application_data=app_data,
        units_data=units_data,
        relation_id=r_id,
        model=model,
        other_model=other_model,
    )


def get_databags(
    obj: RelationEndpointURL,
    other_obj: RelationEndpointURL,
    relation: "Relation",
    other_model: str = None,
):
    """Gets the databags of local unit and its leadership status.

    Given a remote unit and the remote endpoint name.
    """
    data = get_unit_info(
        other_obj.unit_name,
        obj.unit_name,
        endpoint=other_obj.endpoint,
        model=other_model,
    )
    relations = data.get("relation-info")
    if not relations:
        sys.exit(f"{other_obj} has no relations, or the unit is still allocating.")

    raw_data = get_relation_by_endpoint(
        relations,
        obj,
        other_obj,
        relation,
    )
    if relation.type == RelationType.peer:
        # we can grab them all in a single call.
        unit_data = {
            obj.unit_name: raw_data["local-unit"]["data"],
            **{
                u: raw_data["related-units"][u]["data"]
                for u in raw_data.get("related-units", set())
            },
        }
    elif relation.type == RelationType.cross_model:
        # assert raw_data.get("cross-model", False)
        # has 'cross-model' gone from the data at some point?
        unit_data = raw_data["local-unit"]["data"] or {}
    else:
        unit_data = raw_data["related-units"][obj.unit_name]["data"]

    app_data = raw_data.get("application-data", {})
    return unit_data, app_data, raw_data["relation-id"]


@dataclass
class RelationData:
    provider: AppRelationData
    requirer: AppRelationData


def get_peer_relation_data(
    *,
    endpoint: RelationEndpointURL,
    relation: Relation,
    include_default_juju_keys: bool = False,
    model: str = None,
) -> AppRelationData:
    return get_content(
        endpoint,
        endpoint,
        relation,
        include_default_juju_keys=include_default_juju_keys,
        model=model,
    )


def get_relation_data(
    *,
    provider_endpoint: RelationEndpointURL,
    requirer_endpoint: RelationEndpointURL,
    relation: "Relation",
    include_default_juju_keys: bool = False,
    model: str = None,
) -> RelationData:
    """Get relation databags for a juju relation.

    >>> get_relation_data('prometheus/0:ingress', 'traefik/1:ingress-per-unit')
    >>> get_relation_data('prometheus:ingress', 'traefik/1:ingress-per-unit')
    >>> get_relation_data('prometheus:ingress', 'traefik')
    >>> get_relation_data('prometheus', 'traefik')
    """
    provider_data = get_content(
        provider_endpoint,
        requirer_endpoint,
        relation,
        include_default_juju_keys,
        model=model,
        assume_local=True,
    )
    requirer_data = get_content(
        requirer_endpoint,
        provider_endpoint,
        relation,
        include_default_juju_keys,
        model=provider_data.other_model,
        other_model=model,
    )
    return RelationData(provider=provider_data, requirer=requirer_data)


def get_relations(model: str = None) -> List[Relation]:
    status = _juju_status(model=model)
    # get the interface name from juju status.
    raw_relations = _RELATIONS_RE.findall(status)

    relations = []
    for groups in raw_relations:
        relations.append(Relation(*groups))

    return relations


def _render_unit(obj: Optional[Tuple[int, Dict]], source: AppRelationData):
    unit_id, unit_data = obj
    unit_name = f"{source.url.app_name}/{unit_id}"
    return _render_databag(
        unit_name, unit_data, leader=(unit_id == source.meta.leader_id)
    )


def _render_databag(unit_name, dct, leader=False, hide_empty_databags: bool = False):
    from rich.panel import Panel  # noqa
    from rich.table import Table  # noqa
    from rich.text import Text  # noqa

    if not dct:
        if hide_empty_databags:
            return ""
        t = Text("<empty>", style="rgb(255,198,99)")
    else:
        t = Table(box=None)
        t.add_column(style="cyan not bold")  # keys
        t.add_column(style="white not bold")  # values
        for key in sorted(dct.keys()):
            t.add_row(key, dct[key])

    if leader:
        title = unit_name + "*"
        style = "rgb(54,176,224) bold"
    else:
        title = unit_name
        style = "white"

    p = Panel(t, title=title, title_align="left", style=style, border_style="white")
    return p


def _match_provider(rel: Relation, ep: Optional[RelationEndpointURL]):
    if not ep:
        return True
    return rel.provider == ep.app_name and (
        (not ep.endpoint) or rel.provider_endpoint == ep.endpoint
    )


def _match_requirer(rel: Relation, ep: Optional[RelationEndpointURL]):
    if not ep:
        return True
    return rel.requirer == ep.app_name and (
        (not ep.endpoint) or rel.requirer_endpoint == ep.endpoint
    )


def _match_endpoint(
    rel: Relation, ep1: RelationEndpointURL, ep2: Optional[RelationEndpointURL]
):
    if not ep2 or rel.type == RelationType.peer:
        # we could use _match_provider as well, they should be equivalent so long as the peer relation is consistent
        match_peer = _match_requirer(rel, ep1) and _match_requirer(rel, ep2)
        return match_peer, False

    if _match_provider(rel, ep1) and _match_requirer(rel, ep2):
        return True, False
    elif _match_provider(rel, ep2) and _match_requirer(rel, ep1):
        return True, True
    return False, False


def _coalesce_endpoint_and_n(
    endpoint1, endpoint2, n, model: Optional[str]
) -> Tuple[RelationEndpointURL, Optional[RelationEndpointURL], Relation]:
    if n is not None and (endpoint1 or endpoint2):
        raise RuntimeError(
            "Invalid usage: provide `n` or " "(`endpoint1` + `endpoint2`)."
        )

    relations = get_relations(model)

    if not relations:
        sys.exit(f"No relations found in model {model or '<current model>'!r}.")

    if n is not None:
        try:
            relation = relations[n]
        except IndexError:
            n_rel = len(relations)
            plur_rel = n_rel > 1

            def pl(condition, a="", b=""):
                """Conditional pluralizer."""
                return condition and a or b

            raise RuntimeError(
                f"There {pl(plur_rel, 'are', 'is')} only {n_rel} "
                f"relation{pl(plur_rel, 's')}. "
                f"Can't show index={n + 1}."
            )
        endpoint1 = RelationEndpointURL(
            f"{relation.provider}:{relation.provider_endpoint}"
        )
        endpoint2 = RelationEndpointURL(
            f"{relation.requirer}:{relation.requirer_endpoint}"
        )
        return endpoint1, endpoint2, relation

    ep_url_1 = RelationEndpointURL(endpoint1)
    ep_url_2 = RelationEndpointURL(endpoint2) if endpoint2 else None

    found: List[Relation] = []

    for relation in relations:
        match, flip = _match_endpoint(relation, ep_url_1, ep_url_2)
        if match:
            found.append(relation)
        if flip:
            ep_url_1, ep_url_2 = ep_url_2, ep_url_1

    if not found:
        msg = (
            f"No relation found with endpoints {ep_url_1!r} -> {ep_url_2!r} in "
            f"model {model or '<the current model>'!r}."
        )
        # if either provider or requirer are not apps in this model, OR either one have offers,
        # suspect a malformed CMR request
        status = _juju_status(model=model, json=True)
        apps = status["applications"]
        app1 = apps.get(ep_url_1.app_name)
        app2 = apps.get(ep_url_2.app_name)
        app_not_found = (
            ep_url_1.app_name if not app1 else ep_url_2.app_name if not app2 else None
        )
        if app_not_found:
            msg += (
                f" {app_not_found!r} not found in model {model or '<the current model>'!r}; \n"
                f"are you trying to show a CMR? If so, you need to \n"
                f"pass `-m <the model where {app_not_found!r} lives>`"
            )
            raise RuntimeError(msg)
        raise RuntimeError(msg)

    if len(found) > 1:
        found_str = "\n\t".join(
            (
                f"{r.provider}:{r.provider_endpoint}-->["
                f"{r.interface}]-->{r.requirer}:{r.requirer_endpoint}"
                for r in found
            )
        )
        raise RuntimeError(
            f"Multiple relations found matching specification {endpoint1!r} --> {endpoint2!r}; "
            f"please specify further. Found: \n\t{found_str}"
        )

    relation = found[0]
    ep_url_1.endpoint = relation.provider_endpoint
    if ep_url_2:
        ep_url_2.endpoint = relation.requirer_endpoint
    return ep_url_1, ep_url_2, relation


def _gather_entities(
    endpoint1: RelationEndpointURL,
    endpoint2: Optional[RelationEndpointURL],
    relation: Relation,
    model: Optional[str],
    include_default_juju_keys: bool = False,
) -> Tuple[AppRelationData, ...]:
    if relation.type == RelationType.peer:
        return (
            get_peer_relation_data(
                endpoint=endpoint1,
                include_default_juju_keys=include_default_juju_keys,
                model=model,
                relation=relation,
            ),
        )

    if not (endpoint1 and endpoint2):
        raise RuntimeError(
            f"Not a peer relation, but not enough endpoints provided: "
            f"{(endpoint1, endpoint2)} (expected 2)."
        )

    data = get_relation_data(
        provider_endpoint=endpoint1,
        requirer_endpoint=endpoint2,
        include_default_juju_keys=include_default_juju_keys,
        model=model,
        relation=relation,
    )
    return (data.provider, data.requirer)


async def render_relation(
    endpoint1: str = None,
    endpoint2: str = None,
    n: int = None,
    include_default_juju_keys: bool = False,
    hide_empty_databags: bool = False,
    model: str = None,
    format: Format = Format.auto,
):
    """Pprints relation databags for a juju relation
    >>> render_relation('prometheus/0:ingress', 'traefik/1:ingress-per-unit')
    """

    endpoint1, endpoint2, relation = _coalesce_endpoint_and_n(
        endpoint1, endpoint2, n, model
    )

    if relation.type is RelationType.regular:
        # still a chance it's a CMR.
        status = _juju_status(model=model, json=True)
        saas = status.get("application-endpoints", {}).keys()

        if endpoint1.app_name in saas or (endpoint2 and endpoint2.app_name in saas):
            relation.raw_type = "cross_model"

    entities = _gather_entities(
        endpoint1,
        endpoint2,
        relation,
        model=model,
        include_default_juju_keys=include_default_juju_keys,
    )

    if format == Format.auto:
        return _rich_format_table(
            entities, relation, hide_empty_databags=hide_empty_databags
        )

    elif format == Format.json:
        return _format_json(entities, relation.type)

    else:
        raise FormatUnavailable(format)


def _format_json(entities: Tuple[AppRelationData, ...], relation_type: RelationType):
    """Format as json."""

    @dataclasses.dataclass
    class Response:
        type: RelationType
        endpoints: Tuple[AppRelationData]

    resp = Response(relation_type, entities)
    return json.dumps(dataclasses.asdict(resp), indent=2)


def _rich_format_table(
    entities: Tuple[AppRelationData, ...],
    relation: Relation,
    hide_empty_databags: bool = True,
):
    """Format as a rich.table.Table."""
    from rich.columns import Columns  # noqa
    from rich.console import Console  # noqa
    from rich.table import Table  # noqa
    from rich.text import Text  # noqa

    is_cmr = relation.type is RelationType.cross_model
    if len(entities) == 1:
        relation_id = entities[0].relation_id
        header = f"peer relation (id: {relation_id})"
    else:
        if is_cmr:
            header = "cross-model relation"
            relation_id = None
        else:
            relation_id = entities[0].relation_id
            header = f"relation (id: {relation_id})"

    table = Table(title="relation data v0.6")

    table.add_column(
        justify="left",
        header=header,
        style="rgb(54,176,224) bold",
    )
    for entity in entities:
        table.add_column(justify="left", header=entity.url.app_name)  # meta/app_name

    is_peer = relation.type is RelationType.peer
    if is_cmr:
        type_ = "CMR"
    elif is_peer:
        type_ = "peer"
    elif relation.type is RelationType.subordinate:
        type_ = "subordinate"
    else:
        type_ = "regular"

    if is_peer:
        # omit the "=" in column 2
        table.add_row(Text("type", style="pink"), Text(type_, style="bold cyan"))
        table.add_row("interface", Text(relation.interface, style="blue bold"))
        table.add_row(
            "model", Text(entities[0].model or "the current model", style="yellow bold")
        )
        table.add_row(
            "relation ID", Text(str(relation_id), style="rgb(200,30,140) bold")
        )

    else:
        table.add_row(Text("type", style="pink"), Text(type_, style="bold cyan"), "=")
        table.add_row("interface", Text(relation.interface, style="blue bold"), "=")

        if not is_cmr:
            table.add_row(
                "model",
                Text(entities[0].model or "the current model", style="yellow bold"),
                "=",
            )
            table.add_row(
                "relation ID", Text(str(relation_id), style="rgb(200,30,140) bold"), "="
            )
        else:
            table.add_row(
                "model",
                Text(entities[0].model or "the current model", style="yellow bold"),
                Text(
                    entities[0].other_model or "the current model",
                    style="yellow bold",
                ),
            )

            table.add_row(
                "relation ID",
                *(
                    Text(str(entity.relation_id), style="rgb(200,30,140) bold")
                    for entity in entities
                ),
            )

    if not is_peer:
        table.add_row(
            "role", *(Text(role, style="white") for role in ["provider", "requirer"])
        )

    table.add_row(
        "endpoint",
        *(Text(entity.url.endpoint, style="blue bold") for entity in entities),
    )
    table.add_row(
        "leader unit",
        *(Text(str(entity.meta.leader_id), style="red") for entity in entities),
    )

    table.rows[-1].end_section = True

    table.add_row(
        "application data",
        *(
            _render_databag(
                "", entity.application_data, hide_empty_databags=hide_empty_databags
            )
            for entity in entities
        ),
    )

    unit_databags = []

    for i, entity in enumerate(entities):
        units = entity.units_data.items()
        if len(unit_databags) < (i + 1):
            unit_databags.append([])
        bucket = unit_databags[i]
        for _, (unit, data) in enumerate(units):
            # if unit:
            bucket.append(_render_unit((unit, data), entity))

    if any(any(x) for x in unit_databags):
        table.add_row("unit data", *(Columns(x) for x in unit_databags))

    return table


def sync_show_relation(
    endpoint1: str = typer.Argument(
        None,
        help="First endpoint. It's a string in the format "
        "<unit_name>:<relation_name>; example: mongodb/1:ingress.",
    ),
    endpoint2: str = typer.Argument(
        None,
        help="Second endpoint. It's a string in the format "
        "<unit_name>:<relation_name>; example: traefik/3:ingress."
        "Can be omitted for peer relations.",
    ),
    n: int = typer.Option(
        None,
        "-n",
        help="Relation number. "
        "An ID corresponding to the row in juj status --relations."
        "Alternative to passing endpoint1(+endpoint2).",
    ),
    show_juju_keys: bool = typer.Option(
        False,
        "--show-juju-keys",
        "-s",
        help="Show from the unit databags the data provided by juju: "
        "ingress-address, private-address, egress-subnets.",
    ),
    hide_empty_databags: bool = typer.Option(
        False, "--hide-empty", "-h", help="Do not show empty databags."
    ),
    watch: bool = typer.Option(
        False, "-w", "--watch", help="Keep watching for changes."
    ),
    model: str = typer.Option(None, "-m", "--model", help="Which model to look into."),
    color: Optional[str] = ColorOption,
    format: Format = FormatOption,
):
    """Displays the databags of two applications or units involved in a relation.

    Examples:

    $ jhack utils show-relation my_app/0:relation_name other_app/2:other_name

    $ jhack utils show-relation my_app:relation_name other_app/2:other_name

    $ jhack utils show-relation my_app:relation_name other_app:other_name
    """
    return _sync_show_relation(
        endpoint1=endpoint1,
        endpoint2=endpoint2,
        n=n,
        show_juju_keys=show_juju_keys,
        hide_empty_databags=hide_empty_databags,
        watch=watch,
        model=model,
        color=color,
        format=format,
    )


def _sync_show_relation(
    endpoint1: str = None,
    endpoint2: str = None,
    n: int = None,
    show_juju_keys: bool = False,
    hide_empty_databags: bool = False,
    model: str = None,
    watch: bool = False,
    color: RichSupportedColorOptions = "auto",
    format: FormatOption = "auto",
):
    try:
        import rich  # noqa
    except ImportError:
        print("using this command requires rich.")
        return

    from rich.console import Console

    if color == "no":
        color = None
    console = Console(color_system=color)

    while True:
        start = time.time()

        table = asyncio.run(
            render_relation(
                endpoint1,
                endpoint2,
                n=n,
                include_default_juju_keys=show_juju_keys,
                hide_empty_databags=hide_empty_databags,
                model=model,
                format=format,
            )
        )

        if table is None:
            return

        if watch:
            elapsed = time.time() - start
            if elapsed < 1:
                time.sleep(1.5 - elapsed)
                _JUJU_DATA_CACHE.clear()
            # we clear RIGHT BEFORE printing to prevent flickering
            console.clear()
        console.print(table)

        if not watch:
            return


if __name__ == "__main__":
    _sync_show_relation(n=0)
