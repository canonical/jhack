import shlex
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import sleep
from typing import Tuple, Iterable, Dict

import yaml
from rich.console import ConsoleOptions, Console
from rich.layout import Layout, RenderMap
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from jhack.helpers import Target, fetch_file
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("tail_logs")


class Pane(Table):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.trimmed = []

    def trim(self, size: int):
        if self.row_count > size:
            self.trimmed.extend(self.rows[:-size])
            self.rows = self.rows[-size:]
        else:
            while self.row_count < size:
                self.add_row(self.trimmed.pop(0))

    def clear(self):
        self.trimmed.extend(self.rows)
        self.rows = []


class PaneLayout(Layout):
    def __init__(self, pane: Pane, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pane = pane

    def render(self, console: Console, options: ConsoleOptions) -> RenderMap:
        rm = super().render(console, options)
        max_table_len = rm[self].region.height
        self.pane.trim(max_table_len)
        return rm


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
    proc = subprocess.Popen(cmd, bufsize=1000, stdout=subprocess.PIPE)
    proc.wait()
    return proc.stdout.read()


def _update_layout_with_service_logs(
    target: Target, layout: PaneLayout, service_name: str, container: str = None
):
    container_var = (
        f" PEBBLE_SOCKET=/charm/containers/{container}/pebble.socket"
        if container
        else ""
    )
    cmd = rf"juju ssh {target.unit_name}{container_var} /charm/bin/pebble logs {service_name}"

    # put pebble logs into a file
    out = subprocess.getoutput(cmd)
    layout.pane.clear()
    layout.pane.add_row(cmd)

    for line in out.splitlines():
        layout.pane.add_row(line)


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


def get_services(target: Target, container: str) -> Tuple[_Service, ...]:
    out = _pebble(target, container=container, command="services")
    return tuple(
        _Service(line.split()[0].strip().decode("utf-8"))
        for line in out.splitlines()[1:]
    )


def _pane_name(container: str, service: _Service):
    return f"{container}::{service.name}"


def make_layout(containers_to_services: Dict[str, Iterable[_Service]]) -> Layout:
    """Define the layout."""
    layout = Layout(name="root")

    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=7),
    )

    layout["main"].split_row(
        *(Layout(name=container) for container in containers_to_services)
    )

    for container, services in containers_to_services.items():
        service_layouts = []
        for service in services:
            svc_pane = Pane(border_style="green", expand=True, title=service)
            service_layouts.append(
                *(
                    PaneLayout(svc_pane, name=_pane_name(container, service))
                    for service in services
                )
            )
        layout[container].split_column(*service_layouts)
    return layout


class Header:
    def __rich__(self) -> Panel:
        grid = Pane.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right")
        grid.add_row(
            "[b]jhack debug-log[/b]",
            datetime.now().ctime().replace(":", "[blink]:[/]"),
        )
        return Panel(grid, style="white on blue")


def _tail_logs(
    target: str,
    kubernetes_log: bool = True,
    workload_logs: bool = True,
):
    target = Target.from_name(target)
    container_to_services = {
        container: get_services(target, container)
        for container in get_container_names(target)
    }

    layout = make_layout(container_to_services)
    layout["header"].update(Header())
    layout["footer"].update(str(container_to_services))

    def update_all():
        for container, services in container_to_services.items():
            for service in services:
                _update_layout_with_service_logs(
                    target,
                    layout[_pane_name(container, service)],
                    service_name=service.name,
                )

    with Live(layout, auto_refresh=False, screen=True) as live:
        try:
            while True:
                update_all()

                live.refresh()
                sleep(0.5)

        except KeyboardInterrupt:
            live.stop()
            exit("interrupted.")

    # if kubernetes_log:
    #     k8s_pane = Pane()
    #     k8s_layout = Layout(Panel(k8s_pane, title="k8s"), name="k8s")
    # else:
    #     k8s_layout = Layout(visible=False)

    # layout.split_row(
    #     workload_layout,
    #     k8s_layout,
    # )
    #
    # try:
    #     with Live(layout, auto_refresh=False) as live:
    #         threads = []
    #         for fn, args in tails:
    #             thread = Thread(target=fn, args=args)
    #             threads.append(thread)
    #             thread.start()
    #
    #             while True:
    #                 sleep(0.2)
    #                 live.refresh()
    #
    # except KeyboardInterrupt:
    #     for thread in threads:
    #         thread.join()
    #     exit("interrupted by user")
    #


def tail_logs(
    target: str,
    workload_logs: bool = True,
    kubernetes_log: bool = False,
):
    return _tail_logs(
        target=target,
        kubernetes_log=kubernetes_log,
        workload_logs=workload_logs,
    )


if __name__ == "__main__":
    _tail_logs("tempo/0")
