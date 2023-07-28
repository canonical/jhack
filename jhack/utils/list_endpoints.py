from functools import partial
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from jhack.helpers import ColorOption, LibInfo, get_libinfo
from jhack.logger import logger as jhack_logger
from jhack.utils.helpers.gather_endpoints import (
    AppEndpoints,
    PeerBinding,
    gather_endpoints,
)

logger = jhack_logger.getChild("endpoints")


def _implements(interface_name, lib: LibInfo):
    """Attempt to determine whether a charm lib implements this interface."""

    def _normalize(name):
        return name.upper().replace("-", "_").split(".")[0]

    if _normalize(lib.lib_name) == _normalize(interface_name):
        return True

    return False


def _supported_versions(libinfos: List[LibInfo], interface_name: str):
    charm_libs = list(filter(partial(_implements, interface_name), libinfos))
    if not charm_libs:
        return "<library not found>"
    return "|".join(f"{lib.version}.{lib.revision}" for lib in charm_libs)


def _render(endpoints: AppEndpoints, libinfo: Optional[List[LibInfo]]) -> Table:
    table = Table(title="endpoints v0.1", expand=True)
    table.add_column(header="role")
    table.add_column(header="endpoint")
    table.add_column(header="interface")
    if libinfo:
        table.add_column(header="version")
    table.add_column(header="bound to")

    for role in ("requires", "provides"):
        first = True
        for endpoint_name, (interface_name, remotes) in endpoints[role].items():
            table.add_row(
                role if first else None,
                *(
                    [interface_name, endpoint_name]
                    + (
                        [_supported_versions(libinfo, interface_name)]
                        if libinfo
                        else []
                    )
                    + [", ".join(remote["related-application"] for remote in remotes)]
                ),
            )
            first = False

    if endpoints["peers"]:
        binding: PeerBinding
        first = True
        for binding in endpoints["peers"]:
            table.add_row(
                "peers" if first else None,
                binding.interface,
                binding.endpoint,
                "n/a",
                "<itself>",
            )
            first = False

    return table


def _list_endpoints(
    app: str,
    model: Optional[str] = None,
    color: str = "auto",
    show_versions: bool = False,
):
    endpoints = gather_endpoints(model, (app,), include_peers=True)[app]
    libinfo = get_libinfo(app, model) if show_versions else None

    c = Console(color_system=color)
    c.print(_render(endpoints, libinfo))


def list_endpoints(
    app: str = typer.Argument(..., help="Application whose endpoints to show."),
    show_versions: bool = typer.Option(
        False,
        "-v",
        "--show-versions",
        is_flag=True,
        help="Show supported interface versions.",
    ),
    model: str = typer.Option(
        None, "--model", "-m", help="Model in which to apply this command."
    ),
    color: Optional[str] = ColorOption,
):
    """Display the available integration endpoints."""
    _list_endpoints(app=app, model=model, show_versions=show_versions, color=color)


if __name__ == "__main__":
    _list_endpoints("trfk", show_versions=True)
