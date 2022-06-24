import asyncio
import re
import time
from dataclasses import dataclass
from itertools import zip_longest
from subprocess import Popen, PIPE
from typing import Dict, Optional, Tuple

import typer
import yaml

_JUJU_DATA_CACHE = {}
_JUJU_KEYS = ("egress-subnets", "ingress-address", "private-address")


def purge(data: dict):
    for key in _JUJU_KEYS:
        if key in data:
            del data[key]


def get_unit_info(unit_name: str) -> dict:
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

    proc = Popen(f"juju show-unit {unit_name}".split(" "), stdout=PIPE)
    raw_data = proc.stdout.read().decode("utf-8").strip()
    if not raw_data:
        raise ValueError(
            f"no unit info could be grabbed for {unit_name}; "
            f"are you sure it's a valid unit name?"
        )

    data = yaml.safe_load(raw_data)
    if unit_name not in data:
        raise KeyError(unit_name, f"not in {data!r}")

    unit_data = data[unit_name]
    _JUJU_DATA_CACHE[unit_name] = unit_data
    return unit_data


def get_relation_by_endpoint(relations, local_endpoint, remote_endpoint,
                             remote_obj):
    matches = [
        r for r in relations if
        ((r["endpoint"] == local_endpoint and
          r["related-endpoint"] == remote_endpoint) or
         (r["endpoint"] == remote_endpoint and
          r["related-endpoint"] == local_endpoint)) and
        remote_obj in r["related-units"]
    ]
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
    leader_id: int
    interface: str


@dataclass
class AppRelationData:
    app_name: str
    meta: Metadata
    endpoint: str
    application_data: dict
    units_data: Dict[int, dict]


def get_metadata_from_status(app_name, relation_name, other_app_name,
                             other_relation_name):
    # line example: traefik-k8s           active      3  traefik-k8s             0  10.152.183.73  no
    proc = Popen(f'juju status {app_name} --relations'.split(), stdout=PIPE)
    status = proc.stdout.read().decode('utf-8')
    if '-' in app_name:
        # escape dashes
        app_name = app_name.replace('-', r'\-')

    # even if the scale is "4/5" this will match the first digit, i.e. the current scale
    scale = re.compile(
        fr"^{app_name}(?!/)(\s+)?(\d+)?(\s+)?(\w+)(\s+)?(?P<scale>\d+)",
        re.MULTILINE).findall(status)
    if not scale:
        raise RuntimeError(f'failed to parse output of {proc.args}; is '
                           f'{app_name!r} correct?')

    leader_id = \
    re.compile(fr"^{app_name}\/(\d+)\*", re.MULTILINE).findall(status)[0][-1]
    intf_re = fr"(({app_name}:{relation_name}\s+{other_app_name}:{other_relation_name})|({other_app_name}:{other_relation_name}\s+{app_name}:{relation_name}))\s+([\w\-]+)"
    interface = re.compile(intf_re).findall(status)[0][-1]
    return Metadata(int(scale[0][-1]), int(leader_id), interface)


def get_app_name_and_units(url, relation_name,
                           other_app_name, other_relation_name):
    """Get app name and unit count from url; url is either `app_name/0` or `app_name`."""
    app_name, unit_id = url.split('/') if '/' in url else (url, None)

    meta = get_metadata_from_status(app_name, relation_name, other_app_name,
                                    other_relation_name)
    if unit_id:
        units = (int(unit_id),)
    else:
        units = tuple(range(0, meta.scale))
    return app_name, units, meta


def get_content(obj: str, other_obj,
                include_default_juju_keys: bool = False) -> AppRelationData:
    """Get the content of the databag of `obj`, as seen from `other_obj`."""
    url, endpoint = obj.split(":")
    other_url, other_endpoint = other_obj.split(":")

    other_app_name, _ = other_url.split('/') if '/' in other_url else (
    other_url, None)

    app_name, units, meta = get_app_name_and_units(
        url, endpoint, other_app_name, other_endpoint)

    # we might have a different number of units and other units, and it doesn't
    # matter which 'other' we pass to get the databags for 'this', so:
    other_unit_name = f"{other_app_name}/0"

    leader_unit_data = None
    app_data = None
    units_data = {}
    for unit_id in units:
        unit_name = f"{app_name}/{unit_id}"
        unit_data, app_data = get_databags(unit_name, other_unit_name,
                                           endpoint, other_endpoint)
        if not include_default_juju_keys:
            purge(unit_data)
        units_data[unit_id] = unit_data

    return AppRelationData(
        app_name=app_name,
        meta=meta,
        endpoint=endpoint,
        application_data=app_data,
        units_data=units_data)


def get_databags(local_unit, remote_unit, local_endpoint, remote_endpoint):
    """Gets the databags of local unit and its leadership status.

    Given a remote unit and the remote endpoint name.
    """
    local_data = get_unit_info(local_unit)
    leader = local_data["leader"]

    data = get_unit_info(remote_unit)
    relation_info = data.get("relation-info")
    if not relation_info:
        raise RuntimeError(f"{remote_unit} has no relations")

    raw_data = get_relation_by_endpoint(relation_info, local_endpoint,
                                        remote_endpoint, local_unit)
    unit_data = raw_data["related-units"][local_unit]["data"]
    app_data = raw_data["application-data"]
    return unit_data, app_data


@dataclass
class RelationData:
    provider: AppRelationData
    requirer: AppRelationData


def get_relation_data(
        *, provider_endpoint: str, requirer_endpoint: str,
        include_default_juju_keys: bool = False
):
    """Get relation databags for a juju relation.

    >>> get_relation_data('prometheus/0:ingress', 'traefik/1:ingress-per-unit')
    """
    provider_data = get_content(provider_endpoint, requirer_endpoint,
                                include_default_juju_keys)
    requirer_data = get_content(requirer_endpoint, provider_endpoint,
                                include_default_juju_keys)
    return RelationData(provider=provider_data, requirer=requirer_data)


async def render_relation(endpoint1: str, endpoint2: str,
                          include_default_juju_keys: bool = False):
    """Pprints relation databags for a juju relation
    >>> render_relation('prometheus/0:ingress', 'traefik/1:ingress-per-unit')
    """

    from rich.console import Console  # noqa
    from rich.pretty import Pretty  # noqa
    from rich.text import Text  # noqa
    from rich.table import Table  # noqa
    from rich.panel import Panel  # noqa
    from rich.columns import Columns  # noqa

    data1 = get_content(endpoint1, endpoint2, include_default_juju_keys)
    data2 = get_content(endpoint2, endpoint1, include_default_juju_keys)

    table = Table(title="relation data v0.2")
    table.add_column(justify='left', header='category',
                     style='rgb(54,176,224) bold')
    table.add_column(justify='left', header=data1.app_name)  # meta/app_name
    table.add_column(justify='left', header=data2.app_name)

    table.add_row('relation name', Text(data1.endpoint, style='green'),
                  Text(data2.endpoint, style='green'))
    table.add_row('interface', Text(data1.meta.interface, style='blue bold'),
                  Text(data2.meta.interface, style='blue bold'))

    leader_id_1 = data1.meta.leader_id
    leader_id_2 = data2.meta.leader_id
    table.add_row('leader unit', Text(str(leader_id_1), style='red'),
                  Text(str(leader_id_2), style='red'), end_section=True)

    def render_databag(unit_name, dct, leader=False):
        if not dct:
            t = Text('<empty>', style='rgb(255,198,99)')
        else:
            t = Table(box=None)
            t.add_column(style='cyan not bold')  # keys
            t.add_column(style='white not bold')  # values
            for key in sorted(dct.keys()):
                t.add_row(key, dct[key])

        if leader:
            title = unit_name + '*'
            style = "rgb(54,176,224) bold"
        else:
            title = unit_name
            style = "white"

        p = Panel(t, title=title, title_align='left', style=style,
                  border_style="white")
        return p

    app_databag = render_databag('', data1.application_data)
    other_app_databag = render_databag('', data2.application_data)
    table.add_row('application data', app_databag, other_app_databag)

    unit_databags = []
    other_unit_databags = []

    def render(obj: Optional[Tuple[int, Dict]], source: AppRelationData):
        unit_id, unit_data = obj
        unit_name = f"{source.app_name}/{unit_id}"
        return render_databag(unit_name, unit_data,
                              leader=(unit_id == source.meta.leader_id))

    for unit, other_unit in zip_longest(data1.units_data.items(),
                                        data2.units_data.items()):
        if unit:
            unit_databags.append(render(unit, data1))
        if other_unit:
            other_unit_databags.append(render(other_unit, data2))

    table.add_row('unit data', Columns(unit_databags),
                  Columns(other_unit_databags))
    return table


def sync_show_relation(
        endpoint1: str = typer.Argument(
            ...,
            help="First endpoint. It's a string in the format "
                 "<unit_name>:<relation_name>; example: mongodb/1:ingress."),
        endpoint2: str = typer.Argument(
            ...,
            help="Second endpoint. It's a string in the format "
                 "<unit_name>:<relation_name>; example: traefik/3:ingress."),
        include_default_juju_keys: bool = False,
        watch: bool = False):
    """Displays the databags of two applications or units involved in a relation.

    Example:
        jhack utils show-relation my_app/0:relation_name other_app/2:other_name
        jhack utils show-relation my_app:relation_name other_app/2:other_name
        jhack utils show-relation my_app:relation_name other_app:other_name
    """
    try:
        import rich  # noqa
    except ImportError:
        print('using this command requires rich.')
        return

    from rich.console import Console

    while True:
        start = time.time()

        table = asyncio.run(
            render_relation(endpoint1, endpoint2, include_default_juju_keys)
        )

        if watch:
            elapsed = time.time() - start
            if elapsed < 1:
                time.sleep(1.5 - elapsed)
                _JUJU_DATA_CACHE.clear()
            # we clear RIGHT BEFORE printing to prevent flickering
            Console().clear()
        Console().print(table)

        if not watch:
            return


if __name__ == '__main__':
    sync_show_relation("traefik-k8s:ingress-per-unit", "prometheus-k8s:ingress")
