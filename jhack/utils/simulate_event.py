import os
import shlex
import stat
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import List

import typer

from jhack.config import get_jhack_data_path
from jhack.helpers import (
    JPopen,
    get_current_model,
    get_substrate,
    juju_agent_version,
    juju_log,
    show_unit,
)
from jhack.logger import logger as jhack_logger

_RELATION_EVENT_SUFFIXES = {
    "-relation-changed",
    "-relation-created",
    "-relation-joined",
    "-relation-broken",
    "-relation-departed",
}
_PEBBLE_READY_SUFFIX = "-pebble-ready"
OPS_DISPATCH = "OPERATOR_DISPATCH"
juju_context_id = "JUJU_CONTEXT_ID"
JHACK_DISPATCH_SCRIPT = "jhack_dispatch"

logger = jhack_logger.getChild("simulate_event")


def _get_relation_id(
        unit: str, endpoint: str, relation_remote_app: str = None, model: str = None
):
    unit = show_unit(unit, model=model)
    relation_info = unit.get("relation-info")
    if not relation_info:
        raise RuntimeError(
            f"No relation-info found in show-unit {unit} output. "
            f"Does this unit have any relation?"
        )

    for binding in relation_info:
        if binding["endpoint"] == endpoint:
            remote_app = next(iter(binding["related-units"])).split("/")[0]
            if relation_remote_app and remote_app != relation_remote_app:
                continue
            return binding["relation-id"]

    raise RuntimeError(f"unit {unit} has no active bindings to {endpoint}")


def _get_relation_endpoint(event: str):
    for suffix in _RELATION_EVENT_SUFFIXES:
        if suffix in event:
            return event[: -len(suffix)]
    return False


def _get_env(
        unit,
        event,
        relation_remote: str = None,
        override: List[str] = None,
        operator_dispatch: bool = False,
        model: str = None,
):
    current_model = get_current_model()
    env = {
        "JUJU_DISPATCH_PATH": f"hooks/{event}",
        "JUJU_MODEL_NAME": current_model,
        "JUJU_UNIT_NAME": unit,
    }

    if endpoint := _get_relation_endpoint(event):
        relation_remote_app = None
        if relation_remote:
            relation_remote_app = relation_remote.split("/")[0]
            env["JUJU_REMOTE_APP"] = relation_remote_app
            env["JUJU_REMOTE_UNIT"] = relation_remote

        relation_id = _get_relation_id(unit, endpoint, relation_remote_app, model=model)
        env["JUJU_RELATION"] = endpoint
        env["JUJU_RELATION_ID"] = str(relation_id)

        if event.endswith("-relation-departed"):
            env["JUJU_DEPARTING_UNIT"] = relation_remote

    if event.endswith(_PEBBLE_READY_SUFFIX):
        env["JUJU_WORKLOAD_NAME"] = event[: -len(_PEBBLE_READY_SUFFIX)]

    if override:
        for opt in override:
            if "=" not in opt:
                logger.error(
                    f"env option {opt!r} invalid: expected "
                    f'"<key>=<value>"; skipping...'
                )
                continue

            key, value = opt.split("=")
            env[key] = value

    if operator_dispatch:
        # TODO: Unclear what this flag does,
        #  but most of the time you want it to be false. Dig deeper?
        logger.debug("Inserting operator dispatch flag...")
        env[OPS_DISPATCH] = "1"
    else:
        if OPS_DISPATCH in env:
            logger.debug("Purged operator dispatch flag...")
            del env[OPS_DISPATCH]
    #
    for k, v in dict(env).items():
        if not isinstance(v, str):
            logger.warning(k, f"maps to a non-string val ({v}); casting...")
            v = str(v)

        if " " in v:
            # FIXME: find a way to quote this
            logger.warning(f"whitespace found in var {k}: skipping...")
            del env[k]

    if juju_context_id in env:
        logger.debug(f"removed {juju_context_id}")
        del env[juju_context_id]

    ctx_id = 1  # todo figure out what this needs to be
    env["JUJU_CONTEXT_ID"] = f"{unit}-run-commands-{ctx_id}"

    env.update({
        # full env printout: Using: j ssh loki/0 /bin/juju-exec -u loki/0 env
        "KUBERNETES_SERVICE_PORT_HTTPS": "443",
        "JUJU_METER_INFO": "not set",
        "KUBERNETES_SERVICE_PORT": "443",
        "JUJU_CHARM_HTTPS_PROXY": " ",
        "JUJU_MODEL_UUID": "68e5e28f-5a8d-4c50-8c1f-54e2823c0736",
        "JUJU_VERSION": "3.1.2",
        "CLOUD_API_VERSION": "1.27.0",
        "JUJU_CHARM_HTTP_PROXY": " ",
        "JUJU_UNIT_NAME": "loki/0",
        "PWD": "/var/lib/juju/agents/unit-loki-0/charm",
        "CHARM_DIR": "/var/lib/juju/agents/unit-loki-0/charm",
        "LANG": "C.UTF-8",
        "KUBERNETES_PORT_443_TCP": "tcp://10.152.183.1:443",
        "JUJU_HOOK_NAME": " ",
        "JUJU_AGENT_SOCKET_ADDRESS": "@/var/lib/juju/agents/unit-loki-0/agent.socket",
        "JUJU_AGENT_SOCKET_NETWORK": "unix",
        "JUJU_CHARM_FTP_PROXY": " ",
        "JUJU_AVAILABILITY_ZONE": " ",
        "JUJU_METER_STATUS": "AMBER",
        "TERM": "tmux-256color",
        "JUJU_CHARM_DIR": "/var/lib/juju/agents/unit-loki-0/charm",
        "JUJU_API_ADDRESSES": "10.152.183.33:17070 controller-service.controller-mk8scloud.svc.cluster.local:17070",
        "JUJU_PRINCIPAL_UNIT": " ",
        "SHLVL": "1",
        "KUBERNETES_PORT_443_TCP_PROTO": "tcp",
        "JUJU_MODEL_NAME": "clite",
        "KUBERNETES_PORT_443_TCP_ADDR": "10.152.183.1",
        "JUJU_MACHINE_ID": " ",
        "JUJU_SLA": "unsupported",
        "KUBERNETES_SERVICE_HOST": "10.152.183.1",
        "KUBERNETES_PORT": "tcp://10.152.183.1:443",
        "KUBERNETES_PORT_443_TCP_PORT": "443",
        "APT_LISTCHANGES_FRONTEND": "none",
        "DEBIAN_FRONTEND": "noninteractive",
        "JUJU_CHARM_NO_PROXY": "127.0.0.1,localhost,::1"}
    )

    return " ".join(f'{k}="{v}"' for k, v in env.items())


def push_dispatch_script(jhack_dispatch_script_path: str, env: str, unit: str, _model: str, dry_run: bool = False):
    print('shelling over jhack dispatch script...')

    with tempfile.TemporaryDirectory(prefix=str(Path("~/.local/share/juju/foo").expanduser())) as f:
        script = Path(f) / 'script'
        unit_sanitized = unit.replace('/', '-')
        agent_root = f"/var/lib/juju/agents/unit-{unit_sanitized}"
        remote_charm_root = f"{agent_root}/charm"

        script.write_text(
            textwrap.dedent(
                f"""
                #!/bin/sh   
                cd {remote_charm_root}
                OPATH=$PATH
                PATH="$PATH:/var/lib/juju/tools/unit-{unit_sanitized}"  
                {env} ./dispatch
                PATH=$OPATH
                """
            )
        )
        st = os.stat(script)
        os.chmod(script, st.st_mode | stat.S_IEXEC)

        cmd = f"juju scp {_model}{script} {unit}:{jhack_dispatch_script_path}"

        if dry_run:
            print(f'would run: \n\t{cmd}')
            return

        proc = JPopen(shlex.split(cmd))

        proc.wait()
        if proc.returncode != 0:
            logger.error(f"cmd {cmd} terminated with {proc.returncode}; "
                         f"\n\tstdout={proc.stdout.read()}; "
                         f"\n\tstderr={proc.stderr.read()}")


def _simulate_event(
        unit,
        event,
        relation_remote: str = None,
        operator_dispatch: bool = False,
        env_override: List[str] = None,
        print_captured_stdout: bool = False,
        print_captured_stderr: bool = False,
        emit_juju_log: bool = True,
        model: str = None,
        dry_run: bool = False,
):
    env = _get_env(
        unit,
        event,
        relation_remote=relation_remote,
        override=env_override,
        operator_dispatch=operator_dispatch,
    )

    _model = f"-m {model} " if model else ""

    # note juju-exec is juju-run in juju<3.0
    version = juju_agent_version()
    if version is None:
        raise RuntimeError("is juju installed?")

    dispatch_script_path = f"/var/lib/juju/agents/unit-loki-0/charm/{JHACK_DISPATCH_SCRIPT}"
    push_dispatch_script(dispatch_script_path, env, unit, _model, dry_run)

    cmd = f"juju ssh {_model}{unit} {env} {dispatch_script_path}"
    if dry_run:
        print(f'would run: \n\t{cmd}')
        return

    logger.info(cmd)
    proc = JPopen(shlex.split(cmd))
    proc.wait()

    if proc.returncode != 0:
        logger.error(f"cmd {cmd} terminated with {proc.returncode}")
        logger.error(f"stdout={proc.stdout.read()}")
        logger.error(f"stderr={proc.stderr.read()}")
    else:
        if print_captured_stdout and (stdout := proc.stdout.read()):
            print(f"[captured stdout: ]\n{stdout.decode('utf-8')}")
        if print_captured_stderr and (stderr := proc.stderr.read()):
            print(f"[captured stderr: ]\n{stderr.decode('utf-8')}")

    in_model = f" in model {model}" if model else ""
    print(f"Fired {event} on {unit}{in_model}.")

    if emit_juju_log:
        juju_log(unit, f"The previous {event} was fired by jhack.", model=model)


def simulate_event(
        unit: str = typer.Argument(
            ..., help="The unit on which you'd like this event to be fired."
        ),
        event: str = typer.Argument(
            ...,
            help="The name of the event to fire. "
                 "Needs to be a valid event name for the unit; e.g."
                 " - 'start'"
                 " - 'config-changed' # no underscores"
                 " - 'my-relation-name-relation-joined' # write it out in full",
        ),
        relation_remote: str = typer.Option(
            None,
            help="Name of the remote app that a relation event should be interpreted against."
                 "Given that a relation can have multiple remote ends, this is used to determine "
                 "which remote that is. E.g."
                 " - fire foo-relation-changed --remote bar  # some bar unit touched the 'foo' "
                 "relation data."
                 " - fire foo-relation-departed --remote bar/0  # the remote bar/0 unit left the "
                 "'foo' relation.",
        ),
        show_output: bool = typer.Option(
            True,
            "-s",
            "--show-output",
            help="Whether to show the stdout/stderr captured during the scope of the event. "
                 "If False, it should show up anyway in the juju debug-log.",
        ),
        env_override: List[str] = typer.Option(
            None,
            "--env",
            "-e",
            help="Key-value mapping to override any ENV with. For whatever reason."
                 "E.g."
                 " - fire foo-pebble-ready --env JUJU_DEPARTING_UNIT_NAME=remote/0 --env FOO=bar",
        ),
        model: str = typer.Option(
            None, "-m", "--model", help="Which model to apply the command to."
        ),
        operator_dispatch: bool = typer.Option(
            False, "-o", "--operator-dispatch", help="Set the mysterious OPERATOR_DISPATCH envvar."
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            is_flag=True,
            help="Don't actually *do* anything, just print what you would have done.",
        )
):
    """Simulates an event on a unit.

    Especially useful in combination with jhack charm sync and/or debug-code/debug-hooks.
    """
    return _simulate_event(
        unit,
        event,
        relation_remote=relation_remote,
        env_override=env_override,
        print_captured_stdout=show_output,
        print_captured_stderr=show_output,
        model=model,
        operator_dispatch=operator_dispatch,
        dry_run=dry_run
    )


if __name__ == "__main__":
    _simulate_event(
        "loki/0",
        "update-status",
        print_captured_stdout=True,
        print_captured_stderr=True,
    )
