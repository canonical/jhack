import subprocess
import textwrap

NO_VERSION = "Not Installed."


def exists(command: str):
    p = subprocess.run(["which", command], capture_output=True)
    return True if p.returncode == 0 else False


def get_output(command: str):
    p = subprocess.run(command.split(), capture_output=True, text=True)
    return p.stdout.strip()


def print_env():
    """Print the details of the juju environment for use in bug reports."""
    if exists("juju"):
        juju_version = get_output("juju --version")
    else:
        juju_version = NO_VERSION
    if exists("microk8s"):
        mk8s_version = get_output("microk8s version")
    else:
        mk8s_version = NO_VERSION
    if exists("lxd"):
        lxd_version = get_output("lxd --version")
    else:
        lxd_version = NO_VERSION

    print(
        textwrap.dedent(
            f"""\
            juju:
                {juju_version}
            microk8s:
                {mk8s_version}
            lxd:
                {lxd_version}"""
        )
    )
