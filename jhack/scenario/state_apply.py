#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import os
import shlex
import sys
from pathlib import Path
from subprocess import CalledProcessError, run
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional

import typer

from jhack.scenario.dict_to_state import dict_to_state
from jhack.scenario.errors import InvalidTargetUnitName, StateApplyError
from jhack.scenario.utils import JujuUnitName
from scenario.state import (
    Container,
    DeferredEvent,
    Mount,
    Port,
    Secret,
    State,
    StoredState,
    _EntityStatus,
)
from jhack.logger import logger as jhack_root_logger

if TYPE_CHECKING:
    from scenario.state import AnyRelation

SNAPSHOT_DATA_DIR = (Path(os.getcwd()).parent / "snapshot_storage").absolute()

logger = jhack_root_logger.getChild("snapshot")


def set_relation(relation: "AnyRelation") -> List[str]:
    out = []
    for key, value in relation.local_app_data.items():
        out.append(f"relation-set -r {relation.relation_id} --app {key}='{value}'")
    for key, value in relation.local_unit_data.items():
        out.append(f"relation-set -r {relation.relation_id} {key}='{value}'")
    return out


def set_relations(relations: Iterable["AnyRelation"]) -> List[str]:
    logger.info("preparing relations...")
    out = []
    for relation in relations:
        out.extend(set_relation(relation))
    return out


def set_status(
    unit_status: _EntityStatus,
    app_status: _EntityStatus,
    app_version: str,
) -> List[str]:
    logger.info("preparing status...")
    cmds = []

    if unit_status.name == "unknown":
        logger.warning("Cannot set unit status to unknown. Only Juju can.")
    else:
        cmds.append(f"status-set {unit_status.name} {unit_status.message}")

    if app_status.name == "unknown":
        logger.warning("Cannot set app status to unknown. Only Juju can.")
    else:
        cmds.append(f"status-set --application {app_status.name} {app_status.message}")

    cmds.append(f'application-version-set "{app_version}"')
    return cmds


def set_config(config: Dict[str, str], target: JujuUnitName) -> List[str]:
    logger.info("preparing config...")
    cmds = []
    if config:
        for key, value in config.items():
            cmds.append(f"juju config {target.unit_name} {key}={value}")
    return cmds


def set_opened_ports(opened_ports: List[Port]) -> List[str]:
    logger.info("preparing opened ports...")
    # fixme: this will only open new ports, it will not close all already-open ports.

    cmds = []

    for port in opened_ports:
        cmds.append(f"open-port {port.port}/{port.protocol}")

    return cmds


def set_containers(containers: Iterable[Container]) -> List[str]:
    logger.info("preparing containers...")
    if containers:
        logger.warning("set_containers not implemented yet")
    return []


def set_secrets(secrets: Iterable[Secret]) -> List[str]:
    logger.info("preparing secrets...")
    if secrets:
        logger.warning("set_secrets not implemented yet")
    return []


def set_deferred_events(
    deferred_events: Iterable[DeferredEvent],
) -> List[str]:
    logger.info("preparing deferred_events...")
    if deferred_events:
        logger.warning("set_deferred_events not implemented yet")
    return []


def set_stored_state(stored_state: Iterable[StoredState]) -> List[str]:
    logger.info("preparing stored_state...")
    if stored_state:
        logger.warning("set_stored_state not implemented yet")
    return []


def exec_in_unit(target: JujuUnitName, model: str, cmds: List[str]):
    logger.info("Running juju exec...")

    _model = f" -m {model}" if model else ""
    for cmd in cmds:
        print(cmd[:12])
        j_exec_cmd = f"juju exec -u {target}{_model} -- {cmd}"
        try:
            run(shlex.split(j_exec_cmd))
        except CalledProcessError as e:
            raise StateApplyError(
                f"Failed to apply state: process exited with {e.returncode}; "
                f"stdout = {e.stdout}; "
                f"stderr = {e.stderr}.",
            )


def run_commands(cmds: List[str]):
    logger.info("Applying remaining state...")
    for cmd in cmds:
        try:
            run(shlex.split(cmd))
        except CalledProcessError as e:
            # todo: should we log and continue instead?
            raise StateApplyError(
                f"Failed to apply state: process exited with {e.returncode}; "
                f"stdout = {e.stdout}; "
                f"stderr = {e.stderr}.",
            )


def _gather_juju_exec_cmds(include, state):
    def if_include(key, fn):
        if include is None or key in include:
            return fn()
        return []

    j_exec_cmds: List[str] = []

    j_exec_cmds += if_include(
        "s",
        lambda: set_status(state.unit_status, state.app_status, state.workload_version),
    )
    j_exec_cmds += if_include("p", lambda: set_opened_ports(state.opened_ports))
    j_exec_cmds += if_include("r", lambda: set_relations(state.relations))
    j_exec_cmds += if_include("S", lambda: set_secrets(state.secrets))

    return j_exec_cmds


def _gather_raw_calls(include, state, target):
    def if_include(key, fn):
        if include is None or key in include:
            return fn()
        return []

    cmds: List[str] = []

    # todo: config is a bit special because it's not owned by the unit but by the cloud admin.
    #  should it be included in state-apply?
    if_include("c", lambda: set_config(state.config, target))
    cmds += if_include("k", lambda: set_containers(state.containers))
    cmds += if_include("d", lambda: set_deferred_events(state.deferred))
    cmds += if_include("t", lambda: set_stored_state(state.stored_state))
    return cmds


def _gather_push_file_calls(
    containers: List[Container],
    target: str,
    model: str,
) -> List[str]:
    if not containers:
        return []

    cmds = []
    _model = f" -m {model}" if model else ""

    for container in containers:
        mount: Mount
        for mount in container.mounts.values():
            if not mount.src.exists():
                logger.error(f"mount source directory {mount.src} not found.")
                continue

            mount_loc = Path(mount.location)

            for root, _, files in os.walk(mount.src):
                for file in files:
                    # `file` is the absolute path of the object as it would be on the container filesystem.
                    # we need to relativize it to the tempdir the mount is simulated by.
                    # dest_path = Path(file).relative_to(mount.src)
                    dest_path = (
                        mount_loc.joinpath(*Path(root).relative_to(mount.src).parts)
                        / file
                    )
                    src_path = Path(root) / file
                    cmds.append(f"juju scp{_model} {src_path} {target}:{dest_path}")
    return cmds


def _state_apply(
    target: str,
    state: State,
    model: Optional[str] = None,
    include: str = None,
    data_dir: Path = None,
    push_files: Dict[str, List[Path]] = None,
    dry_run: bool = False,
):
    """see state_apply's docstring"""
    logger.info("Starting state-apply...")

    try:
        target = JujuUnitName(target)
    except InvalidTargetUnitName:
        logger.critical(
            f"invalid target: {target!r} is not a valid unit name. Should be formatted like so:"
            f"`foo/1`, or `database/0`, or `myapp-foo-bar/42`.",
        )
        sys.exit(1)

    logger.info(
        f'Preparing to drop {state} onto {target} in model {model or "<current>"}...',
    )

    j_exec_cmds = _gather_juju_exec_cmds(include, state)
    cmds = _gather_raw_calls(include, state, target) + _gather_push_file_calls(
        state.containers,
        target,
        model,
    )

    if dry_run:
        print("would do:")
        for cmd in j_exec_cmds:
            print(
                f'\t juju exec -u {target}{model or "<the current model>"} -- "{cmd}"',
            )
        for cmd in cmds:
            print(f"\t {cmd}")
        return

    # we gather juju-exec commands to run them all at once in the unit.
    exec_in_unit(target, model, j_exec_cmds)
    # non-juju-exec commands are ran one by one, individually
    run_commands(cmds)

    logger.info("Done!")


def state_apply(
    target: str = typer.Argument(..., help="Target unit."),
    state: Path = typer.Argument(
        ...,
        help="Source State to apply. Json file containing a State data structure; "
        "the same you would obtain by running snapshot.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "-m",
        "--model",
        help="Which model to look at.",
    ),
    include: str = typer.Option(
        "scrkSdt",
        "--include",
        "-i",
        help="What parts of the state to apply. Defaults to: all of them. "
        "``r``: relation, ``c``: config, ``k``: containers, "
        "``s``: status, ``S``: secrets(!), "
        "``d``: deferred events, ``t``: stored state.",
    ),
    push_files: Path = typer.Option(
        None,
        "--push-files",
        help="Path to a local file containing a json spec of files to be fetched from the unit. "
        "For k8s units, it's supposed to be a {container_name: {Path: Path}} mapping listing "
        "the files that need to be pushed to the each container and their destinations.",
    ),
    # TODO: generalize "push_files" to allow passing '.' for the 'charm' container or 'the machine'.
    data_dir: Path = typer.Option(
        SNAPSHOT_DATA_DIR,
        "--data-dir",
        help="Directory in which to any files associated with the state are stored. In the case "
        "of k8s charms, this might mean files obtained through Mounts,",
    ),
    dry_run: bool = typer.Option(False, help="dry-run", is_flag=True),
):
    """Apply a State to a remote target unit."""
    push_files_ = json.loads(push_files.read_text()) if push_files else None
    state_json = json.loads(state.read_text())

    state_: State = dict_to_state(state_json)

    return _state_apply(
        target=target,
        state=state_,
        model=model,
        include=include,
        data_dir=data_dir,
        push_files=push_files_,
        dry_run=dry_run,
    )


# for the benefit of scripted usage
_state_apply.__doc__ = state_apply.__doc__

if __name__ == "__main__":
    from scenario import State

    _state_apply("zookeeper/0", model="foo", state=State())
