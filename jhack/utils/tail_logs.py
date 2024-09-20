import os
import shlex
import select
import subprocess
from dataclasses import dataclass
from multiprocessing.pool import ThreadPool
from pathlib import Path
from platform import system
from tempfile import NamedTemporaryFile
from time import sleep
from typing import Tuple

import yaml
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel

from jhack.helpers import Target, fetch_file
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("tail_logs")


class ConsolePane:
    def __init__(self):
        self.content = ""

    def print(self, msg: str):
        self.content += msg

    def __rich_console__(self, console, options):
        for line in console.render_lines(
            self.content, options=options, pad=False, new_lines=False
        )[-options.height :]:
            yield from line


def _redirect_logs(command, pane: ConsolePane):
    logger.debug(f"starting log redirection with {command}")
    proc = subprocess.Popen(
        command,
        universal_newlines=True,
        bufsize=1000,
        stdout=subprocess.PIPE,
    )
    poll = select.poll()
    poll.register(proc.stdout)

    while True:
        if poll.poll(1):
            for line in proc.stdout.readlines():
                pane.print(line.strip())


def _tail_juju_debug_log(target: Target, pane: ConsolePane):
    cmd = f"juju debug-log --replay -i {target.unit_name}"
    _redirect_logs(shlex.split(cmd), pane)


def _pebble_cmd(target: Target, *, command: str, container: str = "charm"):
    return shlex.split(
        f"juju ssh {target.unit_name} PEBBLE_SOCKET=/charm/containers/{container}/pebble.socket /charm/bin/pebble {command}"
    )


def _pebble(target: Target, *, command: str, container: str = "charm"):
    """Run a pebble command on a unit."""
    cmd = _pebble_cmd(target, command=command, container=container)
    proc = subprocess.Popen(
        cmd, universal_newlines=True, bufsize=1000, stdout=subprocess.PIPE
    )
    proc.wait()
    return proc.stdout.read()


def _tail_pebble_service_logs(
    target: Target, pane: ConsolePane, container: str, service_name: str
):
    cmd = _pebble_cmd(target, command=f"logs {service_name} -f", container=container)
    _redirect_logs(cmd, pane)


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
    return tuple(_Service(line.split()[0].strip()) for line in out.splitlines()[1:])


def _tail_logs(
    target: str,
    kubernetes_log: bool = True,
    workload_logs: bool = True,
):
    target = Target.from_name(target)

    tails = []
    layout = Layout()
    if workload_logs:
        workload_layouts_inner = Layout(name="workloads")
        container_layouts = []
        for container in get_container_names(target):
            container_layout = Layout(name=container)
            services_layouts = []
            for service in get_services(target, container):
                name = f"{container}:{service.name}"
                svc_pane = ConsolePane()
                # services_layouts.append(Panel(svc_pane, title=name))
                services_layouts.append(svc_pane)
                tails.append(
                    [
                        _tail_pebble_service_logs,
                        (target, svc_pane, container, service.name),
                    ]
                )
            container_layout.split_column(*services_layouts)
            container_layouts.append(container_layout)

        workload_layouts_inner.split_row(*container_layouts)
        workload_layout = Layout(Panel(workload_layouts_inner, title="workloads"))
    else:
        workload_layout = Layout(visible=False)

    if kubernetes_log:
        k8s_pane = ConsolePane()
        k8s_layout = Layout(Panel(k8s_pane, title="k8s"), name="k8s")
    else:
        k8s_layout = Layout(visible=False)

    layout.split_row(
        workload_layout,
        k8s_layout,
    )

    tp = ThreadPool()

    with Live(layout):
        results = []
        for tail in tails:
            results.append(tp.apply_async(*tail))

        try:
            while True:
                sleep(1)

        except KeyboardInterrupt:
            tp.terminate()
            exit("interrupted by user")


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
