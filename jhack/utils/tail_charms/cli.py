import enum
from typing import List, Optional

import typer
from rich.console import Console
from rich.style import Style
from rich.table import Table
from rich.text import Text

from jhack.utils.tail_charms.core.juju_model_loglevel import (
    AUTO_BUMP_LOGLEVEL_DEFAULT,
)
from jhack.utils.tail_charms.core.deferral_status import DeferralStatus
from jhack.utils.tail_charms.tail_charms import tail_charms
from jhack.utils.tail_charms.ui import colors, symbols


class _Color(str, enum.Enum):
    auto = "auto"
    standard = "standard"
    # 256 = "256"
    truecolor = "truecolor"
    windows = "windows"
    no = "no"


class _Printer(str, enum.Enum):
    rich = "rich"
    raw = "raw"


def _print_color_codes():
    console = Console(color_system="truecolor")
    table = Table("category", "color", "description", expand=True)
    for cat, example, color, desc in (
        (
            "origin",
            "some_event",
            colors.operator_event_color,
            "operator event (cfr. the elusive [`OPERATOR_DISPATCH`](https://github.com/canonical/operator/blob/main/ops/_main.py#L319))",
        ),
        (
            "",
            "custom_event",
            colors.custom_event_color,
            "custom event emitted by the charm on itself",
        ),
        (
            "",
            "unknown_event",
            colors.default_event_color,
            "uncategorized (aka unknown) event type.",
        ),
        (
            "jhacks",
            f"foo-pebble-ready {symbols.fire_symbol}",
            colors.jhack_fire_event_color,
            "event emitted by `jhack fire`",
        ),
        (
            "",
            f"install {symbols.lobotomy_symbol}",
            colors.jhack_lobotomy_event_color,
            "event intercepted by `jhack lobotomy` (therefore, NOT emitted on the charm)",
        ),
        (
            "",
            f"foo-relation-broken {symbols.replay_symbol}",
            colors.jhack_replay_event_color,
            "event emitted by `jhack replay`",
        ),
    ):
        table.add_row(cat, Text(example, style=Style(color=color)), desc)

    table.add_row(
        "errors",
        Text("some_event", style=Style(color=colors.default_event_color))
        + "  "
        + Text(
            symbols.bomb_symbol,
            style=Style(color=color),
        ),
        "this event has been processed with error (dispatch exited nonzero)",
    )

    for cat, explanation, symbol, color in (
        (
            "deferrals",
            "this event has been deferred",
            symbols.deferral_status_to_symbol[DeferralStatus.deferred],
            colors.deferral_colors[DeferralStatus.deferred],
        ),
        (
            "",
            "this event has been reemitted",
            symbols.deferral_status_to_symbol[DeferralStatus.reemitted],
            colors.deferral_colors[DeferralStatus.reemitted],
        ),
        (
            "",
            "this event has been reemitted and immediately re-deferred",
            symbols.deferral_status_to_symbol[DeferralStatus.bounced],
            colors.deferral_colors[DeferralStatus.bounced],
        ),
    ):
        table.add_row(
            cat,
            Text("some_event", style=Style(color=colors.default_event_color))
            + "  "
            + Text(
                symbol,
                style=Style(color=color),
            ),
            explanation,
        )

    table.add_section()

    for cat, evt_to_color in colors.event_colors_by_category.items():
        for evt, color in evt_to_color.items():
            event_name = "*" + evt if evt.startswith("_") else evt
            table.add_row(
                cat,
                Text(event_name, style=Style(color=color)),
                f"the '{event_name}' juju event",
            )
            cat = ""

    console.print(table)


def tail_events(
    target: List[str] = typer.Argument(
        None,
        help="Target to follow. Example: 'foo/0' or 'bar' (all bar units). "
        "By default, it will follow all "
        "available targets.",
    ),
    add_new_units: bool = typer.Option(
        True,
        "--add",
        "-a",
        help="Track by app name instead of by unit name. Meaningless without targets.",
    ),
    replay: bool = typer.Option(False, "--replay", "-r", help="Start from the beginning of time."),
    dry_run: bool = typer.Option(False, help="Only print what you would have done, exit."),
    framerate: float = typer.Option(0.5, help="Framerate cap."),
    length: int = typer.Option(10, "-l", "--length", help="Maximum history length to show."),
    show_defer: bool = typer.Option(
        False, "-d", "--show-defer", help="Visualize the defer graph."
    ),
    show_trace_ids: bool = typer.Option(
        False, "-t", "--show-trace-ids", help="Show Tempo trace IDs if available."
    ),
    show_operator_events: bool = typer.Option(
        False, "--show-operator-events", help="Show Operator events."
    ),
    show_ns: bool = typer.Option(
        False,
        "-n",
        "--show-defer-id",
        help="Prefix deferred events with their deferral ID. This is an ID assigned to an event by the operator "
        "framework when it is first deferred, so that, when it is reemitted (and possibly redeferred), "
        "we can follow it and see whether the event being processed is 'the same event' that was originally "
        "deferred or an identical one."
        "Only applicable if show_defer=True.",
    ),
    watch: bool = typer.Option(True, help="Keep listening.", is_flag=True),
    flip: bool = typer.Option(False, help="Last events last.", is_flag=True),
    printer: _Printer = typer.Option(
        "rich",
        help="Printer mode. "
        "Supported printers are 'rich' and 'raw'. "
        "Rich is prettier and has way more features, but is also slower.",
    ),
    color: _Color = typer.Option(
        "auto",
        "-c",
        "--color",
        help="Color scheme to adopt. Supported options: "
        "['auto', 'standard', '256', 'truecolor', 'windows', 'no'] "
        "no: disable colors entirely.",
    ),
    file: Optional[List[str]] = typer.Option(
        [],
        help="Text file with logs from `juju debug-log`.  Can be used in place of streaming "
        "logs directly from juju, and can be set multiple times to read from multiple "
        "files.  File must be exported from juju using `juju debug-log --date` to allow"
        " for proper sorting",
    ),
    filter_events: Optional[str] = typer.Option(
        None,
        "-f",
        "--filter",
        help="Python-style regex pattern to filter events by name with."
        "Examples: "
        "  -f '(?!update)' --> all events except those starting with 'update'."
        "  -f 'ingress' --> all events starting with 'ingress'.",
    ),
    model: str = typer.Option(None, "-m", "--model", help="Which model to apply the command to."),
    output: str = typer.Option(
        None,
        "-o",
        "--output",
        help="Replay the whole event history log and output it to a file. Overrides --watch.",
    ),
    auto_bump_loglevel: bool = typer.Option(
        AUTO_BUMP_LOGLEVEL_DEFAULT,
        "-b",
        "--auto-bump-loglevel",
        is_flag=True,
        help="Set unit loglevel to TRACE automatically, and set it back on exit to whatever it "
        "previously was. Allows for more accurate event traces. You can enabled it by default in "
        "jhack conf.",
    ),
    print_color_codes: bool = typer.Option(
        False,
        "--print-color-codes",
        is_flag=True,
        help="Print the color codes used by jhack tail and exit.",
    ),
):
    """Pretty-print a table with the events that are being fired on juju units
    in the current model.
    Examples: jhack tail -d mongo-k8s/2

    To display an explanation of the color codes used by jhack, run with the --print-color-codes flag.
    """
    if print_color_codes:
        _print_color_codes()
        return

    return tail_charms(
        targets=target,
        add_new_units=add_new_units,
        replay=replay,
        show_operator_events=show_operator_events,
        printer=printer.value,  # type:ignore
        dry_run=dry_run,
        framerate=framerate,
        length=length,
        show_defer=show_defer,
        show_ns=show_ns,
        show_trace_ids=show_trace_ids,
        watch=watch,
        color=color,
        files=file,
        event_filter=filter_events,
        model=model,
        flip=flip,
        output=output,
        auto_bump_loglevel=auto_bump_loglevel,
    )
