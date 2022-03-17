#!/bin/python3

import typer

from logger import logger
from charm.update import update_charm
from model.clear import sync_clear_model
from model.remove import rmodel
from utils.sync import sync
from utils.unfuck_juju import unfuck_juju


if __name__ == '__main__':
    model = typer.Typer(name='model')
    model.command(name='clear')(sync_clear_model)
    model.command(name='rm')(rmodel)

    utils = typer.Typer(name='utils')
    utils.command(name='sync')(sync)
    utils.command(name='unfuck-juju')(unfuck_juju)

    charm = typer.Typer(name='charm')
    charm.command(name='update')(update_charm)

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
