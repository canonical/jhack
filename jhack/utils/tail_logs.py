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


class JujuLogTable(Table):
    def __init__(self, target: Target, *args, **kwargs) -> None:
        super().__init__(
            *args,
            **kwargs,
            show_header=False,
            title=_jdl_pane_name(target, styled=True),
        )
        self.target = target

    def clear(self):
        # reinitialize
        self.rows = []
        self.columns = []

    def update(self, max_height: int):
        # 1 for the title, 2 for the frame edges
        available_lines = max_height
        cmd = rf"juju debug-log --include {self.target.unit_name} | tail -n {available_lines}"

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
    sname = getattr(service, "name", service)
    if styled:
        return f"[b red]{container}[/][dim]::[/][b cyan]{sname}[/]"
    return f"{container}::{sname}"


def _jdl_pane_name(target: Union[str, Target], styled=False):
    tname = getattr(target, "unit_name", target)
    if styled:
        return f"[b red]juju-logs[/][dim]::[/][b cyan]{tname}[/]"
    return f"juju-logs::{tname}"


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


def make_pebble_layout(
    target: Target, include_containers: Optional[List[str]], show_tree: bool = True
):
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

    if not show_tree:
        main = Layout(name="pebble-main")
        main.split_column(*container_layouts)
        return main

    services = Layout(name="services")
    services.split_column(*container_layouts)

    footer = Footer(containers_to_services)
    footer_layout = Layout(footer, size=footer.size + 3, name="footer")
    main = Layout(name="pebble-main")
    main.split_column(services, footer_layout)
    return main


def make_juju_log_layout(target: Target):
    svc_pane = JujuLogTable(
        target=target,
        border_style="blue",
        expand=True,
    )
    main = Layout(svc_pane, name="jdl-main")
    return main


def make_layout(
    target: Target,
    include: str,
    include_containers: Optional[List[str]] = None,
) -> Layout:
    """Define the layout."""

    show_tree = "t" in include
    juju_logs = "j" in include
    pebble_logs = "p" in include

    root = Layout(name="root")
    header = Layout(Header(target), name="header", size=3)
    body = Layout(name="body")
    body.split_row(
        *filter(
            None,
            [
                (make_juju_log_layout(target) if juju_logs else None),
                (
                    make_pebble_layout(target, include_containers, show_tree=show_tree)
                    if pebble_logs
                    else None
                ),
            ],
        )
    )
    root.split_column(header, body)
    return root


def _tail_logs(
    target: str,
    refresh_rate: float = DEFAULT_REFRESH_RATE,
    include_containers: Optional[List[str]] = None,
    include: str = "jpt",
):

    layout = make_layout(
        Target.from_name(target), include_containers=include_containers, include=include
    )

    with Live(
        layout,
        refresh_per_second=refresh_rate,
        screen=True,
        vertical_overflow="visible",
    ) as live:
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
    include: str = typer.Option(
        "jpt",
        "-i",
        "--include",
        help="Log streams to include."
        "``j``: Include the juju debug-log output for the target. \n"
        "``t``: Print a summary of the pebble services status for all containers. \n"
        "``p``: Include the pebble service logs from all containers. \n",
    ),
    include_container: List[str] = typer.Option(
        None,
        "--include-container",
        help="Only tail from this container "
        "(only works in conjunction with pebble_logs).",
    ),
):
    return _tail_logs(
        target=target,
        refresh_rate=refresh_rate,
        include=include,
        include_containers=include_container,
    )


if __name__ == "__main__":
    _tail_logs("tempo/0")
