#!/usr/bin/env python3
import os

import sys

import typer
from qtpy.QtWidgets import QApplication

from jhack.blackpearl.blackpearl.logger import bp_logger


from jhack.blackpearl.blackpearl.controller.controller import BPController
from jhack.blackpearl.blackpearl.model.model import BPModel
from jhack.blackpearl.blackpearl.view.view import BPView

logger = bp_logger.getChild(__file__)


class Blackpearl:
    def __init__(self):
        self.view = BPView()
        self.model = BPModel(models=["svcgraph"])
        self.controller = BPController(view=self.view, model=self.model)


def show_main_window():
    app = QApplication([])
    app.setStyle("Fusion")

    blackpearl = Blackpearl()
    app.blackpearl = blackpearl

    view = blackpearl.view
    if view.SHOW_MAXIMIZED:
        view.showMaximized()
    else:
        view.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    show_main_window()

    def _display():
        """Launch the Blackpearl."""
        show_main_window()

    def run():
        _display()

    def cli():
        app = typer.Typer(
            name="blackpearl",
            help="Defeat the kraken. "
            "For docs, issues and feature requests, visit "
            "the github repo --> https://github.com/canonical/jhack",
            no_args_is_help=True,
            rich_markup_mode="markdown",
        )
        app.command(name="foo", hidden=True)(
            lambda: None
        )  # prevent subcommand from taking over
        app.command(name="run", no_args_is_help=True)(run)

    cli()
