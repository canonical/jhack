from typing import Optional, List

import typer
import yaml

from jhack.helpers import fetch_file
from jhack.logger import logger as jhack_logger
from jhack.scenario.errors import InvalidTargetUnitName
from jhack.scenario.snapshot import RemotePebbleClient
from jhack.scenario.utils import JujuUnitName

logger = jhack_logger.getChild(__name__)


def get_container_names(target, model):
    try:
        metadata = fetch_file(target, "metadata.yaml", model=model)
    except RuntimeError:
        exit(
            f"Failed to fetch metadata.yaml from {target} in model={model or '<current model>'}"
        )
    raw_meta = yaml.safe_load(metadata)
    containers = raw_meta.get("containers")
    if not containers:
        exit(f"target {target} has no containers defined in metadata.yaml")
    return list(containers.keys())


def _pebble(
    target: str,
    command: List[str],
    container_name: Optional[str] = None,
    model: Optional[str] = None,
    dry_run: bool = False,
):
    try:
        target = JujuUnitName(target)
    except InvalidTargetUnitName:
        exit(f"invalid target: expected `app_name/unit_id`, got: {target!r}")

    if not container_name:
        for container in get_container_names(target, model):
            print(f"result for container {container!r}:")
            _pebble(target, command, container, model, dry_run)
        return

    client = RemotePebbleClient(
        container_name, target=target, model=model, dry_run=dry_run
    )
    out = client.run(command)
    if not out.strip():
        _command = " ".join(["pebble"] + command)
        out = f"[no output: {_command!r}]"
    print(out)


def pebble(
    target: str = typer.Argument(..., help="Target unit."),
    command: List[str] = typer.Argument(
        ..., help="Pebble command to execute on the container."
    ),
    container_name: str = typer.Option(
        None,
        "-c",
        "--container",
        help="Container name to target. "
        "Will execute for each container in turn if none is specified.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "-m",
        "--model",
        help="Which model to look at.",
    ),
    dry_run: bool = typer.Option(
        False,
        is_flag=True,
        help="Don't actually do anything, just print what would have happened.",
    ),
):
    """Proxy a pebble command to a remote unit.
    Example usage:
    -  $ jhack pebble -c nginx tempo/0 plan
    -  $ jhack pebble -c pg pg/0 status pgbouncer
    -  $ jhack pebble -c tempo tempo-worker/0 exec "which tempo"
    -  $ jhack pebble -c parca parca/0 exec "ls -la /"

    Note that ATM jhack can't distinguish arguments passed to this command vs arguments passed to pebble,
    so remember to quote all 'exec' params.
    """
    return _pebble(
        target=target,
        command=command,
        container_name=container_name,
        model=model,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    _pebble(
        "parca/0",
        ["exec", "ps"],
        container_name="parca",
    )
