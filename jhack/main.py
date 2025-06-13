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
    raise RuntimeError(f"cannot find jhack modules; check your PATH={sys.path}.")


def main():
    from jhack.config import configure

    configure()

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
        test_devmode,
        doc_devmode_only,
    )
    from jhack.logger import LOGLEVEL, logger
    from jhack.scenario.snapshot import snapshot
    from jhack.scenario.state_apply import state_apply
    from jhack.utils.integrate import (
        cmr as pull_cmr,
        link as imatrix_fill,
        clear as imatrix_clear,
        show as imatrix_view,
    )
    from jhack.utils.charm_rpc import charm_eval, charm_script
    from jhack.utils.event_recorder.client import (
        dump_db,
        emit,
        install,
        list_events,
        purge_db,
    )
    from jhack.utils.ffwd import fast_forward
    from jhack.utils.just_deploy_this import just_deploy_this as deploy
    from jhack.utils.kill import kill
    from jhack.utils.list_endpoints import list_endpoints
    from jhack.utils.nuke import nuke
    from jhack.utils.print_env import print_env
    from jhack.utils.propaganda import leader_set as elect
    from jhack.utils.show_relation import sync_show_relation
    from jhack.utils.show_stored import show_stored
    from jhack.utils.simulate_event import simulate_event as fire
    from jhack.utils.sitrep import sitrep
    from jhack.utils.sync import sync as sync_deployed_charm
    from jhack.utils.tail_charms.cli import tail_events
    from jhack.utils.tail_logs import tail_logs
    from jhack.utils.unbork_juju import unbork_juju
    from jhack.utils.unleash import vanity, vanity_2
    from jhack.utils.pebble import pebble
    from jhack.version import print_jhack_version

    if "--" in sys.argv:
        sep = sys.argv.index("--")
        typer.Typer._extra_args = sys.argv[sep + 1 :]
        sys.argv = sys.argv[:sep]

    # Add to all devmode-only commands a doc line warning the user it's only "safe" but not ``safe`` to use them
    for devmode_only_command in {
        charm_eval,
        charm_script,
        emit,
        flicker,
        install,
        imatrix_fill,
        imatrix_clear,
        deploy,
        kill,
        elect,
        lobotomy,
        mancioppi,
        nuke,
        pebble,
        provision,
        purge_db,
        fire,
        state_apply,
        sync_deployed_charm,
        test_devmode,
        unbork_juju,
    }:
        doc_devmode_only(devmode_only_command)

    utils = typer.Typer(name="utils", help="Charming utilities.")
    utils.command(name="show-relation", no_args_is_help=True)(sync_show_relation)
    utils.command(name="show-stored", no_args_is_help=True)(show_stored)
    utils.command(name="tail")(tail_events)
    utils.command(name="record", no_args_is_help=True)(record)
    utils.command(name="ffwd")(fast_forward)
    utils.command(name="print-env")(print_env)

    utils.command(name="unbork-juju")(unbork_juju)
    utils.command(name="fire", no_args_is_help=True)(fire)
    utils.command(name="pull-cmr", no_args_is_help=True)(pull_cmr)
    utils.command(name="elect", no_args_is_help=True)(elect)
    utils.command(name="pebble", no_args_is_help=True)(pebble)

    charm = typer.Typer(name="charm", help="Charmcrafting utilities.")
    charm.command(name="update")(update)
    charm.command(name="init", no_args_is_help=True)(init)
    charm.command(name="func", no_args_is_help=True)(functional.run)
    charm.command(name="sync-packed", no_args_is_help=True)(sync_packed_charm)
    charm.command(name="lobotomy", no_args_is_help=True)(lobotomy)
    charm.command(name="provision")(provision)
    charm.command(name="sitrep", no_args_is_help=True)(sitrep)

    replay = typer.Typer(name="replay", help="Commands to replay events.")
    replay.command(name="install", no_args_is_help=True)(install)
    replay.command(name="purge", no_args_is_help=True)(purge_db)
    replay.command(name="list", no_args_is_help=True)(list_events)
    replay.command(name="dump", no_args_is_help=True)(dump_db)
    replay.command(name="emit", no_args_is_help=True)(emit)

    integration_matrix = typer.Typer(
        name="imatrix", help="Commands to view and manage the integration matrix."
    )
    integration_matrix.command(name="view")(imatrix_view)
    integration_matrix.command(name="fill")(imatrix_fill)
    integration_matrix.command(name="clear")(imatrix_clear)

    app = typer.Typer(
        name="jhack",
        help="""
        Hacky, wacky, but ultimately charming.
        
        Home is https://github.com/canonical/jhack.\n
        Head there for feature requests, bugs, etc...\n\n
        
        You can run `jhack commands` for an (almost) exhaustive list of all 
        available command groups and subcommands.
        """,
        no_args_is_help=True,
        rich_markup_mode="markdown",
    )
    app.command(name="version")(print_jhack_version)
    app.command(name="show-relation", no_args_is_help=True)(sync_show_relation)
    app.command(name="show-stored", no_args_is_help=True)(show_stored)
    app.command(name="tail")(tail_events)
    app.command(name="ffwd")(fast_forward)
    app.command(name="unleash", hidden=True)(vanity)
    app.command(name="is", hidden=True)(vanity_2)
    app.command(name="jenv")(print_env)
    app.command(name="list-endpoints")(list_endpoints)

    app.command(name="test-devmode")(test_devmode)
    app.command(name="sync")(sync_deployed_charm)
    app.command(name="nuke")(nuke)
    app.command(name="kill")(kill)
    app.command(name="deploy")(deploy)
    app.command(name="fire", no_args_is_help=True)(fire)
    app.command(name="pull-cmr", no_args_is_help=True)(pull_cmr)
    app.command(name="charm-info", no_args_is_help=True)(vinfo)
    app.command(
        name="vinfo",
        deprecated=True,
        no_args_is_help=True,
        help="deprecated in favour of charm-info",
    )(vinfo)
    app.command(name="eval", no_args_is_help=True)(charm_eval)
    app.command(name="debug-log", no_args_is_help=True)(tail_logs)
    app.command(name="script", no_args_is_help=True)(charm_script)
    app.command(name="pebble", no_args_is_help=True)(pebble)

    def list_commands():
        """List all jhack commands and nested subcommands."""

        def display_ctree(obj, nesting=1):
            prefix = "\t" * nesting
            # print(prefix, obj.name)
            for command in obj.registered_commands:
                if command.hidden:
                    continue
                print(
                    f"{prefix + command.name:<15} {command.callback.__doc__.splitlines()[0]:<}"
                )
            for group in obj.registered_groups:
                print(
                    f"{prefix + group.typer_instance.info.name:<22} {group.typer_instance.info.help.splitlines()[0]}"
                )
                display_ctree(group.typer_instance, nesting + 1)

        print("jhack:                 What juju wished it didn't need.")
        display_ctree(app)

    app.command(name="commands")(list_commands)

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
    scenario.command(name="state-apply")(state_apply)

    chaos = typer.Typer(
        name="chaos",
        help="""Commands to spread the chaos.""",
        no_args_is_help=True,
    )
    chaos.command(name="mancioppi")(mancioppi)
    chaos.command(name="flicker")(flicker)

    # register all subcommands
    app.add_typer(conf, no_args_is_help=True)
    app.add_typer(charm, no_args_is_help=True)
    app.add_typer(utils, no_args_is_help=True)
    app.add_typer(replay, no_args_is_help=True)
    app.add_typer(integration_matrix, no_args_is_help=True)
    app.add_typer(scenario, no_args_is_help=True)
    app.add_typer(chaos, no_args_is_help=True)

    @app.callback()
    def logging_config(loglevel: str = None, log_to_file: Path = None):
        if loglevel:
            valid_loglevels = {
                "CRITICAL",
                "FATAL",
                "ERROR",
                "WARN",
                "WARNING",
                "INFO",
                "DEBUG",
                "NOTSET",
            }

            if loglevel not in valid_loglevels:
                exit(f"invalid loglevel; must be one of {valid_loglevels}")

            typer.echo(f"::= Verbose mode ({loglevel}). =::")
            logger.setLevel(loglevel)
            logging.basicConfig(stream=sys.stdout)

        if log_to_file:
            hdlr = logging.FileHandler(log_to_file)
            logger.addHandler(hdlr)

    if LOGLEVEL != "WARNING":
        typer.echo(f"::= Verbose mode ({LOGLEVEL}). =::")

    app(ignore_unknown_options=True)


if __name__ == "__main__":
    main()
