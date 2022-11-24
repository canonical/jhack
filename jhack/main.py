#!/bin/python3
import logging
import os.path
import sys
from pathlib import Path

import typer

# this will make jhack find its modules if you call it directly (i.e. no symlinks)
# aliases are OK

sys.path.append(str(Path(os.path.realpath(__file__)).parent.parent))
try:
    import jhack
except ModuleNotFoundError:
    raise RuntimeError(f"cannot find jhack modules; " f"check your PATH={sys.path}.")

from jhack.charm import functional
from jhack.charm.init import init
from jhack.charm.provision import provision
from jhack.charm.record import record
from jhack.charm.repack import refresh
from jhack.charm.sync import sync as sync_packed_charm
from jhack.charm.update import update
from jhack.jinx.cleanup import cleanup as jinx_cleanup
from jhack.jinx.init import init_jinx as jinx_init
from jhack.jinx.install import install as jinx_install
from jhack.jinx.pack import pack as jinx_pack
from jhack.logger import LOGLEVEL, logger
from jhack.model.clear import sync_clear_model
from jhack.model.remove import rmodel
from jhack.utils import integrate
from jhack.utils.event_recorder.client import (
    dump_db,
    emit,
    install,
    list_events,
    purge_db,
)
from jhack.utils.ffwd import fast_forward
from jhack.utils.nuke import nuke
from jhack.utils.show_relation import sync_show_relation
from jhack.utils.show_stored import show_stored
from jhack.utils.simulate_event import simulate_event
from jhack.utils.sync import sync as sync_deployed_charm
from jhack.utils.tail_charms import tail_events
from jhack.utils.unbork_juju import unbork_juju
from jhack.utils.unleash import vanity


def main():
    model = typer.Typer(name="model", help="Juju model utilities.")
    model.command(name="clear")(sync_clear_model)
    model.command(name="rm")(rmodel)

    utils = typer.Typer(name="utils", help="Charming utilities.")
    utils.command(name="sync", no_args_is_help=True)(sync_deployed_charm)
    utils.command(name="show-relation", no_args_is_help=True)(sync_show_relation)
    utils.command(name="show-stored", no_args_is_help=True)(show_stored)
    utils.command(name="tail")(tail_events)
    utils.command(name="nuke")(nuke)
    utils.command(name="record", no_args_is_help=True)(record)
    utils.command(name="ffwd")(fast_forward)
    utils.command(name="unbork-juju")(unbork_juju)
    utils.command(name="fire", no_args_is_help=True)(simulate_event)
    utils.command(name="pull-cmr", no_args_is_help=True)(integrate.cmr)

    jinx = typer.Typer(
        name="jinx",
        help="Jinx commands. See https://github.com/PietroPasotti/jinx for more.",
    )
    jinx.command(name="install")(jinx_install)
    jinx.command(name="init")(jinx_init)
    jinx.command(name="pack")(jinx_pack)
    jinx.command(name="cleanup")(jinx_cleanup)

    charm = typer.Typer(name="charm", help="Charmcrafting utilities.")
    charm.command(name="update", no_args_is_help=True)(update)
    charm.command(name="refresh", no_args_is_help=True)(refresh)
    charm.command(name="init", no_args_is_help=True)(init)
    charm.command(name="func", no_args_is_help=True)(functional.run)
    charm.command(name="sync", no_args_is_help=True)(sync_packed_charm)
    charm.command(name="provision")(provision)

    replay = typer.Typer(name="replay", help="Commands to replay events.")
    replay.command(name="install", no_args_is_help=True)(install)
    replay.command(name="purge", no_args_is_help=True)(purge_db)
    replay.command(name="list", no_args_is_help=True)(list_events)
    replay.command(name="dump", no_args_is_help=True)(dump_db)
    replay.command(name="emit", no_args_is_help=True)(emit)

    integration_matrix = typer.Typer(
        name="imatrix", help="Commands to view and manage the integration matrix."
    )
    integration_matrix.command(name="view")(integrate.show)
    integration_matrix.command(name="fill")(integrate.link)
    integration_matrix.command(name="clear")(integrate.clear)

    app = typer.Typer(
        name="jhack",
        help="Hacky, wacky, but ultimately charming.",
        no_args_is_help=True,
    )
    app.command(name="sync", no_args_is_help=True)(sync_deployed_charm)
    app.command(name="show-relation", no_args_is_help=True)(sync_show_relation)
    app.command(name="show-stored", no_args_is_help=True)(show_stored)
    app.command(name="tail")(tail_events)
    app.command(name="nuke")(nuke)
    app.command(name="fire", no_args_is_help=True)(simulate_event)
    app.command(name="ffwd")(fast_forward)
    app.command(name="unbork-juju")(unbork_juju)
    app.command(name="pull-cmr", no_args_is_help=True)(integrate.cmr)
    app.command(name="jhack", hidden=True)(vanity)

    app.add_typer(model, no_args_is_help=True)
    app.add_typer(jinx, no_args_is_help=True)
    app.add_typer(charm, no_args_is_help=True)
    app.add_typer(utils, no_args_is_help=True)
    app.add_typer(replay, no_args_is_help=True)
    app.add_typer(integration_matrix, no_args_is_help=True)

    @app.callback()
    def set_verbose(log: str = None, path: Path = None):
        if log:
            typer.echo(f"::= Verbose mode ({log}). =::")
            logger.setLevel(log)
            logging.basicConfig(stream=sys.stdout)
            if path:
                hdlr = logging.FileHandler(path)
                logger.addHandler(hdlr)

    if LOGLEVEL != "WARNING":
        typer.echo(f"::= Verbose mode ({LOGLEVEL}). =::")

    from jhack.config import configure

    configure()
    app()


if __name__ == "__main__":
    main()
