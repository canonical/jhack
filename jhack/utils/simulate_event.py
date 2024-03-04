from typing import List

import typer

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
            try:
                remote_app = next(iter(binding["related-units"])).split("/")[0]
            except KeyError:
                # possible peer relation!
                if binding["related-endpoint"] == endpoint:
                    return binding["relation-id"]
                raise

            if relation_remote_app and remote_app != relation_remote_app:
                continue

            return binding["relation-id"]

    raise RuntimeError(f"unit {unit} has no active bindings to {endpoint}")


def _get_relation_endpoint(event: str):
    for suffix in _RELATION_EVENT_SUFFIXES:
        if suffix in event:
            return event[: -len(suffix)]
    return False


def build_event_env(
    unit,
    event,
    relation_remote: str = None,
    override: List[str] = None,
    operator_dispatch: bool = False,
    model: str = None,
    glue: str = " ",
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

    return glue.join(f"{k}={v}" for k, v in env.items())


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
    if not len(unit.split("/")) == 2:
        raise ValueError(
            f"invalid unit name: should be something like 'foo/0', not {unit}"
        )

    env = build_event_env(
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

    juju_exec_cmd = "/usr/bin/" + ("juju-exec" if version >= (3, 0) else "juju-run")
    if get_substrate(_model) != "k8s":
        juju_exec_cmd = "sudo " + juju_exec_cmd

    cmd = f"juju ssh {_model}{unit} {juju_exec_cmd} -u {unit} {env} ./dispatch"

    if dry_run:
        print(f"would run: \n\t{cmd}")
        return

    logger.info(cmd)
    proc = JPopen(cmd.split())
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
    dry_run: bool = typer.Option(
        None, "--dry-run", help="Do nothing, print out what would have happened."
    ),
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
        dry_run=dry_run,
    )


if __name__ == "__main__":
    _simulate_event(
        "catalogue/0",
        "replicas-relation-created",
        print_captured_stdout=True,
        print_captured_stderr=True,
    )
