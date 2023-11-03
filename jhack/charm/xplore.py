import getpass
import shlex
import subprocess
from pathlib import Path
from random import random
from tempfile import TemporaryDirectory
from typing import Optional, Union

import typer

from jhack.helpers import JPopen, get_substrate, check_command_available, show_unit
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("mk8s_fs_mount")


def _find_local_mk8s_mount(
    unit_name: str,
    model_name: Optional[str],
    container_name: Optional[str] = None,
    remote_dir: Optional[str] = None,
    *,
    pwd: str,
) -> Path:
    model = f" -m {model_name}" if model_name else ""
    random_fname = "." + "".join(str(random())) + ".jhack_find_sentinel"
    container_name = container_name or "charm"
    if remote_dir is None:
        remote_dir = "/var/lib/juju/" if container_name == "charm" else "/"

    touch = f"juju ssh --container {container_name} {unit_name}{model} touch {remote_dir}{random_fname}"

    print(f"touching {remote_dir}{random_fname} in {unit_name} : {container_name}")
    proc = JPopen(shlex.split(touch))

    proc.wait()
    if err := proc.stderr.read():
        raise RuntimeError(f"failed dropping sentinel file ({err})")

    # might be something like
    # /var/snap/microk8s/common/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/24918/fs/mysecretfile2.2
    # or even:
    # /var/snap/microk8s/common/default-storage/graf-test-trfk-edge-configurations-d6c24946-trfk-edge-0-pvc-...
    # if it's a workload container, or
    # somewhere hidden in /var/snap/microk8s/common/var/lib/kubelet/pods if it's the charm container
    # so we start our search at /var/snap/microk8s/common/ common denominator
    search_root = "/var/snap/microk8s/common/"

    # sudo requires the flag '-S' in order to take input from stdin
    find = f"sudo -S find {search_root} -name {random_fname}"

    # print(find)

    proc = subprocess.run(
        find,
        input=pwd,
        shell=True,
        stdout=subprocess.PIPE,
        encoding="ascii",
    )

    local_root = Path(proc.stdout).parent

    # clean up that weird file
    cleanup = f"juju ssh --container {container_name} {unit_name}{model} rm {remote_dir}{random_fname}"
    JPopen(shlex.split(cleanup)).wait()
    return local_root


def _open_with_file_browser(root: Union[str, Path], *, pwd: Optional[str]):
    if pwd:
        print(f"attempting to open {root} as root in your local file browser...")
        cmd = f"sudo -S xdg-open {root}"
    else:
        print(f"attempting to open {root} in your local file browser...")
        cmd = f"xdg-open {root}"

    subprocess.run(
        cmd,
        input=pwd,
        shell=True,
        stdout=subprocess.PIPE,
        encoding="ascii",
    )


def _xplore_machine(
    unit_name: str,
    model_name: Optional[str],
    remote_dir: Optional[str] = None,
    user: Optional[str] = None,
):
    if not check_command_available("sshfs"):
        exit(f"sshfs not installed; please install it and try again.")

    td = TemporaryDirectory()
    user = user or "ubuntu"
    remote_dir = remote_dir or "/"
    machine_ip = show_unit(unit_name, model_name)["public-address"]
    JPopen(shlex.split(f"sshfs {user}@{machine_ip}:{remote_dir} {td.name}"))

    print(f"{user}@{machine_ip}:{remote_dir} mounted on {td.name}")
    _open_with_file_browser(td.name, pwd=None)


def _xplore_k8s(
    unit_name: str,
    model_name: Optional[str],
    container_name: Optional[str] = None,
    remote_dir: Optional[str] = None,
):
    pwd = getpass.getpass("Please enter your password: ")
    local_root = _find_local_mk8s_mount(
        unit_name, model_name, container_name, remote_dir, pwd=pwd
    )
    logger.info(f"found local root: {local_root}")

    _open_with_file_browser(local_root, pwd=pwd)


def _xplore(
    unit_name: str,
    model_name: Optional[str],
    container_name: Optional[str] = None,
    remote_dir: Optional[str] = None,
):
    if get_substrate(model_name) == "k8s":
        return _xplore_k8s(unit_name, model_name, container_name, remote_dir)
    else:
        if container_name is not None:
            logger.warning("container_name option is meaningless in machine models.")
        return _xplore_machine(unit_name, model_name, remote_dir)


# other approach to consider:
# install https://matt.ucc.asn.au/dropbear/dropbear.html (dropbear ssh) into the target
# container and use it to fork out a ssh server, then connect over sshfs.


def xplore(
    unit_name: str = typer.Argument(..., help="The target unit."),
    model: str = typer.Option(
        None,
        "-m",
        "--model",
        help="Model the target unit is in. Defaults to the current model.",
    ),
    container_name: str = typer.Option(
        None,
        "-c",
        "--container-name",
        help="Container name to target. Defaults to ``charm``. Only meaningful on k8s models.",
    ),
    container_dir: str = typer.Option(
        None, "--container-dir", help="The directory in the container to open."
    ),
):
    """Open a juju-owned charm or workload container as if it were a locally mounted filesystem.

    NB Currently only works on local (as in localhost) development kubernetes deployments,
    and only if it has hostpath storage enabled, or on local machine models.

    NB Requires your admin password in order to do some (hopefully harmless) hackery that has been described as:
    - horrific
    - disgusting
    - ungodly
    - cursed
    - charming

    NB if a directory appears empty, it might be that it's mounted to some place we can't reach it easily.
    Use container_dir to open that directory DIRECTLY, and you should be able to xplore it.
    """
    return _xplore(unit_name, model, container_name, container_dir)
