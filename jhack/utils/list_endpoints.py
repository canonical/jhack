from functools import partial
from typing import Dict, Optional, Sequence

import typer
from rich.color import Color
from rich.console import Console
from rich.style import Style
from rich.table import Table
from rich.text import Text

from jhack.helpers import (
    ColorOption,
    EndpointInfo,
    LibInfo,
    get_epinfo,
    get_libinfo,
    juju_version,
)
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

    return _normalize(lib.lib_name) == _normalize(interface_name)


def _supported_versions(implementations: Sequence[LibInfo]):
    if not implementations:
        return "<library not found>"
    return "|".join(f"{lib.version}.{lib.revision}" for lib in implementations)


def _implementations(
    libinfos: Sequence[LibInfo], interface_name: str
) -> Sequence[LibInfo]:
    """List of LibInfos corresponding to libs that probably implement this interface.

    (based on their name)
    """
    return list(filter(partial(_implements, interface_name), libinfos))


def _normalize(name: str):
    return name.lower().replace("-", "_")


def _description(
    epinfo: Dict[str, Dict[str, EndpointInfo]], role: str, endpoint_name: str
):
    endpoint_info = epinfo.get(role, {}).get(endpoint_name, None)
    if endpoint_info:
        return endpoint_info.description
    return "<none given>"


def _render(
    endpoints: AppEndpoints,
    libinfo: Optional[Sequence[LibInfo]],
    epinfo: Optional[Dict[str, Dict[str, EndpointInfo]]],
    app: str,
) -> Table:
    table = Table(
        title="endpoints v0.1",
        expand=True,
        row_styles=[Style(bgcolor=Color.from_rgb(*[40] * 3)), ""],
    )
    table.add_column(header="role")
    table.add_column(header="endpoint")

    table.add_column(header="owner:interface" if libinfo else "interface")

    if libinfo:
        table.add_column(header="version")

    jujuversion = juju_version()

    # FIXME: regression in juju 3.2
    #   https://bugs.launchpad.net/juju/+bug/2029113
    # support_bound_to = jujuversion.version[:2] != (3, 2)
    support_bound_to = True
    if support_bound_to:
        table.add_column(header="bound to")

    if epinfo:
        table.add_column(header="description")

    for role, color in zip(("requires", "provides"), ("green", "blue")):
        first = True
        for endpoint_name, (interface_name, remotes) in endpoints[role].items():
            if support_bound_to:
                if remotes:
                    try:
                        remote_info = [
                            ", ".join(
                                remote["related-application"] for remote in remotes
                            )
                        ]
                    except Exception:
                        logger.error(
                            f"unable to get related-applications from remotes: {remotes}."
                            f"This should be possible in juju {jujuversion.version}."
                        )
                        remote_info = ["<data unavailable>"]
                        support_bound_to = False

                else:
                    remote_info = ["-"]

            else:
                remote_info = []

            if remotes:
                logger.info("remotes not supported in this juju version")

            implementations = _implementations(libinfo, interface_name)

            if libinfo:
                if len(implementations) == 1:
                    owner = implementations[0].owner
                else:
                    owner = "<unknown owner>"

                # highlight libs owned by the app we're looking at
                owner_color = "cyan" if _normalize(owner) == _normalize(app) else "blue"
                owner_tag = Text(owner, style=f"{owner_color}") + Text(
                    ":", style="default"
                )

            else:
                owner_tag = Text("")

            table.add_row(
                Text(role, style="bold " + color) if first else None,
                *(
                    [endpoint_name, owner_tag + Text(interface_name, style="default")]
                    + ([_supported_versions(implementations)] if libinfo else [])
                    + remote_info
                    + ([_description(epinfo, role, endpoint_name)] if epinfo else [])
                ),
            )
            first = False

        if not first:
            table.add_section()

    table.add_section()
    if endpoints["peers"]:
        binding: PeerBinding
        first = True
        for binding in endpoints["peers"]:
            row = (
                [
                    Text("peers", style="bold yellow") if first else None,
                    binding.provider_endpoint,
                    binding.interface,
                ]
                + ([Text("n/a", style="orange")] if libinfo else [])
                + ([Text("<itself>", style="yellow")] if support_bound_to else [])
            )
            table.add_row(*row)

            first = False

    return table


def _list_endpoints(
    app: str,
    model: Optional[str] = None,
    color: str = "auto",
    show_versions: bool = False,
    show_descriptions: bool = False,
):
    if "/" in app:
        logger.warning(
            f"list-endpoints only works on applications. Pass an app name instead of {app}."
        )
        app = app.split("/")[0]

    all_endpoints = gather_endpoints(model, (app,), include_peers=True)
    endpoints = all_endpoints.get(app)
    if not endpoints:
        logger.error(f"app {app!r} not found in model {model or '<the current model>'}")
        exit(1)

    libinfo = get_libinfo(app, model) if show_versions else ()
    epinfo = get_epinfo(app, model) if show_descriptions else ()

    c = Console(color_system=color)
    c.print(_render(endpoints, libinfo, epinfo, app))


def list_endpoints(
    app: str = typer.Argument(..., help="Application whose endpoints to show."),
    show_versions: bool = typer.Option(
        False,
        "-v",
        "--show-versions",
        is_flag=True,
        help="Show supported interface versions.",
    ),
    show_descriptions: bool = typer.Option(
        False,
        "-d",
        "--show-descriptions",
        is_flag=True,
        help="Show endpoint descriptions as defined in the charmcraft yaml.",
    ),
    model: str = typer.Option(
        None, "--model", "-m", help="Model in which to apply this command."
    ),
    color: Optional[str] = ColorOption,
):
    """Display the available integration endpoints."""
    _list_endpoints(
        app=app,
        model=model,
        show_versions=show_versions,
        show_descriptions=show_descriptions,
        color=color,
    )


if __name__ == "__main__":
    _list_endpoints("tempo", show_versions=True, show_descriptions=True)
