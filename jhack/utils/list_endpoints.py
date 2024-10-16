import sys
from calendar import TextCalendar
from functools import partial
from typing import Dict, Optional, Sequence, List

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
        return Text("<library not found>", style="dim red")
    return Text("|").join(
        Text(f"{lib.version}.{lib.revision}", style="bold cyan")
        for lib in implementations
    )


def _implementations(
    libinfos: Sequence[LibInfo], interface_name: str
) -> Sequence[LibInfo]:
    """List of LibInfos corresponding to libs that probably implement this interface.

    (based on their name)
    """
    return list(filter(partial(_implements, interface_name), libinfos))


def _normalize(name: str):
    return name.lower().replace("-", "_")


def _description(endpoint_info: Optional[EndpointInfo], role: str, endpoint_name: str):
    if endpoint_info:
        return endpoint_info.description
    return "<none given>"


_required_and_bound = Text("yes", style="bold green")
_required_and_unbound = Text("yes", style="bold red")
_not_required = Text("no", style="dim")
_unknown = Text("<unknown>", style="orange")

_UNSUPPORTED_JUJU_BOUND = "<unsupported>"
# marker for a situation where due to a juju bug we can't fetch the remotes


def _check_bound_required(epinfo: EndpointInfo, remotes: List[str]):
    if not epinfo:
        return _unknown
    if epinfo.required:
        if remotes == [_UNSUPPORTED_JUJU_BOUND]:
            return _unknown
        if remotes:
            return _required_and_bound
        else:
            return _required_and_unbound
    else:
        return _not_required


def _render(
    endpoints: AppEndpoints,
    libinfo: Optional[Sequence[LibInfo]],
    epinfo: Optional[Dict[str, Dict[str, EndpointInfo]]],
    app: str,
    extra_fields: List[str],
) -> Table:
    table = Table(
        title="endpoints v0.1",
        expand=True,
        row_styles=[Style(bgcolor=Color.from_rgb(*[40] * 3)), ""],
    )
    table.add_column(header="role")
    table.add_column(header="endpoint")

    if "r" in extra_fields:
        table.add_column(header="required")
    if "i" in extra_fields:
        table.add_column(header="owner:interface" if libinfo else "interface")
    if "v" in extra_fields:
        table.add_column(header="version")

    # Possible regression in juju 3.2 https://bugs.launchpad.net/juju/+bug/2029113
    # support_bound_to = jujuversion.version[:2] != (3, 2)
    support_bound_to = True
    if support_bound_to and "b" in extra_fields:
        table.add_column(header="bound to")

    if "d" in extra_fields:
        table.add_column(header="description")

    for role, color in zip(("requires", "provides"), ("green", "blue")):
        first = True
        for endpoint_name, (interface_name, remotes) in endpoints[role].items():
            if remotes:
                try:
                    remote_info = [
                        ", ".join(remote["related-application"] for remote in remotes)
                    ]
                except Exception:
                    logger.error(
                        f"unable to get related-applications from remotes: {remotes}."
                        f"This should be possible in juju {juju_version().version}."
                    )
                    remote_info = [_UNSUPPORTED_JUJU_BOUND]

            else:
                remote_info = []

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

            endpoint_info = (
                epinfo.get(role, {}).get(endpoint_name, None) if epinfo else None
            )

            table.add_row(
                Text(role, style="bold " + color) if first else None,
                *(
                    [endpoint_name]
                    + (
                        [_check_bound_required(endpoint_info, remote_info)]
                        if "r" in extra_fields
                        else []
                    )
                    + (
                        [owner_tag + Text(interface_name, style="default")]
                        if "i" in extra_fields
                        else []
                    )
                    + (
                        [_supported_versions(implementations)]
                        if "v" in extra_fields
                        else []
                    )
                    + (remote_info or ["-"] if "b" in extra_fields else [])
                    + (
                        [_description(endpoint_info, role, endpoint_name)]
                        if "d" in extra_fields
                        else []
                    )
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
            endpoint_info = (
                epinfo.get("peers", {}).get(binding.provider_endpoint, None)
                if epinfo
                else None
            )

            row = (
                [
                    Text("peers", style="bold yellow") if first else None,
                    binding.provider_endpoint,
                ]
                + ([Text("n/a", style="dim")] if "r" in extra_fields else [])
                + ([binding.interface] if "i" in extra_fields else [])
                + ([Text("n/a", style="orange")] if libinfo else [])
                + (
                    [Text("<itself>", style="yellow")]
                    if (support_bound_to and "b" in extra_fields)
                    else []
                )
            )
            table.add_row(*row)

            first = False

    return table


def _list_endpoints(
    app: str,
    model: Optional[str] = None,
    color: str = "auto",
    extra_fields: List[str] = None,
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

    extra_fields = extra_fields or []
    libinfo = get_libinfo(app, model) if "v" in extra_fields else ()
    epinfo = (
        get_epinfo(app, model) if ("d" in extra_fields or "r" in extra_fields) else ()
    )

    c = Console(color_system=color)
    c.print(_render(endpoints, libinfo, epinfo, app, extra_fields))


def list_endpoints(
    app: str = typer.Argument(..., help="Application whose endpoints to show."),
    show_versions: bool = typer.Option(
        False,
        "-v",
        "--show-versions",
        is_flag=True,
        help="Show supported interface versions.",
    ),
    show_bindings: bool = typer.Option(
        False,
        "-b",
        "--show-bindings",
        is_flag=True,
        help="Show active remote binds (names of remote apps that this endpoint has active relations to).",
    ),
    show_interfaces: bool = typer.Option(
        False,
        "-i",
        "--show-interfaces",
        is_flag=True,
        help="Show the interface advertised by each endpoint.",
    ),
    show_required: bool = typer.Option(
        False,
        "-r",
        "--show-required",
        is_flag=True,
        help="Show the whether the relation is required.",
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

    extra_fields = []
    if show_versions:
        extra_fields.append("v")
    if show_bindings:
        extra_fields.append("b")
    if show_interfaces:
        extra_fields.append("i")
    if show_required:
        extra_fields.append("r")
    if show_descriptions:
        extra_fields.append("d")

    _list_endpoints(
        app=app,
        model=model,
        extra_fields=extra_fields,
        color=color,
    )


if __name__ == "__main__":
    _list_endpoints("tempo", extra_fields=list("vbird"))
