import json
import re
from subprocess import PIPE, Popen
from time import sleep

import typer
from rich.console import Console
from rich.text import Text

from jhack.helpers import get_models

ENVIRON = r"""SHELL=/bin/bash
KUBERNETES_SERVICE_PORT_HTTPS=443
WEBSERVER_SERVICE_PORT=65535
JUJU_METER_INFO=not set
WEBSERVER_SERVICE_PORT_PLACEHOLDER=65535
KUBERNETES_SERVICE_PORT=443
DATABASE_PORT_65535_TCP_ADDR=10.152.183.157
JUJU_CHARM_HTTPS_PROXY=
TMUX=/tmp/tmux-0/default,8469,1
HOSTNAME={app_name}-{unit_id}
DATABASE_PORT_65535_TCP_PORT=65535
JUJU_MODEL_UUID={model_uuid}
JUJU_VERSION={juju_version}
CLOUD_API_VERSION=1.25.0
JUJU_CHARM_HTTP_PROXY=
MODELOPERATOR_PORT_17071_TCP_ADDR=10.152.183.212
DATABASE_SERVICE_PORT_PLACEHOLDER=65535
WEBSERVER_PORT_65535_TCP=tcp://10.152.183.62:65535
DATABASE_PORT_65535_TCP_PROTO=tcp
JUJU_UNIT_NAME={app_name}/{unit_id}
PWD=/var/lib/juju/agents/unit-{app_name}-{unit_id}/charm
DATABASE_SERVICE_HOST=10.152.183.157
CHARM_DIR=/var/lib/juju/agents/unit-{app_name}-{unit_id}/charm
WEBSERVER_PORT=tcp://10.152.183.62:65535
HOME=/root
LANG=C.UTF-8
KUBERNETES_PORT_443_TCP=tcp://10.152.183.1:443
WHEELHOUSE=/tmp/wheelhouse
BYOBU_BACKEND=tmux
WEBSERVER_PORT_65535_TCP_PORT=65535
DATABASE_PORT=tcp://10.152.183.157:65535
JUJU_HOOK_NAME={event_name}
WEBSERVER_PORT_65535_TCP_ADDR=10.152.183.62
JUJU_AGENT_SOCKET_ADDRESS=@/var/lib/juju/agents/unit-{app_name}-{unit_id}/agent.socket
MODELOPERATOR_SERVICE_HOST=10.152.183.212
JUJU_CHARM_FTP_PROXY=
JUJU_AVAILABILITY_ZONE=
PIP_WHEEL_DIR=/tmp/wheelhouse
JUJU_METER_STATUS=AMBER
TERM=tmux-256color
JUJU_CHARM_DIR=/var/lib/juju/agents/unit-{app_name}-{unit_id}/charm
JUJU_DEBUG=/tmp/juju-debug-hooks-2488589566
JUJU_API_ADDRESSES=10.152.183.141:17070 controller-service.controller-{cloud}.svc.cluster.local:17070
JUJU_PRINCIPAL_UNIT=
TMUX_PANE=%2
SHLVL=1
MODELOPERATOR_PORT_17071_TCP=tcp://10.152.183.212:17071
JUJU_CONTAINER_NAMES={container_names}
KUBERNETES_PORT_443_TCP_PROTO=tcp
JUJU_MODEL_NAME={model_name}
KUBERNETES_PORT_443_TCP_ADDR=10.152.183.1
MODELOPERATOR_PORT_17071_TCP_PORT=17071
DATABASE_PORT_65535_TCP=tcp://10.152.183.157:65535
JUJU_MACHINE_ID=
JUJU_SLA=unsupported
MODELOPERATOR_PORT=tcp://10.152.183.212:17071
KUBERNETES_SERVICE_HOST=10.152.183.1
KUBERNETES_PORT=tcp://10.152.183.1:443
KUBERNETES_PORT_443_TCP_PORT=443
PIP_FIND_LINKS=/tmp/wheelhouse
PATH=/var/lib/juju/tools/unit-{app_name}-{unit_id}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/charm/bin
JUJU_DISPATCH_PATH=hooks/{event_name}
WEBSERVER_SERVICE_HOST=10.152.183.62
JUJU_AGENT_SOCKET_NETWORK=unix
WEBSERVER_PORT_65535_TCP_PROTO=tcp
DATABASE_SERVICE_PORT=65535
HTTP_PROBE_PORT=3856
APT_LISTCHANGES_FRONTEND=none
MODELOPERATOR_PORT_17071_TCP_PROTO=tcp
DEBIAN_FRONTEND=noninteractive
MODELOPERATOR_SERVICE_PORT=17071
JUJU_CHARM_NO_PROXY=127.0.0.1,localhost,::1
_=/usr/bin/env"""


def build_env(event: str, target: str, model: str = None):
    model_info = get_models()
    if model is None:
        model = model_info["current-model"]
    model_data = next(filter(lambda m: m["short-name"] == model, model_info["models"]))
    model_uuid = model_data["model-uuid"]
    cloud = model_data["cloud"]
    agent_version = model_data["agent-version"]

    app_name, unit_id = target.split("/")
    replacements = {
        "app_name": app_name,
        "unit_id": unit_id,
        "model_uuid": model_uuid,
        "model_name": model,
        "container_names": "foo",
        "cloud": cloud,
        "juju_version": agent_version,
        "event_name": event,
    }
    text = ENVIRON.format(**replacements)
    pairs = dict(pair.split("=") for pair in text.split("\n"))
    escaped = " ".join("=".join((k, f"'{v}'")) for k, v in pairs.items())
    return escaped


def _fire(event: str, target: str, model: str = None):
    env = build_env(event, target, model)

    cmd = f" {env} /var/lib/juju/agents/unit-{target.replace('/', '-')}/charm/dispatch"
    outer_cmd = f"juju exec -u {target} -- {cmd}"
    proc = Popen(outer_cmd.split(), stdout=PIPE, stderr=PIPE)
    while proc.returncode is None:
        print("waiting for response...")
        proc.wait()
        sleep(0.2)
    # print(outer_cmd)
    # return
    stdout, stderr = (c.read().decode("utf-8") for c in (proc.stdout, proc.stderr))
    console = Console()
    if proc.returncode != 0 or stderr:
        console.print(Text("completed with errors", style="red bold"))
        console.print(stderr)
    else:
        console.print(Text("completed without errors", style="green bold"))

    if stdout:
        console.print(Text("standard output follows:", style="bold"))
        console.print(stdout)


def fire(
    event: str = typer.Argument(..., help="Name of the event to fire."),
    target: str = typer.Argument(..., help="Who to fire it on."),
    model: str = typer.Argument(
        None, help="The model the target is in. " "Defaults to *the current model*."
    ),
):
    return _fire(event, target, model)


if __name__ == "__main__":
    _fire("update-status", "trfk/0", None)
