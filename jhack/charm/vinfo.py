import json
from dataclasses import dataclass
from enum import Enum
from operator import itemgetter
from typing import Optional, Tuple

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from jhack.helpers import (
    ColorOption,
    JPopen,
    RichSupportedColorOptions,
    cached_juju_status,
    check_command_available,
    get_libinfo,
)
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild(__file__)


def _get_charmcraft_lib_info(charm_name):
    out = JPopen(f"charmcraft list-lib {charm_name} --format=json".split())
    return json.loads(out.stdout.read().decode("utf-8"))


def _check_outdated(charm_name):
    # dashes get turned into underscores to make it python-identifier-compliant.
    # so we get to try first with dashes.
    dashed_name = charm_name.replace("_", "-")
    return _get_charmcraft_lib_info(dashed_name) or _get_charmcraft_lib_info(charm_name)


def _add_app_info(table: Table, target: str, model: str):
    status = cached_juju_status(target, model=model, json=True)
    table.add_row("app name", target)
    app_name = target.split("/")[0]
    appinfo = status["applications"][app_name]
    table.add_row(
        "charm",
        f"{appinfo['charm-name']}: v{appinfo['charm-rev']} - "
        f"{appinfo.get('charm-channel', '<local charm>')}",
    )
    table.add_row("model", model or status["model"]["name"])
    table.add_row(
        "workload version",
        status["applications"][app_name].get("version", None) or "<unknown>",
        end_section=True,
    )


_symbol_unknown = "?"
_symbol_outdated = "<"
_symbol_out_of_sync = ">"
_symbol_in_sync = "=="


class SyncStatus(Enum):
    outdated = "outdated"
    up_to_date = "up_to_date"
    ahead_of_upstream = "ahead_of_upstream"
    unknown = "unknown"


@dataclass
class OutdatedCheck:
    outdated: SyncStatus
    text: Text
    lib_path: str  # charmcraft library address


def _add_charm_lib_info(
    table: Table, app: str, model: str, check_outdated=True, machine=False
):
    if check_outdated and not check_command_available("charmcraft"):
        logger.error(
            "Cannot check outdated libs: "
            "command unavailable: `charmcraft`. Is this a snap?"
        )
        check_outdated = False

    libinfo = get_libinfo(app, model, machine)

    ch_lib_meta = {}

    if check_outdated:
        owners = set(map(itemgetter(0), libinfo))
        for owner in owners:
            logger.info(f"getting charmcraft lib info from {owner}")
            lib_info_ch = _check_outdated(owner)
            ch_lib_meta[owner] = {obj["library_name"]: obj for obj in lib_info_ch}

    def _check_version(
        owner: str, lib_name: str, version: Tuple[int, int]
    ) -> OutdatedCheck:
        lib_path = f"charms.{owner}.v{version[0]}.{lib_name}"
        try:
            lib_meta = ch_lib_meta[owner][lib_name]
        except KeyError as e:
            logger.warning(
                f"Couldn't find {e} in charmcraft lib-info for {owner}.{lib_name}"
            )
            return OutdatedCheck(
                SyncStatus.unknown, Text(_symbol_unknown, style="orange"), lib_path
            )

        upstream_v = lib_meta["api"], lib_meta["patch"]

        if upstream_v == version:
            return OutdatedCheck(
                SyncStatus.up_to_date,
                Text(_symbol_in_sync, style="bold green"),
                lib_path,
            )

        elif upstream_v < version:
            symbol = _symbol_out_of_sync
            color = "orange"
            status = SyncStatus.ahead_of_upstream

        else:
            symbol = _symbol_outdated
            color = "red"
            status = SyncStatus.outdated

        return OutdatedCheck(
            status,
            Text(symbol, style="bold " + color)
            + Text(" (", style="bold default")
            + Text(str(upstream_v[0]), style=color)
            + "."
            + Text(str(upstream_v[1]), style=color)
            + Text(")", style="bold default"),
            lib_path,
        )

    for owner, version, lib_name, revision in libinfo:
        description = (
            Text(version, style="bold") + "." + Text(revision, style="default")
        )

        if check_outdated:
            description += "\t"
            check = _check_version(owner, lib_name, (int(version), int(revision)))
            description += check.text

            # TODO: for each outdated lib, print copy-pastable command you'd need to run to update
        row = [
            (
                Text(owner, style="purple")
                + Text(":", style="default")
                + Text(lib_name, style="bold cyan")
            ),
            description,
        ]

        table.add_row(*row)

    table.rows[-1].end_section = True


def _vinfo(
    target: str,
    machine: bool = False,
    check_outdated: bool = True,
    color: RichSupportedColorOptions = "auto",
    model: str = None,
):
    table = Table(title="vinfo v0.1", show_header=False, expand=True)
    table.add_column()
    table.add_column()

    _add_app_info(table, target, model)
    _add_charm_lib_info(
        table,
        target,
        model,
        machine=machine,
        check_outdated=check_outdated,
    )

    if color == "no":
        color = None
    console = Console(color_system=color)
    console.print(table)


def vinfo(
    target: str = typer.Argument(
        ..., help="Unit or application name to generate the vinfo of."
    ),
    check_outdated: bool = typer.Option(
        False,
        "-o",
        "--check-outdated",
        help="Check whether the charm libs used by the charm are up to date."
        "This requires the 'charmcraft' command to be available. "
        "False by default as the command will take considerably longer.",
        is_flag=True,
    ),
    color: Optional[str] = ColorOption,
    model: str = typer.Option(
        None, "--model", "-m", help="Model in which to apply this command."
    ),
):
    """Show version information of a charm and its charm libs."""
    _vinfo(
        target=target,
        machine=False,  # not implemented; todo implement
        check_outdated=check_outdated,
        color=color,
        model=model,
    )


if __name__ == "__main__":
    _vinfo("zinc-k8s/0")
