import shlex
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from subprocess import CalledProcessError
from tempfile import NamedTemporaryFile
from time import sleep
from typing import Tuple, Iterable, Dict, Union, List, Sequence, Optional
from xml.etree.ElementInclude import include

import typer
import yaml
from rich.abc import RichRenderable
from rich.console import ConsoleOptions, Console
from rich.layout import Layout, RenderMap
from rich.live import Live
from rich.panel import Panel
from rich.pretty import Pretty
from rich.style import Style
from rich.table import Table

from jhack.helpers import Target, fetch_file
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("tail_logs")

DEFAULT_REFRESH_RATE = 0.5


class SvcLogTable(Table):
    def __init__(
        self, target: Target, container: str, service: str, *args, **kwargs
    ) -> None:
        super().__init__(
            *args,
            **kwargs,
            show_header=False,
            title=_pane_name(container, service, styled=True),
        )
        self.target = target
        self.container = container
        self.service = service

    def clear(self):
        # reinitialize
        self.rows = []
        self.columns = []

    def update(self, max_height: int):
        container_var = (
            f" PEBBLE_SOCKET=/charm/containers/{self.container}/pebble.socket"
            if self.container
            else ""
        )
        # 1 for the title, 2 for the frame edges
        available_lines = max_height - 3
        cmd = rf"juju ssh {self.target.unit_name}{container_var} \
        /charm/bin/pebble logs {self.service} | tail -n {available_lines}"

        try:
            out = subprocess.getoutput(cmd)
        except CalledProcessError:
            logger.exception()
            exit(f"error executing {cmd}")

        self.clear()

        if not out:
            self.add_row("<no logs>")

        for line in out.splitlines():
            self.add_row(line)

    def __rich_console__(self, console: "Console", options: "ConsoleOptions"):
        self.update(options.max_height)
        return super().__rich_console__(console, options)


def _pebble(target: Target, *, command: str, container: str = "charm"):
    """Run a pebble command on a unit."""
    container_var = (
        f" PEBBLE_SOCKET=/charm/containers/{container}/pebble.socket"
        if container
        else ""
    )
    cmd = shlex.split(
        rf"juju ssh {target.unit_name}{container_var} /charm/bin/pebble {command}"
    )
    try:

        proc = subprocess.Popen(cmd, bufsize=1000, stdout=subprocess.PIPE)
        proc.wait()

    except CalledProcessError:
        logger.error("")
        return ""

    if proc.returncode != 0:
        logger.error(f"pebble command {cmd} exited nonzero: container might be down?")
        return ""

    return proc.stdout.read()


def get_container_names(target: Target) -> Tuple[str, ...]:
    # we could do:
    # cmd = "microk8s.kubectl get pod tempo-0 -n status-test -o json | jq -r '[.status.containerStatuses[] | .name]' "
    # but given snap and all, we can't be sure the user is using microk8s.
    # either way we can't be sure where we can get the kubectl command from
    try:
        with NamedTemporaryFile() as f:
            path = Path(f.name)
            try:
                fetch_file(target.unit_name, "metadata.yaml", path)
            except RuntimeError:
                fetch_file(target.unit_name, "charmcraft.yaml", path)
            meta = yaml.safe_load(path.read_text())
    except:
        logger.exception(
            f"failed to get metadata.yaml|charmcraft.yaml from {target.unit_name}"
        )
        return ()

    containers = meta.get("containers", {})
    return tuple(containers)


@dataclass
class _Service:

    name: str
    startup: str
    active: bool

    @staticmethod
    def from_pebble_output(line: bytes):
        service, startup, current, *_ = (
            x.strip() for x in line.decode("utf-8").split()
        )
        return _Service(service, startup, current == "active")

    @property
    def active_icon(self):
        return ":green_circle:" if self.active else ":red_circle:"


def get_services(target: Target, container: str) -> Tuple[_Service, ...]:
    out = _pebble(target, container=container, command="services")

    return tuple(_Service.from_pebble_output(line) for line in out.splitlines()[1:])


def _pane_name(container: str, service: Union[str, _Service], styled=False):
    if styled:
        return f"[b red]{container}[/][dim]::[/][b cyan]{getattr(service,'name', service)}[/]"
    return f"{container}::{getattr(service,'name', service)}"


class Header:
    def __init__(self, target: Target):
        self.target = target

    def __rich__(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right")
        grid.add_row(
            "[b]jhack [purple]debug-log[/purple][/b] v0.1",
            f"[bold orange]{self.target.unit_name}[/]",
        )
        return Panel(grid, style="white on blue")


class Footer:
    def __init__(self, spec: Dict[str, Sequence[_Service]]):
        super().__init__()
        self.spec = spec
        self.size = len(self.spec) + sum(len(svcs) for svcs in self.spec.values())

    def __rich__(self) -> Panel:
        from rich.tree import Tree

        table = Table.grid(padding=(0, 1, 0, 0))
        table.add_row("Ω", "[dim]log streams[/]")

        tree = Tree(
            table,
            highlight=True,
        )
        for container, services in self.spec.items():
            if not services:
                tree.add(container + ":bomb:")
                continue

            node = tree.add(container)
            for service in services:
                node.add(
                    f"[b cyan]{service.name}[/] [bold](startup={service.startup})[/] {service.active_icon}"
                )

        return Panel(tree)


def make_pebble_layout(target: Target, include_containers: Optional[List[str]]):
    main = Layout(name="main")
    containers_to_services = {
        container: get_services(target, container)
        for container in get_container_names(target)
    }
    if not containers_to_services:
        exit(f"no containers found on {target.unit_name}")

    container_layouts = []
    for container, services in containers_to_services.items():
        if (not include_containers) or (container in include_containers):
            service_layouts = []
            for service in services:
                svc_pane = SvcLogTable(
                    service=service.name,
                    container=container,
                    target=target,
                    border_style="green",
                    expand=True,
                )
                service_layouts.append(
                    *(
                        Layout(svc_pane, name=_pane_name(container, service), ratio=1)
                        for service in services
                    )
                )
            container_layout = Layout(name=container)
            container_layout.split_column(*service_layouts)
            container_layouts.append(container_layout)

    main.split_column(*container_layouts)

    footer = Footer(containers_to_services)
    footer_layout = Layout(footer, size=footer.size + 3, name="footer")
    return main, footer_layout


def make_juju_log_layout(target: Target):
    svc_pane = SvcLogTable(
        target=target,
        border_style="blue",
        expand=True,
    )
    main = Layout(svc_pane, name="main")
    return main


def make_layout(
    target: Target,
    show_tree: bool = True,
    juju_logs: bool = True,
    pebble_logs: bool = True,
    include_containers: Optional[List[str]] = None,
) -> Layout:
    """Define the layout."""

    layout = Layout(name="root")

    pebble_layout, pebble_footer = None, None
    if pebble_logs:
        pebble_layout, pebble_footer = make_pebble_layout(target, include_containers)

    layout.split(
        *filter(
            None,
            (
                Layout(Header(target), name="header", size=3),
                pebble_layout,
                pebble_footer
                # root node, and top and bottom panel edges
            ),
        )
    )

    return layout


def _tail_logs(
    target: str,
    refresh_rate: float = DEFAULT_REFRESH_RATE,
    show_tree: bool = True,
    juju_logs: bool = True,
    pebble_logs: bool = True,
    include_containers: Optional[List[str]] = None,
):
    layout = make_layout(
        Target.from_name(target),
        pebble_logs=pebble_logs,
        include_containers=include_containers,
        juju_logs=juju_logs,
        show_tree=show_tree,
    )

    with Live(layout, refresh_per_second=refresh_rate, screen=True) as live:
        try:
            while True:
                time.sleep(100)

        except KeyboardInterrupt:
            live.stop()
            exit("interrupted.")


def tail_logs(
    target: str = typer.Argument("Target unit. For example: `prometheus-k8s/0`."),
    refresh_rate: float = typer.Option(
        DEFAULT_REFRESH_RATE, help="Refreshes per second (goal)."
    ),
    juju_logs: bool = typer.Option(
        True,
        "-j",
        "--include-juju-logs",
        help="Include the juju debug-log output for the target.",
    ),
    pebble_logs: bool = typer.Option(
        True, "-p", "--include-pebble-logs", help="Include the pebble service logs."
    ),
    include_container: List[str] = typer.Option(
        None,
        "--include-container",
        help="Only tail from this container "
        "(only works in conjunction with pebble_logs).",
    ),
    hide_tree=typer.Option(
        False,
        is_flag=True,
        help="Hide the container/services overview tree shown in the footer.",
    ),
):
    return _tail_logs(
        target=target,
        refresh_rate=refresh_rate,
        show_tree=not hide_tree,
        juju_logs=juju_logs,
        pebble_logs=pebble_logs,
        include_containers=include_container,
    )


if __name__ == "__main__":
    _tail_logs("tempo/0")
