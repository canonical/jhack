import shlex
import sys
from pathlib import Path
import subprocess

import click
import typer
import yaml
from click import Choice

suffixes = ["-k8s", "-operator"]


def _just_deploy_this(path: Path, name: str = None, dry_run: bool = False):
    if path.name.endswith(".charm"):
        charms = [path]
    else:
        charms = list(path.glob("*.charm"))

    if not charms:
        print(f"No charm found in {path}. Pack one first.")

    if len(charms) > 1:
        print(f"Multiple charms found in {path}.")
        for i, c in enumerate(charms):
            print(f"{i}: {c}")

        charm = typer.prompt(
            "pick one",
            default=charms[0],
            type=Choice(list(map(str, range(len(charms))))),
        )
    else:
        charm = charms[0]

    meta = path / "metadata.yaml"
    if not meta.exists():
        meta = path / "charmcraft.yaml"
    if not meta.exists():
        exit(f"No metadata.yaml/charmcraft.yaml found at {path}; unable to comply.")

    raw_meta = yaml.safe_load(meta.read_text())
    if not name:
        raw_name = raw_meta.get("name")
        if not raw_name:
            exit("invalid metadata file: no 'name' field found.")

        def trim(_name):
            for suffix in suffixes:
                if _name.endswith(suffix):
                    return trim(_name[: -len(suffix)])
            return _name

        name = trim(raw_name)

    raw_resources = raw_meta.get("resources", {})
    resources_args = []
    for resource_name, resource_meta in raw_resources.items():

        upstream_source = resource_meta.get("upstream-source")
        if not upstream_source:
            print(f"No upstream-source found for {resource_name}.")
            charm = typer.prompt("Enter resource name", confirmation_prompt=True)

        resources_args.append(f"--resource {resource_name}={upstream_source}")

    try:
        extra_args = typer.Typer._extra_args
    except AttributeError:
        extra_args = []

    extra_args = " " + " ".join(extra_args) if extra_args else ""
    cmd = (
        f"juju deploy {charm.absolute()} {' '.join(resources_args)} {name}{extra_args}"
    )

    if dry_run:
        print(f"would run:\n\t{cmd}")
        return

    print(f"deploying {path} as {name}")
    subprocess.run(*shlex.split(cmd))


def just_deploy_this(
    ctx: typer.Context,
    path: Path = typer.Argument(
        Path(),
        help="Path to a charm repository root (or a `.charm` file).",
    ),
    name: str = typer.Argument(
        None,
        help="Application name you want to deploy the charm at. Will default to a "
        "gently trimmed version of the charm name, omitting -k8s or -operator prefixes.",
    ),
    dry_run: bool = typer.Option(
        None, help="Do nothing, print out what would have happened.", is_flag=True
    ),
):
    """Just Deploy This. (Pretty please).

    Reads out the `upstream-source` of any resources attached to a charm and deploys it with those.
    Any additional arguments (after a ``--``) will be passed through to `juju deploy`.

    Examples:\n
    - ``$ jhack deploy ./``\n
    - ``$ jhack deploy ./some/path/foo_k8s.charm bar``\n
    - ``$ jhack deploy ./some/path/foo.charm bar -- --to-machine 42``
    """
    _just_deploy_this(path, name, dry_run=dry_run)


if __name__ == "__main__":
    _just_deploy_this(Path("/home/pietro/canonical/tempo-k8s"))
