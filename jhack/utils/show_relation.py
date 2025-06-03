import asyncio
import dataclasses
import json
import re
import sys
import time
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

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

_CACHING = True
"""Toggle caching for juju api calls."""

_JUJU_DATA_CACHE = {}

_JUJU_KEYS = ("egress-subnets", "ingress-address", "private-address")
_UNIT_ID_RE = re.compile(r"/\d")
_RELATIONS_RE = re.compile(r"([\w\-]+):([\w\-]+)\s+([\w\-]+):([\w\-]+)\s+([\w\-]+)\s+([\w\-]+).*")

# strings in the format: mk8s:admin/foo.parca
_SAAS_URL_RE = re.compile(r"([\w\-]+):([\w\-]+)/([\w\-]+).([\w\-]+)")


class RelationType(str, Enum):
    regular = "regular"
    subordinate = "subordinate"
    peer = "peer"
    cross_model = "cross_model"


class RelationEndpointURL(str):
    # a string in the format APP_NAME:ENDPOINT_NAME
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


@dataclass
class Saas:
    """Represents a SAAS in the current model."""

    controller: str
    owner: str
    model: str
    app: str  # app name in model of origin


@dataclass
class Relation:
    """Represents a juju-status Relation data structure."""

    provider: str
    provider_endpoint: str
    requirer: str
    requirer_endpoint: str
    interface: str
    raw_type: str

    provider_saas_url: Saas = None
    requirer_saas_url: Saas = None

    @property
    def provider_url(self) -> RelationEndpointURL:
        return RelationEndpointURL(
            f"{self.provider_saas_url.app if self.provider_saas_url else self.provider}:{self.provider_endpoint}"
        )

    @property
    def requirer_url(self) -> RelationEndpointURL:
        return RelationEndpointURL(
            f"{self.requirer_saas_url.app if self.requirer_saas_url else self.requirer}:{self.requirer_endpoint}"
        )

    @property
    def type(self) -> RelationType:
        return RelationType(self.raw_type)


class InterfaceNotFoundError(RuntimeError):
    pass


def purge(data: dict):
    for key in _JUJU_KEYS:
        if key in data:
            del data[key]


@lru_cache
def _cached_juju_status(*args, **kwargs):
    return juju_status(*args, **kwargs)


def _juju_status(*args, **kwargs):
    # to facilitate mocking in utests
    if _CACHING:
        return _cached_juju_status(*args, **kwargs)
    return juju_status(*args, **kwargs)


def _show_unit(unit_name, related_to: str = None, endpoint: str = None, model: str = None):
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


def _get_unit_info(
    unit_name: str,
    related_to: str = None,
    endpoint: str = None,
    model: str = None,
) -> dict:
    data = _show_unit(unit_name, related_to=related_to, endpoint=endpoint, model=model)
    if not data:
        raise ValueError(
            f"no unit info could be grabbed for {unit_name}; are you sure it's a valid unit name?"
        )
    if unit_name not in data:
        raise KeyError(f"{unit_name} not in {data!r}: {unit_name} is not related to {related_to}")

    unit_data = data[unit_name]
    return unit_data


@lru_cache
def _cached_get_unit_info(
    unit_name: str,
    related_to: str = None,
    endpoint: str = None,
    model: str = None,
) -> dict:
    return _get_unit_info(unit_name, related_to, endpoint, model)


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
    if _CACHING:
        return _cached_get_unit_info(unit_name, related_to, endpoint, model)
    return _get_unit_info(unit_name, related_to, endpoint, model)


def get_relation_by_endpoint(
    relations: List[Dict[str, Any]],
    obj: RelationEndpointURL,
    other_obj: RelationEndpointURL,
    relation: "Relation",
):
    if relation.type == RelationType.peer:
        matches = [r for r in relations if r["endpoint"] == relation.requirer_endpoint]
        if len(matches) != 1:
            raise ValueError(f"Would expect a single peer on {relation.requirer_endpoint}")
        return matches[0]

    local_endpoint = obj.endpoint
    remote_endpoint = other_obj.endpoint

    matches = []
    for r in relations:
        if (r["endpoint"] == local_endpoint or not local_endpoint) and (
            r["related-endpoint"] == remote_endpoint or not remote_endpoint
        ):
            candidate = r
        elif (r["endpoint"] == remote_endpoint or not remote_endpoint) and (
            r["related-endpoint"] == local_endpoint or not local_endpoint
        ):
            candidate = r
        else:
            continue

        if relation.type == RelationType.cross_model and candidate.get("cross-model"):
            matches.append(candidate)

        elif obj.unit_name in candidate.get("related-units", set()):
            matches.append(candidate)

    if relation.type == RelationType.regular:
        matches = [
            r
            for r in matches
            if obj.unit_name in r.get("related-units", set()) and not r.get("cross-model")
        ]

    if not matches:
        raise ValueError(
            f"no relations found with remote endpoint={remote_endpoint!r} "
            f"and local endpoint={local_endpoint!r} "
            f"in {other_obj.app_name!r}"
        )
    if len(matches) > 1:
        # fixme: if these are CMRs, it could be https://github.com/canonical/jhack/issues/129
        raise ValueError(
            f"multiple relations ({len(matches)}) found with remote endpoint={remote_endpoint!r} "
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


def get_metadata_from_status(
    endpoint: RelationEndpointURL,
    model: str = None,
):
    status = _juju_status(model=model, json=True)
    # machine status json output apparently has no 'scale'... -_-
    app_status = status["applications"][endpoint.app_name]
    if app_status.get("subordinate-to"):
        units = {}
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
        logger.debug(f"no leader elected yet, guessing it's the only unit out there: {leader_id}")
    return Metadata(scale, tuple(unit_ids), leader_id)


def get_units_and_meta(
    endpoint: RelationEndpointURL,
    model: str = None,
):
    """Get app name and unit count from url; url is either `app_name/0` or `app_name`."""
    meta = get_metadata_from_status(endpoint, model=model)
    if endpoint.unit_id is not None:
        units = (int(endpoint.unit_id),)
    else:
        units = meta.units
    return units, meta


def get_databag_content(
    obj: RelationEndpointURL,
    other_obj: RelationEndpointURL,
    relation: "Relation",
    obj_model: str,
    other_obj_model: str,
    include_default_juju_keys: bool = False,
) -> AppRelationData:
    """Get the content of the databag of `obj`, as seen from `other_obj`."""
    # in k8s there's always a 0 unit, in machine that's not the case.
    # so even though we need 'any' remote unit name, we still need to query the status
    # to find out what units there are.
    status = _juju_status(model=other_obj_model, json=True)
    units, meta = get_units_and_meta(other_obj, other_obj_model)
    other_app_status = status["applications"][other_obj.app_name]

    if primaries := other_app_status.get("subordinate-to"):
        # the remote end is a subordinate!
        # primary is our `obj`.
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
            other_unit_id = RelationEndpointURL(sub_unit_found).unit_id

        else:
            # this app is sub and related to some other app or viceversa
            other_units = other_app_status.get("units")
            if other_units:
                other_unit_id = RelationEndpointURL(next(iter(other_units))).unit_id
            else:
                # we need to get the units of the primary.
                primary_units = status["applications"][primaries[0]]["units"]
                other_unit_id = RelationEndpointURL(next(iter(primary_units))).unit_id

    else:
        other_unit_id = RelationEndpointURL(next(iter(other_app_status["units"]))).unit_id
        # we might have a different number of units and other units, and it doesn't
        # matter which 'other' we pass to get the databags for 'this one'.

    app_data = None

    units_data = {}
    r_id = None
    for unit_id in units:
        obj_with_uid = obj.with_unit_id(unit_id)

        unit_data, app_data, r_id_ = _get_databags(
            obj_with_uid,
            other_obj.with_unit_id(other_unit_id),  # any unit will do
            model=other_obj_model,
            relation=relation,
        )

        if r_id is not None:
            assert r_id == r_id_, f"mismatching relation IDs: {r_id, r_id_}"
        r_id = r_id_
        if not include_default_juju_keys:
            purge(unit_data)
        units_data[obj_with_uid.unit_name] = unit_data

    return AppRelationData(
        url=obj,
        meta=meta,
        application_data=app_data,
        units_data=units_data,
        relation_id=r_id,
        model=obj_model,
    )


def _get_databags(
    obj: RelationEndpointURL,
    other_obj: RelationEndpointURL,
    relation: "Relation",
    model: str = None,
):
    """Gets the databags of local unit and its leadership status.

    Given a remote unit and the remote endpoint name.
    """
    data = get_unit_info(
        other_obj.unit_name,
        # obj.unit_name,
        # endpoint=other_obj.endpoint,
        model=model,
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
    relation: Relation,
    include_default_juju_keys: bool = False,
    model: str = None,
) -> AppRelationData:
    obj = relation.requirer_url

    units, meta = get_units_and_meta(obj, model)

    # in peer relations, show-unit luckily reports 'local-unit', so we're good.
    any_unit = obj.with_unit_id(units[0])  # any unit will do
    units_data, app_data, r_id = _get_databags(
        any_unit,
        any_unit,
        relation,
    )

    if not include_default_juju_keys:
        for unit_data in units_data.values():
            purge(unit_data)

    return AppRelationData(
        url=obj,
        meta=meta,
        application_data=app_data,
        units_data=units_data,
        relation_id=r_id,
        model=model,
    )


def get_relation_data(
    *,
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
    requirer_model = relation.requirer_saas_url.model if relation.requirer_saas_url else model
    provider_model = relation.provider_saas_url.model if relation.provider_saas_url else model

    provider_data = get_databag_content(
        obj=relation.provider_url,
        obj_model=provider_model,
        other_obj=relation.requirer_url,
        other_obj_model=requirer_model,
        relation=relation,
        include_default_juju_keys=include_default_juju_keys,
    )

    # flip around prov/req
    requirer_data = get_databag_content(
        obj=relation.requirer_url,
        obj_model=requirer_model,
        other_obj=relation.provider_url,
        other_obj_model=provider_model,
        relation=relation,
        include_default_juju_keys=include_default_juju_keys,
    )
    return RelationData(provider=provider_data, requirer=requirer_data)


def get_relations(model: str = None) -> List[Relation]:
    status = _juju_status(model=model)
    # get the interface name from juju status. We have to do this horrible regex parsing because the interface
    # field isn't presented in the json/yaml output (in some juju client versions) -_-
    raw_relations = _RELATIONS_RE.findall(status)

    json_status = _juju_status(json=True)
    saas_apps = json_status.get("application-endpoints", [])

    relations = []
    for groups in raw_relations:
        relation = Relation(*groups)

        if relation.provider in saas_apps:
            relation.raw_type = RelationType.cross_model.value
            url = _SAAS_URL_RE.findall(saas_apps[relation.provider]["url"])[0]
            relation.provider_saas_url = Saas(*url)

        if relation.requirer in saas_apps:
            relation.raw_type = RelationType.cross_model.value
            url = _SAAS_URL_RE.findall(saas_apps[relation.requirer]["url"])[0]
            relation.requirer_saas_url = Saas(*url)

        relations.append(relation)

    return relations


def _render_unit(obj: Optional[Tuple[int, Dict]], source: AppRelationData):
    unit_name, unit_data = obj
    unit_id = int(unit_name.split("/")[1])
    return _render_databag(unit_name, unit_data, leader=(unit_id == source.meta.leader_id))


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


def _match_endpoint(rel: Relation, ep1: RelationEndpointURL, ep2: Optional[RelationEndpointURL]):
    if rel.type is RelationType.peer:
        # we could use _match_provider as well, they should be equivalent
        # so long as the peer relation is consistent
        match_peer = _match_requirer(rel, ep1) and _match_requirer(rel, ep2)
        return match_peer, False

    if _match_provider(rel, ep1) and _match_requirer(rel, ep2):
        return True, False
    elif _match_provider(rel, ep2) and _match_requirer(rel, ep1):
        return True, True
    return False, False


def _coalesce_endpoint_and_n(endpoint1, endpoint2, n, model: Optional[str]) -> Relation:
    """Determine what relation we're talking about."""
    if n is not None and (endpoint1 or endpoint2):
        raise RuntimeError("Invalid usage: provide `n` or (`endpoint1` + `endpoint2`).")

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
        return relation

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
            f"No relation found matching spec {ep_url_1!r} -> {ep_url_2!r} in "
            f"model {model or '<the current model>'!r}. Verify that you "
            f"haven't misspelled any app/saas/endpoint names."
        )
        # if either provider or requirer are not apps in this model, OR either one have offers,
        # suspect a malformed CMR request
        status = _juju_status(model=model, json=True)
        apps = status["applications"]

        apps_not_found = []
        for ep_url in (ep_url_1, ep_url_2):
            if ep_url and not apps.get(ep_url.app_name):
                apps_not_found.append(ep_url.app_name)

        if apps_not_found:
            msg += (
                f" apps {apps_not_found!r} not found in model {model or '<the current model>'!r}."
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
            f"Multiple relations found matching spec {endpoint1!r} -> {endpoint2!r}; "
            f"please specify further. Found: \n\t{found_str}"
        )

    relation = found[0]
    return relation


def _gather_entities(
    relation: Relation,
    model: Optional[str],
    include_default_juju_keys: bool = False,
) -> Tuple[AppRelationData, ...]:
    if relation.type == RelationType.peer:
        return (
            get_peer_relation_data(
                include_default_juju_keys=include_default_juju_keys,
                model=model,
                relation=relation,
            ),
        )

    data = get_relation_data(
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

    relation = _coalesce_endpoint_and_n(endpoint1, endpoint2, n, model)

    entities = _gather_entities(
        relation,
        model=model,
        include_default_juju_keys=include_default_juju_keys,
    )

    if format == Format.auto:
        return _rich_format_table(entities, relation, hide_empty_databags=hide_empty_databags)

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
    for alias, entity in zip((relation.provider, relation.requirer), entities):
        app_name = entity.url.app_name
        if alias == app_name:
            header = app_name
        else:
            header = f"{app_name}({alias})"
        table.add_column(justify="left", header=header)  # meta/app_name

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
        table.add_row("model", Text(entities[0].model or "the current model", style="yellow bold"))
        table.add_row("relation ID", Text(str(relation_id), style="rgb(200,30,140) bold"))

    else:
        table.add_row(Text("type", style="pink"), Text(type_, style="bold cyan"), "=")
        table.add_row("interface", Text(relation.interface, style="blue bold"), "=")

        if is_cmr:
            table.add_row(
                "model",
                Text(entities[0].model or "the current model", style="yellow bold"),
                Text(entities[1].model or "the current model", style="yellow bold"),
            )

            table.add_row(
                "relation ID",
                *(
                    Text(str(entity.relation_id), style="rgb(200,30,140) bold")
                    for entity in entities
                ),
            )
        else:
            table.add_row(
                "model",
                Text(entities[0].model or "the current model", style="yellow bold"),
                "=",
            )
            table.add_row("relation ID", Text(str(relation_id), style="rgb(200,30,140) bold"), "=")

    if not is_peer:
        table.add_row("role", *(Text(role, style="white") for role in ["provider", "requirer"]))

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
            _render_databag("", entity.application_data, hide_empty_databags=hide_empty_databags)
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
        "An ID corresponding to the row in ``juju status --relations``."
        "Alternative to passing endpoint1 (+endpoint2).",
    ),
    show_juju_keys: bool = typer.Option(
        False,
        "--show-juju-keys",
        "-s",
        help="Show in the unit databags the data provided by juju: "
        "ingress-address, private-address, egress-subnets.",
    ),
    hide_empty_databags: bool = typer.Option(
        False, "--hide-empty", "-h", help="Do not show empty databags."
    ),
    watch: bool = typer.Option(False, "-w", "--watch", help="Keep watching for changes."),
    model: str = typer.Option(None, "-m", "--model", help="Which model to look into."),
    color: Optional[str] = ColorOption,
    format: Format = FormatOption,
):
    """Displays the databags of two applications or units involved in a relation.

    Examples:\n
    - ``$ jhack utils show-relation my_app other_app`` - if there only is one integration\n
    - ``$ jhack utils show-relation my_app:relation_name other_app`` - if there are multiple\n
    - ``$ jhack utils show-relation my_app/1:relation_name other_app/2`` -
      only show these specific units' databags\n


    Should work seamlessly for CMRs, peer, and subordinate relations
        Examples:\n
    - ``$ jhack utils show-relation my_app:peers`` - peer relation\n
    - ``$ jhack utils show-relation my_app:foo cross_model_app:bar`` - CMRs\n
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
            global _CACHING
            _CACHING = False
            logger.info("running in watch-mode: caching DISABLED")

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
    _sync_show_relation(
        "pgql:cos-o",
    )
