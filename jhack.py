#!/bin/python3

import typer

from charm import functional
from charm.init import init
from logger import logger
from charm.update import update
from charm.repack import repack
from charm.sync import sync as sync_packed_charm
from model.clear import sync_clear_model
from model.remove import rmodel
from utils.ffwd import fast_forward
from utils.sync import sync as sync_deployed_charm
from utils.show_relation import sync_show_relation
from utils.tail_charms import tail_events
from utils.unbork_juju import unbork_juju
from jinx.install import install as jinx_install
from jinx.init import init_jinx as jinx_init
from jinx.pack import pack as jinx_pack
from jinx.cleanup import cleanup as jinx_cleanup


if __name__ == '__main__':
    model = typer.Typer(name='model', help='Juju model utilities.')
    model.command(name='clear')(sync_clear_model)
    model.command(name='rm')(rmodel)

    utils = typer.Typer(name='utils', help='Charming utilities.')
    utils.command(name='sync')(sync_deployed_charm)
    utils.command(name='show-relation')(sync_show_relation)
    utils.command(name='tail')(tail_events)
    utils.command(name='ffwd')(fast_forward)
    utils.command(name='unbork-juju')(unbork_juju)

    jinx = typer.Typer(name='jinx',
                       help="Jinx commands. See https://github.com/PietroPasotti/jinx for more.")
    jinx.command(name='install')(jinx_install)
    jinx.command(name='init')(jinx_init)
    jinx.command(name='pack')(jinx_pack)
    jinx.command(name='cleanup')(jinx_cleanup)

    charm = typer.Typer(name='charm', help='Charmcrafting utilities.')
    charm.command(name='update')(update)
    charm.command(name='repack')(repack)
    charm.command(name='init')(init)
    charm.command(name='func')(functional.run)
    charm.command(name='sync')(sync_packed_charm)

    app = typer.Typer(name='jhack', help='Hacky, wacky, but ultimately charming.')
    app.command(name='sync')(sync_deployed_charm)
    app.command(name='show-relation')(sync_show_relation)
    app.command(name='tail')(tail_events)
    app.command(name='ffwd')(fast_forward)
    app.command(name='unbork-juju')(unbork_juju)

    app.add_typer(model)
    app.add_typer(jinx)
    app.add_typer(charm)
    app.add_typer(utils)

    @app.callback()
    def main(verbose: bool = False):
        if verbose:
            typer.echo("::= Verbose mode. =::")
            logger.setLevel('INFO')

    app()
