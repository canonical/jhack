import asyncio
import time
from subprocess import Popen, PIPE

import yaml

_JUJU_DATA_CACHE = {}
_JUJU_KEYS = ('egress-subnets', 'ingress-address', 'private-address')


def purge(data: dict):
    for key in _JUJU_KEYS:
        if key in data:
            del data[key]


async def grab_unit_info(unit_name: str) -> dict:
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

    proc = Popen(f'juju show-unit {unit_name}'.split(' '), stdout=PIPE)
    raw_data = proc.stdout.read().decode('utf-8').strip()
    if not raw_data:
        raise ValueError(
            f"no unit info could be grabbed for {unit_name}; "
            f"are you sure it's a valid unit name?"
        )

    data = yaml.safe_load(raw_data)
    _JUJU_DATA_CACHE[unit_name] = data
    return data


def get_relation_by_endpoint(relations, endpoint, remote_obj):
    relations = [r for r in relations if
                 r['endpoint'] == endpoint and
                 remote_obj in r['related-units']]
    if not relations:
        raise ValueError(f'no relations found with endpoint=='
                         f'{endpoint}')
    if len(relations) > 1:
        raise ValueError('multiple relations found with endpoint=='
                         f'{endpoint}')
    return relations[0]


async def get_content(obj: str, other_obj,
                      include_default_juju_keys: bool = False) -> tuple:
    endpoint = None
    other_unit_name = other_obj.split(':')[0] if ':' in other_obj else other_obj
    if ':' in obj:
        unit_name, endpoint = obj.split(':')
    else:
        unit_name = obj
    data = (await grab_unit_info(unit_name))[unit_name]

    relation_infos = data.get('relation-info')
    if not relation_infos:
        raise RuntimeError(f'{unit_name} has no relations')

    if not endpoint:
        relation_data_raw = relation_infos[0]
        endpoint = relation_data_raw['endpoint']
    else:
        relation_data_raw = get_relation_by_endpoint(relation_infos, endpoint,
                                                     other_unit_name)

    metadata = unit_name, endpoint, data['leader']
    application_data = relation_data_raw['application-data']

    related_units_data_raw = relation_data_raw['related-units']
    other_unit_data = related_units_data_raw.get(other_unit_name, {})

    other_unit_name = next(iter(related_units_data_raw.keys()))
    other_unit_info = await grab_unit_info(other_unit_name)
    other_unit_relation_infos = other_unit_info[other_unit_name][
        'relation-info']
    this_unit_data = get_relation_by_endpoint(
        other_unit_relation_infos, relation_data_raw['related-endpoint'],
        unit_name)[
        'related-units'][unit_name]['data']

    if not include_default_juju_keys:
        purge(this_unit_data)
        purge(other_unit_data)

    relation_data = (application_data, this_unit_data, other_unit_data)
    return metadata, relation_data


async def render_relation(endpoint1: str, endpoint2: str,
                          include_default_juju_keys: bool = False):
    """Pprints relation databags for a juju relation
    >>> render_relation('prometheus/0:ingress', 'traefik/1:ingress-per-unit')
    """

    from rich.console import Console  # noqa
    from rich.pretty import Pretty  # noqa
    from rich.table import Table  # noqa

    ep1_content = await get_content(endpoint1, endpoint2,
                                    include_default_juju_keys)
    ep2_content = await get_content(endpoint2, endpoint1,
                                    include_default_juju_keys)
    # content: metadata, (application_data, this_unit_data, other_unit_data)

    table = Table(title="relation data v0.1")
    table.add_column(justify='left', header='category', style='cyan')
    table.add_column(justify='right', header='keys', style='blue')
    table.add_column(justify='left', header=ep1_content[0][0])  # meta/unit_name
    table.add_column(justify='left', header=ep2_content[0][0])

    meta1 = ep1_content[0]
    meta2 = ep2_content[0]
    table.add_row('metadata', 'endpoint', Pretty(meta1[1]), Pretty(meta2[1]))
    table.add_row('', 'leader', Pretty(meta1[2]), Pretty(meta2[2]),
                  end_section=True)

    def insert_pairwise_dicts(category, dict1, dict2):
        first = True
        for key in sorted(dict1.keys() | dict2.keys()):
            table.add_row(category if first else '',
                          key,
                          dict1[key] if key in dict1 else '',
                          dict2[key] if key in dict2 else '')
            first = False

    insert_pairwise_dicts('application data', ep1_content[1][0],
                          ep2_content[1][0])
    insert_pairwise_dicts('unit data', ep1_content[1][1], ep2_content[1][1])
    return table


def sync_show_relation(endpoint1: str, endpoint2: str,
                       include_default_juju_keys: bool = False,
                       watch: bool = False):
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
