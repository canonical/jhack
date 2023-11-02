import shlex
import subprocess
from pathlib import Path
from random import random
from subprocess import PIPE
from typing import Optional, Tuple
from jhack.logger import logger as jhack_logger
from jhack.helpers import JPopen
import getpass

logger = jhack_logger.getChild("mk8s_fs_mount")


def _find_local_mk8s_mount(
    unit_name: str,
    model_name: Optional[str],
    container_name: Optional[str] = "charm",
    remote_dir="/",
    *,
    pwd: str,
) -> Path:
    model = f" -m {model_name}" if model_name else ""
    random_fname = "." + "".join(str(random())) + ".jhack_find_sentinel"

    touch = f"juju ssh --container {container_name} {unit_name}{model} touch {remote_dir}{random_fname}"
    # print(touch)

    logger.debug(f"touching {random_fname} in {unit_name} : {container_name}")
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

    return Path(proc.stdout).parent


def _open_with_sudo_file_browser(root: Path, *, pwd: str):
    cmd = f"sudo -S xdg-open {root}"
    print(f"attempting to open {root} in your local file browser...")

    subprocess.run(
        cmd,
        input=pwd,
        shell=True,
        stdout=subprocess.PIPE,
        encoding="ascii",
    )


def _open_local_mk8s_mount(
    unit_name: str,
    model_name: Optional[str],
    container_name: Optional[str] = "charm",
    remote_dir: str = "/",
):
    pwd = getpass.getpass("Please enter your password: ")
    local_root = _find_local_mk8s_mount(
        unit_name, model_name, container_name, remote_dir, pwd=pwd
    )
    logger.info(f"found local root: {local_root}")

    _open_with_sudo_file_browser(local_root, pwd=pwd)


# other approach to consider:
# install https://matt.ucc.asn.au/dropbear/dropbear.html (dropbear ssh) into the target
# container and use it to fork out a ssh server, then connect over sshfs.


if __name__ == "__main__":
    print(_open_local_mk8s_mount("trfk-edge/0", None, "charm"))
    # print(
    #     _open_local_mk8s_mount(
    #         "trfk-edge/0", None, "traefik", remote_dir="/opt/traefik/juju/"
    #     )
    # )
