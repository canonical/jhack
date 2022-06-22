import asyncio
import time
from dataclasses import dataclass
from subprocess import Popen, PIPE

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


def get_relation_by_endpoint(relations, local_endpoint, remote_endpoint, remote_obj):
    relations = [
        r for r in relations if
        r["endpoint"] == remote_endpoint and
        r["related-endpoint"] == remote_endpoint and
        remote_obj in r["related-units"]
    ]
    if not relations:
        raise ValueError(
            f"no relations found with remote endpoint=="
            f"{remote_endpoint} and local endpoint == {local_endpoint}"
            f"in {remote_obj} (relations={relations})"
        )
    if len(relations) > 1:
        raise ValueError(
            "multiple relations found with remote endpoint=="
            f"{remote_endpoint} and local endpoint == {local_endpoint}"
            f"in {remote_obj} (relations={relations})"
        )
    return relations[0]


@dataclass
class UnitRelationData:
    unit_name: str
    endpoint: str
    leader: bool
    application_data: dict
    unit_data: dict


def get_content(obj: str, other_obj,
                include_default_juju_keys: bool = False) -> UnitRelationData:
    """Get the content of the databag of `obj`, as seen from `other_obj`."""
    unit_name, endpoint = obj.split(":")
    other_unit_name, other_endpoint = other_obj.split(":")

    unit_data, app_data, leader = get_databags(unit_name, other_unit_name,
                                               endpoint, other_endpoint)

    if not include_default_juju_keys:
        purge(unit_data)

    return UnitRelationData(unit_name, endpoint, leader, app_data, unit_data)


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
    return unit_data, app_data, leader


@dataclass
class RelationData:
    provider: UnitRelationData
    requirer: UnitRelationData


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
    from rich.table import Table  # noqa

    data1 = get_content(endpoint1, endpoint2, include_default_juju_keys)
    data2 = get_content(endpoint2, endpoint1, include_default_juju_keys)

    table = Table(title="relation data v0.1")
    table.add_column(justify='left', header='category', style='cyan')
    table.add_column(justify='right', header='keys', style='blue')
    table.add_column(justify='left', header=data1.unit_name)  # meta/unit_name
    table.add_column(justify='left', header=data2.unit_name)

    table.add_row('metadata', 'endpoint', Pretty(data1.endpoint),
                  Pretty(data2.endpoint))
    table.add_row('', 'leader', Pretty(data1.leader), Pretty(data2.leader),
                  end_section=True)

    def insert_pairwise_dicts(category, dict1, dict2):
        first = True
        for key in sorted(dict1.keys() | dict2.keys()):
            table.add_row(category if first else '',
                          key,
                          dict1[key] if key in dict1 else '',
                          dict2[key] if key in dict2 else '')
            first = False

    insert_pairwise_dicts('application data', data1.application_data,
                          data2.application_data)
    insert_pairwise_dicts('unit data', data1.unit_data, data2.unit_data)
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
    """Displays the databags of two units involved in a relation.

    Example:
        jhack utils show-relation my_app/0:relation_name other_app/2:other_name
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
    sync_show_relation("traefik-k8s/0:ingress-per-unit", "ipun/0:ingress-per-unit")
