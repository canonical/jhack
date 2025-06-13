import sys
import typing
from collections import Counter
from io import StringIO
from pathlib import Path
from typing import List, Set, Optional, Dict, Union, cast, Literal

from rich.console import Console
from rich.align import Align
from rich.live import Live
from rich.style import Style
from rich.table import Table
from rich.text import Text

from jhack.conf import conf
from jhack.utils.tail_charms.ui import colors, symbols
from jhack.utils.tail_charms.ui.colors import _random_color
from jhack.version import VERSION
from jhack.utils.tail_charms.core.deferral_status import DeferralStatus

from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild(__file__)

if typing.TYPE_CHECKING:
    from jhack.utils.tail_charms.core.processor import EventLogMsg

Color = Optional[Literal["auto", "standard", "256", "truecolor", "windows", "no"]]


def _get_event_text(event: "EventLogMsg", ascii=False):
    event_text = event.event
    if "jhack" in event.tags:
        if "lobotomy" in event.tags:
            event_text += f" {symbols.lobotomy_symbol}"
        if "fire" in event.tags:
            event_text += f" {symbols.fire_symbol_ascii if ascii else symbols.fire_symbol}"
        if "replay" in event.tags:
            if "source" in event.tags:
                event_text += " (↑)"
            elif "replayed" in event.tags:
                event_text += f" ({symbols.replay_symbol}:{event.jhack_replayed_evt_timestamp} ↓)"

    if "failed" in event.tags:
        event_text += f" {symbols.bomb_symbol}"
    return event_text


class Printer:
    def _count_events(self, events: List["EventLogMsg"]):
        return Counter((e.unit for e in events))

    def render(
        self,
        events: List["EventLogMsg"],
        currently_deferred: Set["EventLogMsg"] = None,
        **kwargs,
    ):
        pass

    def quit(
        self,
        events: List["EventLogMsg"],
    ):
        pass


class PoorPrinter(Printer):
    def __init__(
        self,
        live: bool = True,
        output: Optional[Path] = None,
    ):
        self._output = output
        self._live = live
        self._out_stream = sys.stdout if live else StringIO()
        self._targets_known = set()

    def render(
        self,
        events: List["EventLogMsg"],
        currently_deferred: Set["EventLogMsg"] = None,
        **kwargs,
    ):
        targets = sorted(set(e.unit for e in events))
        if not targets:
            self._out_stream.write("Listening for events... \n")
            return

        colwidth = 20

        col_titles = ["timestamp"]
        new_cols = [0]
        for target in targets:
            col_titles.append(target)
            new_cols.append(1 if target not in self._targets_known else 0)
            self._targets_known.add(target)

        def _pad_header(h: str):
            h = f" {h} "
            hlen = len(h)
            extra = colwidth - hlen
            pre = "=" * (extra // 2)
            post = "=" * ((extra // 2) + (0 if (hlen / 2).is_integer() else 1))
            return f"{pre}{h.upper()}{post}"

        if any(new_cols):
            # print header
            header = "TIMESTAMP | " + " | ".join(map(_pad_header, col_titles[1:])) + "\n"
            self._out_stream.write(header)

        def _pad(x):
            return " " * (colwidth // 2) + x + " " * ((colwidth // 2) - len(x))

        space = _pad(".")

        msg = events[-1]
        line = f"{msg.timestamp}  | "
        spill_over = 0
        for target in targets:
            if target == msg.unit:
                evt = _get_event_text(msg, ascii=True).ljust(colwidth)
                line += evt
                spill_over = len(evt) - colwidth
            else:
                if spill_over > 0:
                    line += space[spill_over:]
                    spill_over -= colwidth

                else:
                    line += space
            line += " < " if spill_over > 0 else " | "

        line += "\n"
        self._out_stream.write(line)

    def quit(
        self,
        events: List["EventLogMsg"],
    ):
        count = self._count_events(events)
        print(
            f"Jhack tail {VERSION}:  captured {count.total()} events in {len(count.keys())} units."
        )
        if not self._live:
            if self._output:
                (self._out_stream.read())
            else:
                print(self._out_stream.read())


class RichPrinter(Printer):
    def __init__(
        self,
        color: Color = "auto",
        flip: bool = False,
        show_ns: bool = True,
        show_trace_ids: bool = False,
        show_defer: bool = False,
        output: Optional[Path] = None,
        max_length: int = 10,
        framerate: float = 0.5,
    ):
        self._color = color
        self._max_length = max_length
        self._flip = flip
        self._show_defer = show_defer
        self._show_trace_ids = show_trace_ids
        self._show_ns = show_ns
        self._rendered = False
        self._output = output
        self._framerate = framerate

        self._n_colors = {}

        if color == "no":
            color = None

        self.console = console = Console(
            color_system=color,
        )
        self.live = live = Live(
            console=console,
            refresh_per_second=conf.CONFIG.get("tail", "refresh_per_second"),
        )
        live.update("Listening for events...", refresh=True)
        live.start()

    def _n_color(self, n: int):
        if n not in self._n_colors:
            self._n_colors[n] = _random_color()
        return self._n_colors[n]

    def render(
        self,
        events: List["EventLogMsg"],
        currently_deferred: Set["EventLogMsg"] = None,
        leaders: Dict[str, str] = None,
        _debug=False,
        final: bool = False,
        **kwargs,
    ) -> Union[Table, Align]:
        self._rendered = True
        table = Table(
            show_footer=False,
            expand=True,
            header_style=Style(bgcolor=colors.header_bgcolor),
            row_styles=[Style(bgcolor=colors.alternate_row_bgcolor), Style()],
        )
        _pad = " "
        ns_shown = self._show_ns
        deferrals_shown = self._show_defer
        traces_shown = self._show_trace_ids

        # grab the most recent N events
        cropped = events[-self._max_length :]
        targets = sorted(set(e.unit for e in cropped))
        n_columns = len(targets) + 1  # for the timestamps

        matrix = [[None] * n_columns for _ in range(len(cropped))]

        for i, event in enumerate(cropped):
            matrix[i][0] = Text(event.timestamp, style=Style(color=colors.tstamp_color))
            event_row = [
                (
                    Text(
                        _get_event_text(event),
                        style=Style(color=colors.get_event_color(event)),
                    )
                    if event
                    else Text()
                )
            ]

            if deferrals_shown:
                deferral_status = event.deferred
                deferral_symbol = symbols.deferral_status_to_symbol[deferral_status]
                style = (
                    Style(color=colors.deferral_colors[deferral_status])
                    if deferral_status is not DeferralStatus.null
                    else Text()
                )
                deferral_rndr = Text(deferral_symbol, style=style)
                event_row.append(deferral_rndr)

            if ns_shown:
                n_rndr = (
                    Text(str(event.n), style=Style(color=self._n_color(event.n)))
                    if event.n
                    else Text()
                )
                event_row.insert(0, n_rndr)

            if traces_shown:
                trace_id = event.trace_id
                trace_rndr = (
                    Text(trace_id, style=Style(color=colors.trace_id_color))
                    if trace_id
                    else Text("-")
                )
                event_row.append(trace_rndr)

            matrix[i][targets.index(event.unit) + 1] = Text(_pad).join(event_row)

        if leaders:

            def _mark_if_leader(target):
                return (
                    Text(f"{target}*", style=Style(bold=True))
                    if leaders.get(target.split("/")[0]) == target
                    else target
                )

            target_headers = (_mark_if_leader(target) for target in targets)
        else:
            target_headers = targets

        headers = [f"tail v{VERSION}", *target_headers]

        for header in headers:
            table.add_column(header)
        for row in matrix if self._flip else reversed(matrix):
            table.add_row(*row)

        if table.rows:
            if self._flip:
                table.rows[-1].style = Style(bgcolor=colors.last_event_bgcolor)
            else:
                table.rows[0].style = Style(bgcolor=colors.last_event_bgcolor)

        if currently_deferred:
            table.rows[-1].end_section = True

            table.add_row(
                "Currently deferred:",
                *(
                    "\n".join(f"{e.n}:{e.event}" for e in currently_deferred if e.unit == target)
                    for target in targets
                ),
            )

        if _debug:
            self.console.print(table)
            return table

        table_centered = Align.center(table)
        self.live.update(table_centered)
        logger.debug("updated live")

        if not self.live.is_started:
            logger.info("live started by render")
            self.live.start()

        return table_centered

    def quit(
        self,
        events: List["EventLogMsg"],
    ):
        """Print a goodbye message and output a summary to file if requested."""
        if not self._rendered:
            self.live.update("No events caught.", refresh=True)
            return

        output = self._output
        if output:
            logger.info(
                "exit + output mode: setting max length to 0 to disable cropping for exit summary"
            )
            self._max_length = 0

        rendered = self.render(
            events,
            final=True,
        )
        table = cast(Table, rendered.renderable)
        table.rows[-1].end_section = True
        evt_count = self._count_events(events)

        nevents = []
        tgt_names = []
        count = self._count_events(events)
        for tgt in sorted(count):
            nevents.append(str(evt_count[tgt]))
            text = Text(tgt, style="bold")
            tgt_names.append(text)

        table.add_row(Text("Captured:", style="bold blue"), *nevents, end_section=True)

        table_centered = Align.center(table)

        self.live.update(table_centered)
        self.live.refresh()
        self.live.stop()
        self.live.console.print(
            Align.center(Text("The end.", style=Style(color="red", bold=True, blink=True)))
        )

        if not output:
            return
        if not output.parent.exists():
            logger.warning("output directory does not exist")
            return

        try:
            with open(output, "w") as o_file:
                table.expand = False
                table.padding = 1
                console = Console(file=o_file, width=10 ^ 10000, height=10 ^ 10000)
                console.print(table)

        except Exception:
            logger.exception(f"failed to write to {output}")
