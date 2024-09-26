#!/bin/python3
import logging
import os
import sys
from importlib.util import find_spec
from pathlib import Path

import typer


# this will make jhack find its modules if you call it directly (i.e. no symlinks)
# aliases are OK
sys.path.append(str(Path(os.path.realpath(__file__)).parent.parent))

try:
    find_spec("jhack")
except ModuleNotFoundError:
    raise RuntimeError(f"cannot find jhack modules; " f"check your PATH={sys.path}.")


def main():
    from jhack.config import configure

    configure()

    def devmode_only(command):
        command.__doc__ = command.__doc__ + "\n\n **--this command is DEVMODE ONLY--**"
        return command

    from jhack.chaos.flicker import flicker
    from jhack.chaos.mancioppi import mancioppi
    from jhack.charm import functional
    from jhack.charm.init import init
    from jhack.charm.lobotomy import lobotomy
    from jhack.charm.provision import provision
    from jhack.charm.record import record
    from jhack.charm.sync import sync as sync_packed_charm
    from jhack.charm.update import update
    from jhack.charm.vinfo import vinfo
    from jhack.conf.conf import (
        print_current_config,
        print_defaults,
        print_destructive,
        print_yolo,
    )
    from jhack.logger import LOGLEVEL, logger
    from jhack.scenario.snapshot import snapshot
    from jhack.scenario.state_apply import state_apply
    from jhack.utils import integrate
    from jhack.utils.charm_rpc import charm_eval, charm_script
    from jhack.utils.event_recorder.client import (
        dump_db,
        emit,
        install,
        list_events,
        purge_db,
    )
    from jhack.utils.ffwd import fast_forward
    from jhack.utils.just_deploy_this import just_deploy_this
    from jhack.utils.list_endpoints import list_endpoints
    from jhack.utils.tail_logs import tail_logs
    from jhack.utils.nuke import nuke
    from jhack.utils.print_env import jhack_version, print_env
    from jhack.utils.propaganda import leader_set
    from jhack.utils.show_relation import sync_show_relation
    from jhack.utils.show_stored import show_stored
    from jhack.utils.simulate_event import simulate_event
    from jhack.utils.sitrep import sitrep
    from jhack.utils.sync import sync as sync_deployed_charm
    from jhack.utils.tail_charms import tail_events
    from jhack.utils.unbork_juju import unbork_juju
    from jhack.utils.unleash import vanity
    from jhack.utils.remote_debug import remote_debug

    if "--" in sys.argv:
        sep = sys.argv.index("--")
        typer.Typer._extra_args = sys.argv[sep + 1 :]
        sys.argv = sys.argv[:sep]

    utils = typer.Typer(name="utils", help="Charming utilities.")
    utils.command(name="show-relation", no_args_is_help=True)(sync_show_relation)
    utils.command(name="show-stored", no_args_is_help=True)(show_stored)
    utils.command(name="tail")(tail_events)
    utils.command(name="record", no_args_is_help=True)(record)
    utils.command(name="ffwd")(fast_forward)
    utils.command(name="print-env")(print_env)
    utils.command(name="remote-debug", no_args_is_help=True)(remote_debug)

    utils.command(name="unbork-juju")(devmode_only(unbork_juju))
    utils.command(name="fire", no_args_is_help=True)(devmode_only(simulate_event))
    utils.command(name="pull-cmr", no_args_is_help=True)(integrate.cmr)
    utils.command(name="elect", no_args_is_help=True)(devmode_only(leader_set))

    charm = typer.Typer(name="charm", help="Charmcrafting utilities.")
    charm.command(name="update", no_args_is_help=True)(update)
    charm.command(name="init", no_args_is_help=True)(init)
    charm.command(name="func", no_args_is_help=True)(functional.run)
    charm.command(name="sync-packed", no_args_is_help=True)(sync_packed_charm)
    charm.command(name="lobotomy", no_args_is_help=True)(devmode_only(lobotomy))
    charm.command(name="provision")(devmode_only(provision))
    charm.command(name="sitrep", no_args_is_help=True)(sitrep)

    replay = typer.Typer(name="replay", help="Commands to replay events.")
    replay.command(name="install", no_args_is_help=True)(devmode_only(install))
    replay.command(name="purge", no_args_is_help=True)(devmode_only(purge_db))
    replay.command(name="list", no_args_is_help=True)(list_events)
    replay.command(name="dump", no_args_is_help=True)(dump_db)
    replay.command(name="emit", no_args_is_help=True)(devmode_only(emit))

    integration_matrix = typer.Typer(
        name="imatrix", help="Commands to view and manage the integration matrix."
    )
    integration_matrix.command(name="view")(integrate.show)
    integration_matrix.command(name="fill")(devmode_only(integrate.link))
    integration_matrix.command(name="clear")(devmode_only(integrate.clear))

    app = typer.Typer(
        name="jhack",
        help="""
        Hacky, wacky, but ultimately charming.
        
        Home is https://github.com/canonical/jhack.\n
        Head there for feature requests, bugs, etc...""",
        no_args_is_help=True,
        rich_markup_mode="markdown",
    )
    app.command(name="version")(jhack_version)
    app.command(name="show-relation", no_args_is_help=True)(sync_show_relation)
    app.command(name="show-stored", no_args_is_help=True)(show_stored)
    app.command(name="tail")(tail_events)
    app.command(name="ffwd")(fast_forward)
    app.command(name="unleash", hidden=True)(vanity)
    app.command(name="jenv")(print_env)
    app.command(name="list-endpoints")(list_endpoints)

    # DEVMODE ONLY COMMANDS
    def _test_devmode():
        """Dummy devmode command to verify the destructive profile."""
        from jhack.conf.conf import check_destructive_commands_allowed

        check_destructive_commands_allowed("test-devmode")
        print("BOOM!")

    app.command(name="test-devmode")(devmode_only(_test_devmode))
    app.command(name="sync")(devmode_only(sync_deployed_charm))
    app.command(name="nuke")(devmode_only(nuke))
    app.command(name="deploy")(devmode_only(just_deploy_this))
    app.command(name="fire", no_args_is_help=True)(devmode_only(simulate_event))
    app.command(name="pull-cmr", no_args_is_help=True)(integrate.cmr)
    app.command(name="charm-info", no_args_is_help=True)(vinfo)
    app.command(name="vinfo", deprecated=True, no_args_is_help=True)(vinfo)
    app.command(name="eval", no_args_is_help=True)(devmode_only(charm_eval))
    app.command(name="debug-log", no_args_is_help=True)(tail_logs)
    app.command(name="script", no_args_is_help=True)(devmode_only(charm_script))

    conf = typer.Typer(
        # TODO md formatting is currently quite bork cfr. https://github.com/tiangolo/typer/pull/815
        name="conf",
        help="""Jhack configuration.\n\n 
        
        You can run ``jhack conf [default | destructive | yolo]``\n\n
        to view sample configuration profiles. \n\n
        By default, the 'default' profile is used and copied into your ``~/.config/jhack/config.toml``.\n\n\n
        
        Reset to factory settings:\n
         - `jhack conf default > ~/.config/jhack/config.toml`\n\n\n
         
         
        Enable built-in destructive or yolo profiles:\n
         - `jhack conf destructive > ~/.config/jhack/config.toml`\n
         - `jhack conf yolo > ~/.config/jhack/config.toml`\n\n\n
         
         Otherwise, edit your ``~/.config/jhack/config.toml`` manually to suit your needs.
         """,
        no_args_is_help=True,
    )
    conf.command(name="default")(print_defaults)
    conf.command(name="yolo")(print_yolo)
    conf.command(name="destructive")(print_destructive)
    conf.command(name="current")(print_current_config)

    scenario = typer.Typer(
        name="scenario",
        help="""Commands to interact with scenario-powered State.""",
        no_args_is_help=True,
    )
    scenario.command(name="snapshot")(snapshot)
    scenario.command(name="state-apply")(devmode_only(state_apply))

    chaos = typer.Typer(
        name="chaos",
        help="""Commands to spread the chaos.""",
        no_args_is_help=True,
    )
    chaos.command(name="mancioppi")(devmode_only(mancioppi))
    chaos.command(name="flicker")(devmode_only(flicker))

    # register all subcommands
    app.add_typer(conf, no_args_is_help=True)
    app.add_typer(charm, no_args_is_help=True)
    app.add_typer(utils, no_args_is_help=True)
    app.add_typer(replay, no_args_is_help=True)
    app.add_typer(integration_matrix, no_args_is_help=True)
    app.add_typer(scenario, no_args_is_help=True)
    app.add_typer(chaos, no_args_is_help=True)

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

    app(ignore_unknown_options=True)


if __name__ == "__main__":
    main()
