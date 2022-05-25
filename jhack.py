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
from utils.sync import sync as sync_deployed_charm
from utils.show_relation import sync_show_relation
from utils.tail_charms import tail_events
from utils.unbork_juju import unbork_juju


if __name__ == '__main__':
    model = typer.Typer(name='model')
    model.command(name='clear')(sync_clear_model)
    model.command(name='rm')(rmodel)

    utils = typer.Typer(name='utils')
    utils.command(name='sync')(sync_deployed_charm)
    utils.command(name='show-relation')(sync_show_relation)
    utils.command(name='tail')(tail_events)
    utils.command(name='unbork-juju')(unbork_juju)

    charm = typer.Typer(name='charm')
    charm.command(name='update')(update)
    charm.command(name='repack')(repack)
    charm.command(name='init')(init)
    charm.command(name='func')(functional.run)
    charm.command(name='sync')(sync_packed_charm)

    app = typer.Typer(name='jhack')
    app.add_typer(model)
    app.add_typer(charm)
    app.add_typer(utils)

    @app.callback()
    def main(verbose: bool = False):
        if verbose:
            typer.echo("::= Verbose mode. =::")
            logger.setLevel('INFO')

    app()
