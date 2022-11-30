import json
import re
from operator import itemgetter
from typing import Optional

import typer
from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from jhack.logger import logger as jhacklogger

from jhack.helpers import juju_status, RichSupportedColorOptions, JPopen, ColorOption, check_command_available

logger = jhacklogger.getChild(__file__)

_status_cache = None


def _juju_status(target, model):
    global _status_cache
    if not _status_cache:
        _status_cache = juju_status(target, model=model, json=True)
    return _status_cache


def _get_lib_info(charm_name):
    out = JPopen(f"charmcraft list-lib {charm_name} --format=json".split())
    return json.loads(out.stdout.read().decode('utf-8'))


def get_lib_info(charm_name):
    # dashes get turned into underscores to make it python-identifier-compliant.
    # so we get to try first with dashes.
    dashed_name = charm_name.replace('_', '-')
    return _get_lib_info(dashed_name) or _get_lib_info(charm_name)


def _add_app_info(table: Table, target: str, model: str):
    status = _juju_status(target, model=model)
    table.add_row('app name', target)
    appinfo = status['applications'][target.split('/')[0]]
    table.add_row('charm', f"{appinfo['charm-name']}: v{appinfo['charm-rev']} - {appinfo['charm-channel']}")
    table.add_row('model', model or status['model']['name'])
    table.add_row('workload version',
                  status['applications']['zinc-k8s'].get('version', None) or '<unknown>',
                  end_section=True)


_symbol_unknown = "?"
_symbol_outdated = "<"
_symbol_out_of_sync = ">"
_symbol_in_sync = "=="


def _add_charm_lib_info(table: Table, app: str, model: str, check_outdated=True,
                        machine=False):
    if check_outdated and not check_command_available('charmcraft'):
        logger.error('Cannot check outdated libs: '
                     'command unavailable: `charmcraft`. Is this a snap?')
        check_outdated = False

    status = _juju_status(app, model=model)
    unit_name = status['applications'][app.split('/')[0]]['units'].popitem()[0]

    # todo: if machine, adapt path
    cmd = f'juju ssh {unit_name} find ./agents/unit-zinc-k8s-0/charm/lib ' \
          '-type f ' \
          '-iname "*.py" ' \
          r'-exec grep "LIBPATCH" {} \+'
    proc = JPopen(cmd.split())
    out = proc.stdout.read().decode('utf-8')
    libs = out.strip().split('\n')

    # todo: if machine, adapt pattern
    # pattern: './agents/unit-zinc-k8s-0/charm/lib/charms/loki_k8s/v0/loki_push_api.py:LIBPATCH = 12'
    libinfo = []
    for lib in libs:
        libinfo.append(re.search(r".*/charms/(\w+)/v(\d+)/(\w+)\.py\:LIBPATCH\s\=\s(\d+)", lib).groups())

    ch_lib_meta = {}

    if check_outdated:
        owners = set(map(itemgetter(0), libinfo))
        for owner in owners:
            logger.info(f'getting charmcraft lib info from {owner}')
            lib_info_ch = get_lib_info(owner)
            ch_lib_meta[owner] = {obj['library_name']: obj for obj in lib_info_ch}

    def _check_version(owner, lib_name, version):
        try:
            lib_meta = ch_lib_meta[owner][lib_name]
        except KeyError as e:
            logger.warning(f"Couldn't find {e} in charmcraft lib-info for {owner}.{lib_name}")
            return Text(_symbol_unknown, style='orange')

        upstream_v = lib_meta['api'], lib_meta['patch']

        if upstream_v == version:
            return Text(_symbol_in_sync, style='bold green')

        elif upstream_v < version:
            symbol = _symbol_out_of_sync
            color = 'orange'

        else:
            symbol = _symbol_outdated
            color = 'red'

        return (Text(symbol, style="bold " + color) +
                Text(" (", style='bold default') +
                Text(str(upstream_v[0]), style=color) +
                "." +
                Text(str(upstream_v[1]), style=color) +
                Text(")", style='bold default'))

    for owner, version, lib_name, revision in libinfo:
        description = (Text(version, style="bold") +
                       "." +
                       Text(revision, style='default'))

        if check_outdated:
            description += "\t"
            description += _check_version(owner, lib_name, (int(version), int(revision)))

        table.add_row(
            (Text(owner, style="purple") +
             Text(":", style='default') +
             Text(lib_name, style="bold cyan")),
            description)

    table.rows[-1].end_section = True


def _vinfo(target: str,
              machine: bool = False,
              check_outdated: bool = True,
              color: RichSupportedColorOptions = "auto",
              model: str = None):
    table = Table(title='vinfo v0.1', show_header=False)
    table.add_column()
    table.add_column()

    # app, _, unit_id = target.rpartition('/')
    # if app:
    #     target = app
    # else:
    #     target = unit_id

    _add_app_info(table, target, model)
    _add_charm_lib_info(table, target, model, machine=machine, check_outdated=check_outdated)

    if color == "no":
        color = None
    console = Console(color_system=color)
    console.print(table)


def vinfo(
        target: str = typer.Argument(
            ...,
            help="Unit or application name to generate the vinfo of."
        ),
        # machine: bool = typer.Option(
        #     False,
        #     help="Is this a machine model?",  # todo autodetect
        #     is_flag=True
        # ),
        check_outdated: bool = typer.Option(
            False, "-o", "--check-outdated",
            help="Check whether the charm libs used by the charm are up to date."
                 "This requires the 'charmcraft' command to be available. "
                 "False by default as the command will take considerably longer.",
            is_flag=True
        ),
        color: Optional[str] = ColorOption,
        model: str = typer.Option(
            None, "--model", "-m",
            help="Model in which to apply this command.")
        ):
    """Show version information of a charm and its charm libs."""
    _vinfo(target=target,
              machine=False,  # not implemented; todo implement
              check_outdated=check_outdated,
              color=color,
              model=model)


if __name__ == '__main__':
    _vinfo('zinc-k8s/0')
