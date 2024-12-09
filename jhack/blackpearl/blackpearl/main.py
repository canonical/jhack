#!/usr/bin/env python3

import sys
from typing import List

import typer
from qtpy.QtWidgets import QApplication

from jhack.blackpearl.blackpearl.controller.controller import BPController
from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.model.testing import TestingBPModel
from jhack.blackpearl.blackpearl.view.view import BPView

logger = bp_logger.getChild(__file__)


class Blackpearl:
    """Main blackpearl class."""

    def __init__(self, models: List[str] | None = None):
        self.view = BPView()
        # self.model = BPModel(models=models)
        self.model = TestingBPModel(models=models)
        self.controller = BPController(view=self.view, model=self.model)


def main_cli(
    model: List[str] = typer.Option(
        None,
        "-m",
        "--model",
        help="Restrict the field-of-view to these models only, for the initial load.",
    ),
):
    """Fire up the BlackPearl GUI.

    Aye aye!
    """
    return show_main_window(models=model)


def show_main_window(*args, **kwargs):
    app = QApplication([])
    app.setStyle("Fusion")

    blackpearl = Blackpearl(*args, **kwargs)
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
