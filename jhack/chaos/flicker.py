import itertools
import random
import shlex
from subprocess import check_output, CalledProcessError
from time import sleep
from typing import List

from jhack.helpers import juju_status
from jhack.logger import logger as jhack_logger
from jhack.utils.integrate import IntegrationMatrix

logger = jhack_logger.getChild("gather_endpoints")

import typer


def _flicker(
    model: str = None,
    include: List[str] = None,
    exclude: List[str] = None,
    wait_user: bool = False,
    dry_run: bool = False,
    reverse: bool = False,
):
    include = set(include) or set()
    exclude = set(exclude) or set()
    if include and exclude:
        exit("only pass one of --include and --exclude.")

    status = juju_status(json=True, model=model)
    _all = set(status["applications"])

    targets = list(_all.intersection(include) or _all.difference(exclude))
    print("Gathering imatrix...")
    imatrix = IntegrationMatrix(model=model)
    integrations = []
    for prov, req in itertools.product(targets, targets):
        for i in imatrix.get_integrations(prov, req):
            integrations.append((prov, req, i))

    print(f"Will flicker: {list(targets)}")
    print(f"Integrations:")
    for _prov, _req, _integration in integrations:
        _integration_repr = f"{_prov}:{_integration.provider_endpoint} {_req}"
        print(f"\t{_integration_repr}")

    def disintegrate(integrations):
        done = []
        for prov, req, integration in integrations:
            cmd = f"juju remove-relation {prov}:{integration.provider_endpoint} {req}"
            if dry_run:
                print(f"\t{cmd}")
            else:
                integration_repr = f"{prov}:{integration.provider_endpoint} --[{integration.interface}]--> {req}"
                print(f"\tDisintegrating {integration_repr}")
                try:
                    check_output(shlex.split(cmd))
                except CalledProcessError:
                    logger.error(
                        f"error disintegrating {integration_repr} ({cmd}). Skipping..."
                    )
                    logger.debug(
                        f"error disintegrating {integration_repr}", exc_info=True
                    )
                    continue

            done.append((prov, req, integration))

        return done

    def integrate(integrations):
        done = []
        for prov, req, integration in integrations:
            cmd = f"juju integrate {prov}:{integration.provider_endpoint} {req}"
            if dry_run:
                print(f"\t{cmd}")
            else:
                integration_repr = f"{prov}:{integration.provider_endpoint} --[{integration.interface}]--> {req}"
                print(f"\tIntegrating {integration_repr}")
                try:
                    check_output(shlex.split(cmd))
                except CalledProcessError:
                    logger.error(
                        f"error integrating {integration_repr} ({cmd}). Skipping..."
                    )
                    logger.debug(f"error integrating {integration_repr}", exc_info=True)
                    continue

            done.append((prov, req, integration))

        return done

    if reverse:
        one, two = integrate, disintegrate
    else:
        one, two = disintegrate, integrate

    random.shuffle(integrations)

    modified = one(integrations)

    if dry_run:
        if wait_user:
            print(f"would wait for user to enter [y]...")
    elif wait_user:
        try:
            typer.confirm("proceed?")
        except typer.Abort:
            print("Aborted by user.")
            exit(0)

    random.shuffle(modified)
    two(modified)


def flicker(
    model: str = typer.Option(None, "--model", "-m", help="The model to flicker."),
    include: List[str] = typer.Option(
        None, "--include", "-i", help="Flicker this app."
    ),
    exclude: List[str] = typer.Option(
        None, "--exclude", "-e", help="Leave this app unflickered."
    ),
    wait_user: bool = typer.Option(
        True, is_flag=True, help="Wait for user input before unflickering."
    ),
    dry_run: bool = typer.Option(
        False,
        is_flag=True,
        help="Don't actually do anything, just print what would have happened.",
    ),
    reverse: bool = typer.Option(
        False, is_flag=True, help="First scale down, then up."
    ),
):
    """Flickers the bugs out of this model.

    Removes all relations and adds them back in a random order.
    """

    return _flicker(
        model=model,
        include=include,
        exclude=exclude,
        wait_user=wait_user,
        dry_run=dry_run,
        reverse=reverse,
    )
