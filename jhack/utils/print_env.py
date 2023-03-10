import csv
import subprocess
import textwrap

NO_VERSION = "Not Installed."


def get_output(command: str):
    p = subprocess.run(command.split(), capture_output=True, text=True)
    return p.stdout.strip() if p.returncode != 127 else None


def get_os_release():
    with open("/etc/os-release") as f:
        return dict(csv.reader(f, delimiter="="))


def print_env():
    """Print the details of the juju environment for use in bug reports."""
    juju_version = get_output("juju --version") or NO_VERSION
    mk8s_version = get_output("microk8s version") or NO_VERSION
    lxd_version = get_output("lxd --version") or NO_VERSION
    os_version = get_os_release()["PRETTY_NAME"]
    kernel_info = get_output("uname -srp")

    print(
        textwrap.dedent(
            f"""\
            juju:
                {juju_version}
            microk8s:
                {mk8s_version}
            lxd:
                {lxd_version}
            os-info:
                {os_version}
                {kernel_info}"""
        )
    )
