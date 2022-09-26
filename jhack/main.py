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
from jhack.utils.event_recorder.client import (
    dump_db,
    emit,
    install,
    list_events,
    purge_db,
)
from jhack.utils.ffwd import fast_forward
from jhack.utils.fire import fire
from jhack.utils.nuke import nuke
from jhack.utils.show_relation import sync_show_relation
from jhack.utils.show_stored import show_stored
from jhack.utils.simulate_event import simulate_event
from jhack.utils.sync import sync as sync_deployed_charm
from jhack.utils.tail_charms import tail_events
from jhack.utils.unbork_juju import unbork_juju


def main():
    model = typer.Typer(name="model", help="Juju model utilities.")
    model.command(name="clear")(sync_clear_model)
    model.command(name="rm")(rmodel)

    utils = typer.Typer(name="utils", help="Charming utilities.")
    utils.command(name="sync")(sync_deployed_charm)
    utils.command(name="show-relation")(sync_show_relation)
    utils.command(name="show-stored")(show_stored)
    utils.command(name="tail")(tail_events)
    utils.command(name="nuke")(nuke)
    utils.command(name="record")(record)
    utils.command(name="ffwd")(fast_forward)
    utils.command(name="unbork-juju")(unbork_juju)
    utils.command(name="fire")(simulate_event)

    jinx = typer.Typer(
        name="jinx",
        help="Jinx commands. See https://github.com/PietroPasotti/jinx for more.",
    )
    jinx.command(name="install")(jinx_install)
    jinx.command(name="init")(jinx_init)
    jinx.command(name="pack")(jinx_pack)
    jinx.command(name="cleanup")(jinx_cleanup)

    charm = typer.Typer(name="charm", help="Charmcrafting utilities.")
    charm.command(name="update")(update)
    charm.command(name="refresh")(refresh)
    charm.command(name="init")(init)
    charm.command(name="func")(functional.run)
    charm.command(name="sync")(sync_packed_charm)
    charm.command(name="provision")(provision)

    replay = typer.Typer(name="replay", help="Commands to replay events.")
    replay.command(name="install")(install)
    replay.command(name="list")(list_events)
    replay.command(name="dump")(dump_db)
    replay.command(name="purge")(purge_db)
    replay.command(name="emit")(emit)

    app = typer.Typer(name="jhack", help="Hacky, wacky, but ultimately charming.")
    app.command(name="sync")(sync_deployed_charm)
    app.command(name="show-relation")(sync_show_relation)
    app.command(name="show-stored")(show_stored)
    app.command(name="tail")(tail_events)
    app.command(name="nuke")(nuke)
    app.command(name="fire")(simulate_event)
    app.command(name="ffwd")(fast_forward)
    app.command(name="unbork-juju")(unbork_juju)
    app.command(name="fire")(fire)

    app.add_typer(model)
    app.add_typer(jinx)
    app.add_typer(charm)
    app.add_typer(utils)
    app.add_typer(replay)

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
