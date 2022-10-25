import asyncio
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

import typer
import yaml

from jhack.helpers import ColorOption, JPopen, RichSupportedColorOptions, juju_status
from jhack.logger import logger

logger = logger.getChild(__file__)

_JUJU_DATA_CACHE = {}
_JUJU_KEYS = ("egress-subnets", "ingress-address", "private-address")


def get_interface(
    raw_status, app_name, relation_name, other_app_name, other_relation_name
):
    # get the interface name from juju status.
    relations_re = re.compile(
        r"([\w\-]+):([\w\-]+)\s+([\w\-]+):([\w\-]+)\s+([\w\-]+)\s+([\w\-]+).*"
    )
    relations = relations_re.findall(raw_status)

    endpoint1 = app_name, relation_name
    endpoint2 = other_app_name, other_relation_name

    for app1, rname1, app2, rname2, interface, _ in relations:
        ep1 = app1, rname1
        ep2 = app2, rname2
        if (ep1 == endpoint1 and ep2 == endpoint2) or (
            ep1 == endpoint2 and ep2 == endpoint1
        ):
            return interface

    raise RuntimeError(
        f"unable to find interface for "
        f"{app_name}:{relation_name} <--> "
        f"{other_app_name}:{other_relation_name}"
    )


def purge(data: dict):
    for key in _JUJU_KEYS:
        if key in data:
            del data[key]


def _juju_status(*args, **kwargs):
    # to facilitate mocking in utests
    return juju_status(*args, **kwargs)


def _show_unit(unit_name, model: str = None):
    if model:
        proc = JPopen(f"juju show-unit -m {model} {unit_name}".split())
    else:
        proc = JPopen(f"juju show-unit {unit_name}".split())
    return proc.stdout.read().decode("utf-8").strip()


def get_unit_info(unit_name: str, model: str = None) -> dict:
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
    if cached_data := _JUJU_DATA_CACHE.get(unit_name):
        return cached_data

    raw_data = _show_unit(unit_name, model=model)
    if not raw_data:
        raise ValueError(
            f"no unit info could be grabbed for {unit_name}; "
            f"are you sure it's a valid unit name?"
        )

    data = yaml.safe_load(raw_data)
    if unit_name not in data:
        raise KeyError(f"{unit_name} not in {data!r}")

    unit_data = data[unit_name]
    _JUJU_DATA_CACHE[unit_name] = unit_data
    return unit_data


def get_relation_by_endpoint(
    relations, local_endpoint, remote_endpoint, remote_obj, peer: bool
):
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
    if not peer:
        matches = [r for r in matches if remote_obj in r["related-units"]]

    if not matches:
        raise ValueError(
            f"no relations found with remote endpoint={remote_endpoint!r} "
            f"and local endpoint={local_endpoint!r} "
            f"in {remote_obj!r}"
        )
    if len(matches) > 1:
        raise ValueError(
            f"multiple relations found with remote endpoint={remote_endpoint!r} "
            f"and local endpoint={local_endpoint!r} "
            f"in {remote_obj!r} (relations={matches})"
        )
    return matches[0]


@dataclass
class Metadata:
    scale: int
    units: Tuple[int, ...]
    leader_id: int
    interface: str


@dataclass
class AppRelationData:
    app_name: str
    relation_id: int
    meta: Metadata
    endpoint: str
    application_data: dict
    units_data: Dict[int, dict]


def get_metadata_from_status(
    app_name, relation_name, other_app_name, other_relation_name, model: str = None
):
    # line example: traefik-k8s           active      3  traefik-k8s             0  10.152.183.73  no
    status = _juju_status(app_name, model=model, json=True)
    # machine status json output apparently has no 'scale'... -_-
    scale = len(status["applications"][app_name]["units"])

    leader_id: int = None
    unit_ids: List[int] = []

    for u, v in status["applications"][app_name]["units"].items():
        unit_id = int(u.split("/")[1])
        if v.get("leader", False):
            leader_id = unit_id
        unit_ids.append(unit_id)
    if leader_id is None:
        if len(unit_ids) > 1:
            raise RuntimeError(
                f"could not identify leader among units {unit_ids}. "
                f"You might need to wait for all units to be allocated."
            )
        leader_id = unit_ids[0]
        logger.debug(
            f"no leader elected yet, guessing it's the only unit out there: {leader_id}"
        )

    # we gotta do this because json status --format json does not include the interface
    raw_text_status = _juju_status(app_name, model=model)

    interface = get_interface(
        raw_text_status,
        app_name=app_name,
        relation_name=relation_name,
        other_app_name=other_app_name,
        other_relation_name=other_relation_name,
    )
    return Metadata(scale, tuple(unit_ids), leader_id, interface)


def get_app_name_and_units(
    url, relation_name, other_app_name, other_relation_name, model: str = None
):
    """Get app name and unit count from url; url is either `app_name/0` or `app_name`."""
    app_name, unit_id = url.split("/") if "/" in url else (url, None)

    meta = get_metadata_from_status(
        app_name, relation_name, other_app_name, other_relation_name, model=model
    )
    if unit_id:
        units = (int(unit_id),)
    else:
        units = meta.units
    return app_name, units, meta


def get_content(
    obj: str,
    other_obj,
    include_default_juju_keys: bool = False,
    model: str = None,
    peer: bool = False,
) -> AppRelationData:
    """Get the content of the databag of `obj`, as seen from `other_obj`."""
    url, endpoint = obj.split(":")
    other_url, other_endpoint = other_obj.split(":")

    other_app_name, _ = other_url.split("/") if "/" in other_url else (other_url, None)

    app_name, units, meta = get_app_name_and_units(
        url, endpoint, other_app_name, other_endpoint, model
    )

    # in k8s there's always a 0 unit, in machine that's not the case.
    # so even though we need 'any' remote unit name, we still need to query the status
    # to find out what units there are.
    status = _juju_status(other_app_name, model=model, json=True)
    other_unit_name = next(iter(status["applications"][other_app_name]["units"]))
    # we might have a different number of units and other units, and it doesn't
    # matter which 'other' we pass to get the databags for 'this one'.
    # in peer relations, show-unit luckily reports 'local-unit', so we're good.

    leader_unit_data = None
    app_data = None
    units_data = {}
    r_id = None
    for unit_id in units:
        unit_name = f"{app_name}/{unit_id}"
        unit_data, app_data, r_id_ = get_databags(
            unit_name, other_unit_name, endpoint, other_endpoint, model=model, peer=peer
        )

        if r_id is not None:
            assert r_id == r_id_, f"mismatching relation IDs: {r_id, r_id_}"
        r_id = r_id_

        if not include_default_juju_keys:
            purge(unit_data)
        units_data[unit_id] = unit_data

    return AppRelationData(
        app_name=app_name,
        meta=meta,
        endpoint=endpoint,
        application_data=app_data,
        units_data=units_data,
        relation_id=r_id,
    )


def get_databags(
    local_unit,
    remote_unit,
    local_endpoint,
    remote_endpoint,
    model: str = None,
    peer: bool = False,
):
    """Gets the databags of local unit and its leadership status.

    Given a remote unit and the remote endpoint name.
    """
    local_data = get_unit_info(local_unit, model=model)
    data = get_unit_info(remote_unit, model=model)
    relation_info = data.get("relation-info")
    if not relation_info:
        raise RuntimeError(f"{remote_unit} has no relations")

    raw_data = get_relation_by_endpoint(
        relation_info, local_endpoint, remote_endpoint, local_unit, peer=peer
    )
    if peer:
        unit_data = raw_data["local-unit"]["data"]
    else:
        unit_data = raw_data["related-units"][local_unit]["data"]
    app_data = raw_data["application-data"]
    return unit_data, app_data, raw_data["relation-id"]


@dataclass
class RelationData:
    provider: AppRelationData
    requirer: AppRelationData


def get_peer_relation_data(
    *, endpoint: str, include_default_juju_keys: bool = False, model: str = None
):
    return get_content(
        endpoint, endpoint, include_default_juju_keys, model=model, peer=True
    )


def get_relation_data(
    *,
    provider_endpoint: str,
    requirer_endpoint: str,
    include_default_juju_keys: bool = False,
    model: str = None,
):
    """Get relation databags for a juju relation.

    >>> get_relation_data('prometheus/0:ingress', 'traefik/1:ingress-per-unit')
    """
    provider_data = get_content(
        provider_endpoint, requirer_endpoint, include_default_juju_keys, model=model
    )
    requirer_data = get_content(
        requirer_endpoint, provider_endpoint, include_default_juju_keys, model=model
    )

    # sanity check: the two IDs should be identical
    if not provider_data.relation_id == requirer_data.relation_id:
        logger.warning(
            f"provider relation id {provider_data.relation_id} "
            f"not the same as requirer relation id: {requirer_data.relation_id}"
        )

    return RelationData(provider=provider_data, requirer=requirer_data)


@dataclass
class Relation:
    provider: str
    requirer: str
    interface: str
    type: str
    message: str = None


def get_relations(model: str = None) -> List[Relation]:
    status = _juju_status("", model=model)
    relations = None
    for line in status.split("\n"):
        if line.startswith("Relation provider"):
            relations = []
            continue
        if relations is not None:
            if not line.strip():
                break  # end of list
            relations.append(Relation(*(x.strip() for x in line.split(" ") if x)))
    return relations


def _render_unit(obj: Optional[Tuple[int, Dict]], source: AppRelationData):
    unit_id, unit_data = obj
    unit_name = f"{source.app_name}/{unit_id}"
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


async def render_relation(
    endpoint1: str = None,
    endpoint2: str = None,
    n: int = None,
    include_default_juju_keys: bool = False,
    hide_empty_databags: bool = False,
    model: str = None,
):
    """Pprints relation databags for a juju relation
    >>> render_relation('prometheus/0:ingress', 'traefik/1:ingress-per-unit')
    """

    if n is not None and (endpoint1 or endpoint2):
        raise RuntimeError(
            "Invalid usage: provide `n` or " "(`endpoint1` + `endpoint2`)."
        )

    is_peer = False

    if n is not None:
        relations = get_relations(model)
        if not relations:
            print(f"No relations found in model {model!r}.")
            return
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
                f"Can't show index={n+1}."
            )
        endpoint1 = relation.provider

        if relation.type != "peer":
            endpoint2 = relation.requirer

    if endpoint1 and endpoint2 is None:
        is_peer = True

        data = get_peer_relation_data(
            endpoint=endpoint1,
            include_default_juju_keys=include_default_juju_keys,
            model=model,
        )
        relation_id = data.relation_id
        entities = (data,)

    else:
        if not (endpoint1 and endpoint2):
            raise RuntimeError("invalid usage: provide two endpoints.")

        data = get_relation_data(
            provider_endpoint=endpoint1,
            requirer_endpoint=endpoint2,
            include_default_juju_keys=include_default_juju_keys,
            model=model,
        )

        # same as provider's
        relation_id = data.requirer.relation_id
        entities = (data.requirer, data.provider)

    from rich.columns import Columns  # noqa
    from rich.console import Console  # noqa
    from rich.table import Table  # noqa
    from rich.text import Text  # noqa

    table = Table(title="relation data v0.3")

    table.add_column(
        justify="left",
        header=f"relation (id: {relation_id})",
        style="rgb(54,176,224) bold",
    )
    for entity in entities:
        table.add_column(justify="left", header=entity.app_name)  # meta/app_name

    table.add_row(
        "relation name", *(Text(entity.endpoint, style="green") for entity in entities)
    )
    table.add_row(
        "interface",
        *(Text(entity.meta.interface, style="blue bold") for entity in entities),
    )
    table.add_row(
        "leader unit",
        *(Text(str(entity.meta.leader_id), style="red") for entity in entities),
    )
    if is_peer:
        table.add_row(Text("type", style="pink"), Text("peer", style="bold cyan"))
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
    _sync_show_relation(n=1, watch=True)
