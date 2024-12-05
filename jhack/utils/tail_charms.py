import enum
import random
import re
import shlex
import sys
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from io import StringIO
from pathlib import Path
from subprocess import getoutput, run
from typing import (
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    cast,
)

import typer
from rich.align import Align
from rich.color import Color
from rich.console import Console
from rich.live import Live
from rich.style import Style
from rich.table import Table
from rich.text import Text

from jhack.conf.conf import CONFIG
from jhack.helpers import JPopen, find_leaders
from jhack.logger import logger as jhack_logger
from jhack.utils.debug_log_interlacer import DebugLogInterlacer
from jhack.version import VERSION

logger = jhack_logger.getChild(__file__)

BEST_LOGLEVELS = frozenset(("DEBUG", "TRACE"))
_Color = Optional[Literal["auto", "standard", "256", "truecolor", "windows", "no"]]
AUTO_BUMP_LOGLEVEL_DEFAULT = CONFIG.get("tail", "automatically_bump_loglevel")


def model_loglevel(model: str = None):
    _model = f"-m {model} " if model else ""
    try:
        lc = JPopen(f"juju model-config {_model}logging-config".split())
        lc.wait()
        if lc.returncode != 0:
            logger.info("no model config: maybe there is no current model? defaulting to WARNING")
            return "WARNING"  # the default

        logging_config = lc.stdout.read().decode("utf-8")
        for key, val in (cfg.split("=") for cfg in logging_config.split(";")):
            if key == "unit":
                val = val.strip()
                if val not in BEST_LOGLEVELS:
                    logger.warning(
                        f"unit loglevel is {val}, which means tail will not be able to "
                        f"track Operator Framework debug logs for deferrals, reemittals, etc. "
                        f"Using juju uniter logs to track emissions. To fix this, run "
                        f"`juju model-config logging-config=<root>=WARNING;unit=TRACE`"
                    )
                return val

    except Exception as e:
        logger.error(f"failed to determine model loglevel: {e}. Guessing `WARNING` for now.")
    return "WARNING"  # the default


class LEVELS(enum.Enum):
    DEBUG = "DEBUG"
    TRACE = "TRACE"
    INFO = "INFO"
    ERROR = "ERROR"


class DeferralStatus(str, enum.Enum):
    null = "null"
    deferred = "deferred"
    reemitted = "reemitted"
    bounced = "bounced"


@dataclass
class EventLogMsg:
    type = "emitted"

    pod_name: str
    timestamp: str
    loglevel: str
    unit: str
    event: str
    mocked: bool
    deferred: DeferralStatus = DeferralStatus.null

    event_cls: str = None
    charm_name: str = None
    n: int = None

    tags: Tuple[str] = ()

    # we don't have any use for these, and they're only present if this event
    # has been (re)emitted/deferred during a relation hook call.
    endpoint: str = ""
    endpoint_id: str = ""

    # special for jhack-replay-emitted loglines
    jhack_replayed_evt_timestamp: str = ""

    # special for charm-tracing-enabled charms
    trace_id: str = ""


@dataclass
class EventDeferredLogMsg(EventLogMsg):
    type = "deferred"
    event_cls: str = ""
    charm_name: str = ""
    n: str = ""

    def __hash__(self):
        return hash((self.type, self.charm_name, self.n, self.event))


@dataclass
class EventReemittedLogMsg(EventDeferredLogMsg):
    type = "reemitted"


_event_colors_by_category = {
    "lifecycle": {
        "_action": Color.from_rgb(200, 200, 50),
        "stop": Color.from_rgb(184, 26, 71),
        "remove": Color.from_rgb(171, 81, 21),
        "start": Color.from_rgb(20, 147, 186),
        "install": Color.from_rgb(49, 183, 224),
        "update_status": Color.from_rgb(150, 150, 50),
        "collect_metrics": Color.from_rgb(50, 50, 50),
        "leader_elected": Color.from_rgb(26, 184, 68),
        "leader_settings_changed": Color.from_rgb(26, 184, 68),
    },
    "relation": {
        "_relation_created": Color.from_rgb(184, 26, 250),
        "_relation_joined": Color.from_rgb(184, 26, 230),
        "_relation_changed": Color.from_rgb(184, 26, 210),
        "_relation_departed": Color.from_rgb(184, 70, 190),
        "_relation_broken": Color.from_rgb(184, 80, 170),
    },
    "secrets": {
        "secret_changed": Color.from_rgb(10, 80, 240),
        "secret_expired": Color.from_rgb(10, 100, 250),
        "secret_remove": Color.from_rgb(10, 120, 230),
        "secret_rotate": Color.from_rgb(10, 140, 220),
    },
    "storage": {
        "_storage_attached": Color.from_rgb(184, 139, 26),
        "_storage_detaching": Color.from_rgb(184, 139, 26),
    },
    "workload": {
        "_pebble_ready": Color.from_rgb(212, 224, 40),
        "_pebble_custom_notice": Color.from_rgb(212, 210, 40),
        "_pebble_check_failed": Color.from_rgb(212, 200, 40),
        "_pebble_check_recovered": Color.from_rgb(212, 190, 40),
    },
}
_event_colors = {}
for sublist in _event_colors_by_category.values():
    _event_colors.update(sublist)

_header_bgcolor = Color.from_rgb(70, 70, 70)
_last_event_bgcolor = Color.from_rgb(50, 50, 50)
_alternate_row_bgcolor = Color.from_rgb(30, 30, 30)
_default_event_color = Color.from_rgb(255, 255, 255)
_default_n_color = Color.from_rgb(255, 255, 255)
_tstamp_color = Color.from_rgb(255, 160, 120)
_operator_event_color = Color.from_rgb(252, 115, 3)
_custom_event_color = Color.from_rgb(120, 150, 240)
_jhack_event_color = Color.from_rgb(200, 200, 50)
_jhack_fire_event_color = Color.from_rgb(250, 200, 50)
_jhack_lobotomy_event_color = Color.from_rgb(150, 210, 110)
_jhack_replay_event_color = Color.from_rgb(100, 100, 150)
_deferral_colors = {
    DeferralStatus.null: "",
    DeferralStatus.deferred: "red",
    DeferralStatus.reemitted: "green",
    DeferralStatus.bounced: Color.from_rgb(252, 115, 3),
}


# todo: should we have a "console compatibility mode" using ascii here?
_bounce = "●"  # "●•⭘" not all alternatives supported on all consoles
_close = "❮"
_open = "❯"
_null = ""

_deferral_status_to_symbol = {
    DeferralStatus.null: _null,
    DeferralStatus.deferred: _open,
    DeferralStatus.reemitted: _close,
    DeferralStatus.bounced: _bounce,
}

_trace_id_color = Color.from_rgb(100, 100, 210)


def _print_color_codes():
    console = Console(color_system="truecolor")
    table = Table("category", "color", "description", expand=True)
    for cat, example, color, desc in (
        (
            "origin",
            "some_event",
            _operator_event_color,
            "operator event (cfr. the elusive [`OPERATOR_DISPATCH`](https://github.com/canonical/operator/blob/main/ops/_main.py#L319))",
        ),
        (
            "",
            "custom_event",
            _custom_event_color,
            "custom event emitted by the charm on itself",
        ),
        (
            "",
            f"foo-pebble-ready {_fire_symbol}",
            _jhack_fire_event_color,
            "event emitted by `jhack fire`",
        ),
        (
            "",
            f"install {_lobotomy_symbol}",
            _jhack_lobotomy_event_color,
            "event intercepted by `jhack lobotomy` (therefore, NOT emitted on the charm)",
        ),
        (
            "",
            f"foo-relation-broken {_replay_symbol}",
            _jhack_replay_event_color,
            "event emitted by `jhack replay`",
        ),
    ):
        table.add_row(cat, Text(example, style=Style(color=color)), desc)
    table.add_section()

    for cat, evt_to_color in _event_colors_by_category.items():
        for evt, color in evt_to_color.items():
            event_name = "*" + evt if evt.startswith("_") else evt
            table.add_row(
                cat,
                Text(event_name, style=Style(color=color)),
                f"the '{event_name}' juju event",
            )
            cat = ""

    table.add_section()
    table.add_row(
        "uncategorized",
        Text("foo_bar_baz", style=Style(color=_default_event_color)),
        "uncategorized event (unknown origin and type)",
    )
    table.add_section()

    id_color = _random_color()
    for deferral_status, explanation in (
        ("deferred", "the 'some_event' event has been deferred and assigned number 13"),
        ("reemitted", "the event #13 has been reemitted"),
        ("bounced", "the event #13 has been reemitted and immediately re-deferred"),
    ):
        table.add_row(
            deferral_status,
            Text("13 ", style=Style(color=id_color))
            + Text("some_event", style=Style(color=_jhack_fire_event_color))
            + "  "
            + Text(
                _deferral_status_to_symbol[deferral_status],
                style=Style(color=_deferral_colors[deferral_status]),
            ),
            explanation,
        )

    console.print(table)


def _random_color():
    r = random.randint(0, 255)
    g = random.randint(0, 255)
    b = random.randint(0, 255)
    return Color.from_rgb(r, g, b)


class LogLineParser:
    base_pattern = (
        "^(?P<pod_name>\S+): (?P<timestamp>\S+(\s*\S+)?) (?P<loglevel>\S+) "
        "unit\.(?P<unit>\S+)\.juju-log "
    )
    base_relation_pattern = base_pattern + "(?P<endpoint>\S+):(?P<endpoint_id>\S+): "

    operator_event_suffix = "Charm called itself via hooks/(?P<event>\S+)\."
    operator_event = re.compile(base_pattern + operator_event_suffix)

    event_suffix = "Emitting Juju event (?P<event>\S+)\."
    event_emitted = re.compile(base_pattern + event_suffix)
    event_emitted_from_relation = re.compile(base_relation_pattern + event_suffix)

    # modifiers
    jhack_fire_evt_suffix = "The previous (?P<event>\S+) was fired by jhack\."
    event_fired_jhack = re.compile(base_pattern + jhack_fire_evt_suffix)
    jhack_replay_evt_suffix = (
        "(?P<event>\S+) \((?P<jhack_replayed_evt_timestamp>\S+(\s*\S+)?)\)"
        " was replayed by jhack\."
    )
    event_replayed_jhack = re.compile(base_pattern + jhack_replay_evt_suffix)

    event_repr = r"<(?P<event_cls>\S+) via (?P<charm_name>\S+)/on/(?P<event>\S+)\[(?P<n>\d+)\]>\."
    defer_suffix = "Deferring " + event_repr
    event_deferred = re.compile(base_pattern + defer_suffix)
    event_deferred_from_relation = re.compile(base_relation_pattern + defer_suffix)

    # unit-tempo-0: 12:28:24 DEBUG unit.tempo/0.juju-log Starting root trace with id=XXX.
    # we ignore the relation tag since we don't really care with modifier loglines
    trace_id = re.compile(
        base_pattern + "(.* )?" + r"Starting root trace with id='(?P<trace_id>\S+)'\."
    )

    custom_event_suffix = "Emitting custom event " + event_repr
    custom_event = re.compile(base_pattern + custom_event_suffix)  # ops >= 2.1
    custom_event_from_relation = re.compile(
        base_relation_pattern + custom_event_suffix
    )  # ops >= 2.1

    reemitted_suffix_old = "Re-emitting " + event_repr  # ops < 2.1
    event_reemitted_old = re.compile(base_pattern + reemitted_suffix_old)
    event_reemitted_from_relation_old = re.compile(base_relation_pattern + reemitted_suffix_old)

    reemitted_suffix_new = "Re-emitting deferred event " + event_repr  # ops >= 2.1
    event_reemitted_new = re.compile(base_pattern + reemitted_suffix_new)
    event_reemitted_from_relation_new = re.compile(base_relation_pattern + reemitted_suffix_new)

    lobotomy_suffix = "(?:selective|full) lobotomy ACTIVE: event hooks\/(?P<event>\S+) ignored."
    lobotomy_skipped_event = re.compile(base_pattern + lobotomy_suffix)

    uniter_event = re.compile(
        r"^unit-(?P<unit_name>\S+)-(?P<unit_number>\d+): (?P<timestamp>\S+( \S+)?) "
        r'(?P<loglevel>\S+) juju\.worker\.uniter\.operation ran "(?P<event>\S+)" hook '
        r"\(via hook dispatching script: dispatch\)"
    )

    tags = {
        operator_event: ("operator",),
        event_fired_jhack: ("jhack", "fire"),
        lobotomy_skipped_event: ("jhack", "lobotomy"),
        event_replayed_jhack: ("jhack", "replay"),
        custom_event: ("custom",),
        custom_event_from_relation: ("custom",),
        trace_id: ("trace_id",),
    }

    def __init__(self, model: str = None):
        self._loglevel = model_loglevel(model=model)

    @property
    def uniter_events_only(self) -> bool:
        return self._loglevel not in BEST_LOGLEVELS

    @staticmethod
    def _uniform_event(event: str):
        return event.replace("-", "_")

    def _match(self, msg, *matchers) -> Optional[Dict[str, str]]:
        if not matchers:
            raise ValueError("no matchers provided")

        for matcher in matchers:
            if match := matcher.match(msg):
                tags = self.tags.get(matcher, ())
                dct = match.groupdict()
                dct["tags"] = tags
                dct["event"] = self._uniform_event(dct.get("event", ""))
                return dct
        return None

    def match_event_deferred(self, msg):
        if self.uniter_events_only:
            return None
        return self._match(msg, self.event_deferred, self.event_deferred_from_relation)

    def match_event_emitted(self, msg):
        if match := self._match(msg, self.lobotomy_skipped_event):
            return match

        if self.uniter_events_only:
            match = self._match(msg, self.uniter_event)
            if not match:
                return None
            unit = match.pop("unit_name")
            n = match.pop("unit_number")
            match["pod_name"] = f"{unit}-{n}"
            match["unit"] = f"{unit}/{n}"
            if "date" in match:
                del match["date"]
            return match

        return self._match(
            msg,
            self.event_emitted,
            self.lobotomy_skipped_event,
            self.event_emitted_from_relation,
            self.operator_event,
            self.custom_event,
            self.custom_event_from_relation,
        )

    def match_jhack_modifiers(self, msg, trace_id: bool = False):
        # jhack fire/replay may emit some loglines that aim at modifying the meaning of
        # previously parsed loglines
        if self.uniter_events_only:
            return
        mods = [self.event_fired_jhack, self.event_replayed_jhack]
        if trace_id:
            # don't search for trace ids unless they are enabled
            mods += [self.trace_id]
        match = self._match(msg, *mods)
        return match

    def match_event_reemitted(self, msg):
        if self.uniter_events_only:
            return None
        return self._match(
            msg,
            self.event_reemitted_old,
            self.event_reemitted_from_relation_old,
            self.event_reemitted_new,
            self.event_reemitted_from_relation_new,
        )


def _get_event_color(event: EventLogMsg) -> Color:
    """Color-code the events as they are displayed to make reading them easier."""
    # If we have a log message to start from, use any relevant tags to determine what type of event it is
    if "custom" in event.tags:
        return _custom_event_color
    if "operator" in event.tags:
        return _operator_event_color
    if "jhack" in event.tags:
        if "fire" in event.tags:
            return _jhack_fire_event_color
        elif "replay" in event.tags:
            return _jhack_replay_event_color
        elif "lobotomy" in event.tags:
            return _jhack_lobotomy_event_color
        return _jhack_event_color

    # if we are coloring an event without tags,
    # use the event-specific color coding.
    if event.event in _event_colors:
        return _event_colors.get(event.event, _default_event_color)
    else:
        for _e in _event_colors:
            if event.event.endswith(_e):
                return _event_colors[_e]
    return _default_event_color


_fire_symbol = "🔥"
_fire_symbol_ascii = "*"
_lobotomy_symbol = "✂"
_replay_symbol = "⟳"


def _get_event_text(event: EventLogMsg, ascii=False):
    event_text = event.event
    if "jhack" in event.tags:
        if "lobotomy" in event.tags:
            event_text += f" {_lobotomy_symbol}"
        if "fire" in event.tags:
            event_text += f" {_fire_symbol_ascii if ascii else _fire_symbol}"
        if "replay" in event.tags:
            if "source" in event.tags:
                event_text += " (↑)"
            elif "replayed" in event.tags:
                event_text += f" ({_replay_symbol}:{event.jhack_replayed_evt_timestamp} ↓)"
    return event_text


class Printer:
    def _count_events(self, events: List[EventLogMsg]):
        return Counter((e.unit for e in events))

    def render(
        self,
        events: List[EventLogMsg],
        currently_deferred: Set[EventLogMsg] = None,
        **kwargs,
    ):
        pass

    def quit(
        self,
        events: List[EventLogMsg],
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
        events: List[EventLogMsg],
        currently_deferred: Set[EventLogMsg] = None,
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
        events: List[EventLogMsg],
    ):
        count = self._count_events(events)
        # counter has a .total() method since python 3.10
        print(
            f"Jhack tail v0.4:  captured {sum(count.values())} events in {len(count.keys())} units."
        )
        if not self._live:
            if self._output:
                (self._out_stream.read())
            else:
                print(self._out_stream.read())


class RichPrinter(Printer):
    def __init__(
        self,
        color: _Color = "auto",
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
        self.live = live = Live(console=console, refresh_per_second=60 / self._framerate)
        live.update("Listening for events...", refresh=True)
        live.start()

    def _n_color(self, n: int):
        if n not in self._n_colors:
            self._n_colors[n] = _random_color()
        return self._n_colors[n]

    def render(
        self,
        events: List[EventLogMsg],
        currently_deferred: Set[EventLogMsg] = None,
        leaders: Dict[str, str] = None,
        _debug=False,
        final: bool = False,
        **kwargs,
    ) -> Union[Table, Align]:
        self._rendered = True
        table = Table(
            show_footer=False,
            expand=True,
            header_style=Style(bgcolor=_header_bgcolor),
            row_styles=[Style(bgcolor=_alternate_row_bgcolor), Style()],
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
            matrix[i][0] = Text(event.timestamp, style=Style(color=_tstamp_color))
            event_row = [
                (
                    Text(
                        _get_event_text(event),
                        style=Style(color=_get_event_color(event)),
                    )
                    if event
                    else Text()
                )
            ]

            if deferrals_shown:
                deferral_status = event.deferred
                deferral_symbol = _deferral_status_to_symbol[deferral_status]
                style = (
                    Style(color=_deferral_colors[deferral_status])
                    if deferral_status != DeferralStatus.null
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
                    Text(trace_id, style=Style(color=_trace_id_color)) if trace_id else Text("-")
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
                table.rows[-1].style = Style(bgcolor=_last_event_bgcolor)
            else:
                table.rows[0].style = Style(bgcolor=_last_event_bgcolor)

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
        events: List[EventLogMsg],
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


class Processor:
    def __init__(
        self,
        targets: Sequence[str],
        leaders: Dict[str, str] = None,
        add_new_units: bool = True,
        max_length: int = 10,
        show_ns: bool = True,
        show_trace_ids: bool = False,
        show_defer: bool = False,
        event_filter_re: re.Pattern = None,
        model: str = None,
        output: str = None,
        printer: Literal["rich", "raw"] = "rich",
        # only available in rich printing mode
        color: _Color = "auto",
        flip: bool = False,
        framerate: int = 0.5,
    ):
        self.targets = targets
        self.leaders = leaders or {}
        self.output = Path(output) if output else None
        self.add_new_units = add_new_units

        if printer == "raw":
            if flip or (color != "auto"):
                logger.warning("'flip' and 'color' args unavailable in this printer mode.")
            self.printer = PoorPrinter(
                live=True,
                output=self.output,
            )

        elif printer == "rich":
            self.printer = RichPrinter(
                color=color,
                flip=flip,
                show_defer=show_defer,
                show_ns=show_ns,
                show_trace_ids=show_trace_ids,
                output=self.output,
                max_length=max_length,
                framerate=framerate,
            )
        else:
            exit(f"unknown printer type: {printer}")

        self.event_filter_re = event_filter_re
        self._captured_logs: List[EventLogMsg] = []
        self._currently_deferred: Set[EventLogMsg] = set()

        self._show_ns = show_ns and show_defer
        self._show_defer = show_defer
        self._flip = flip
        self._show_trace_ids = show_trace_ids
        self._next_msg_trace_id: Optional[str] = None

        self._has_just_emitted = False
        self._warned_about_orphans = False
        self.parser = LogLineParser(model=model)

    def _warn_about_orphaned_event(self, evt):
        if self._warned_about_orphans:
            return
        logger.warning(
            f"Error processing {evt.event}({getattr(evt, 'n', '?')}); no "
            f"matching deferred event could be found in the currently "
            f"deferred/previously emitted ones. This can happen if you only set "
            f"logging-config to DEBUG after the first events got deferred, "
            f"or after the history started getting recorded anyway. "
            f"This means you might see some messy output."
        )
        self._warned_about_orphans = True

    def _defer(self, deferred: EventDeferredLogMsg):
        # find the original message we're deferring
        found = None
        for captured in filter(lambda e: e.unit == deferred.unit, self._captured_logs[::-1]):
            if captured.event == deferred.event:
                found = captured
                break

        if not found:
            # we're deferring an event we've not seen before: logging just started.
            # so we pretend we've seen it, to be safe.
            found = EventLogMsg(
                pod_name=deferred.pod_name,
                timestamp="",
                loglevel=deferred.loglevel,
                unit=deferred.unit,
                event=deferred.event,
                mocked=True,
                deferred=DeferralStatus.deferred,
            )
            self._captured_logs.append(found)
            logger.debug(f"Mocking {found}: we're deferring it but " f"we've not seen it before.")

        currently_deferred_ns = {d.n for d in self._currently_deferred}
        is_already_deferred = deferred.n in currently_deferred_ns
        found.n = deferred.n
        if found.deferred == DeferralStatus.reemitted:
            # the event we found
            found.deferred = DeferralStatus.bounced
        else:
            found.deferred = DeferralStatus.deferred

        if not is_already_deferred:
            logger.debug(f"deferring {deferred}")
            self._currently_deferred.add(deferred)
        else:
            # not the first time we defer this boy
            logger.debug(f"bouncing {deferred.event}")

    def _reemit(self, reemitted: EventReemittedLogMsg):
        # search deferred queue first to last
        deferred = None
        for _deferred in list(self._currently_deferred):
            if _deferred.n == reemitted.n:
                deferred = _deferred

        if not deferred:
            self._warn_about_orphaned_event(reemitted)
            # if we got here we need to make up a lane for the message.
            deferred = EventDeferredLogMsg(
                pod_name=reemitted.pod_name,
                timestamp="",
                loglevel=reemitted.loglevel,
                unit=reemitted.unit,
                event=reemitted.event,
                event_cls=reemitted.event_cls,
                charm_name=reemitted.charm_name,
                n=reemitted.n,
                mocked=True,
            )

            self._defer(deferred)
            logger.debug(
                f"mocking {deferred}: we're reemitting it but " f"we've not seen it before."
            )
            # the 'happy path' would have been: _emit, _defer, _emit, _reemit,
            # so we need to _emit it once more to pretend we've seen it.

        reemitted.deferred = DeferralStatus.reemitted
        self._currently_deferred.remove(deferred)

        logger.debug(f"reemitted {reemitted.event}")

    def _match_filter(self, event_name: str) -> bool:
        """If the user specified an event name regex filter, run it."""
        if not self.event_filter_re:
            return True
        match = self.event_filter_re.match(event_name)
        return bool(match)

    def _match_event_deferred(self, log: str) -> Optional[EventDeferredLogMsg]:
        if "Deferring" not in log:
            return
        match = self.parser.match_event_deferred(log)
        if match:
            if not self._match_filter(match["event"]):
                return
            return EventDeferredLogMsg(**match, mocked=False)

    def _match_event_reemitted(self, log: str) -> Optional[EventReemittedLogMsg]:
        if "Re-emitting" not in log:
            return
        match = self.parser.match_event_reemitted(log)
        if match:
            if not self._match_filter(match["event"]):
                return
            return EventReemittedLogMsg(**match, mocked=False)

    def _match_event_emitted(self, log: str) -> Optional[EventLogMsg]:
        match = self.parser.match_event_emitted(log)
        if match:
            if not self._match_filter(match["event"]):
                return
            return EventLogMsg(**match, mocked=False)

    def _match_jhack_modifiers(self, log: str) -> Optional[EventLogMsg]:
        match = self.parser.match_jhack_modifiers(log, trace_id=self._show_trace_ids)
        if match:
            if not self._match_filter(match["event"]):
                return
            return EventLogMsg(**match, mocked=False)

    def _apply_jhack_mod(self, msg: EventLogMsg):
        def _get_referenced_msg(event: Optional[str], unit: str) -> Optional[EventLogMsg]:
            # this is the message we're referring to, the one we're modifying
            logs = self._captured_logs
            if not event:
                if not logs:
                    logger.error("cannot reference the previous event: no messages.")
                    return
                return logs[-1]
            # try to find last event of this type emitted on the same unit:
            # that is the one we're referring to
            try:
                referenced_log = next(
                    filter(lambda e: e.event == event and e.unit == unit, logs[::-1])
                )
            except StopIteration:
                logger.error(f"{unit}:{event} not found in history...")
                return
            return referenced_log

        if "fire" in msg.tags:
            # the previous event of this type was fired by jhack.
            # copy over the tags
            referenced_msg = _get_referenced_msg(msg.event, msg.unit)
            if referenced_msg:
                referenced_msg.tags = msg.tags

        elif "trace_id" in msg.tags:
            # the NEXT logged event of this type was traced by Tempo's trace_charm library.
            # tag the event message with the trace id.
            self._next_msg_trace_id = msg.trace_id

        elif "replay" in msg.tags:
            # the previous event of this type was replayed by jhack.
            # we log as if we emitted one.
            self._captured_logs.append(msg)

            original_evt_timestamp = msg.jhack_replayed_evt_timestamp
            original_event = None
            for msg in self._captured_logs:
                if msg.timestamp == original_evt_timestamp:
                    original_event = msg
                    break
            if original_event:
                # add tags: if the original event was jhack-fired, we don't want to lose that info.
                original_event.tags += ("jhack", "replay", "source")
            else:
                logger.debug(
                    f"original event out of scope: {original_evt_timestamp} is "
                    f"too far in the past."
                )
            msg.tags = ("jhack", "replay", "replayed")

        else:
            raise ValueError(f"unsupported jhack modifier tags: {msg.tags}")

    def process(self, log: str) -> Optional[EventLogMsg]:
        """process a log line"""
        if msg := self._match_jhack_modifiers(log):
            mode = "jhack-mod"
        elif msg := self._match_event_emitted(log):
            mode = "emit"
        elif self._show_defer:
            if msg := self._match_event_deferred(log):
                mode = "defer"
            elif msg := self._match_event_reemitted(log):
                mode = "reemit"
            else:
                return
        else:
            return

        if not self._is_tracking(msg.unit):
            print("skipped as untracked")
            return

        self._update_leader(msg)

        if mode in {"emit", "reemit"}:
            logger.debug("captured event!")
            self._captured_logs.append(msg)
        if mode == "defer":
            self._defer(msg)
        elif mode == "reemit":
            self._reemit(msg)
        elif mode == "jhack-mod":
            self._apply_jhack_mod(msg)

        if mode in {"reemit", "emit"} or (mode == "jhack-mod" and "replay" in msg.tags):
            if self._next_msg_trace_id:
                # the trace id is one of the first thing the lib logs.
                # Therefore, it actually occurs BEFORE the logline presenting the event is emitted.
                # so we have to store it and pop it when the emission event logline comes in.
                msg.trace_id = self._next_msg_trace_id
                self._next_msg_trace_id = None

        self.printer.render(
            events=self._captured_logs,
            currently_deferred=self._currently_deferred,
            leaders=self.leaders,
        )
        return msg

    def quit(self):
        self.printer.quit(self._captured_logs)

    @lru_cache()
    def _is_tracking(self, unit: str):
        if not self.targets:
            return True

        def get_app(unit_name: str):
            return unit_name.split("/")[0]

        match_app = self.add_new_units

        for target in self.targets:
            u_app = get_app(unit)
            if match_app and get_app(target) == u_app:
                return True

            # target is a unit name
            if target == unit:
                return True

            # target is an app name
            elif "/" not in target and target == u_app:
                return True

        return False

    def _update_leader(self, msg: EventLogMsg):
        if msg.event == "leader_elected":
            unit = msg.unit
            self.leaders[unit.split("/")[0]] = unit


class _Printer(str, enum.Enum):
    rich = "rich"
    raw = "raw"


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
    level: LEVELS = "DEBUG",
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
    color: str = typer.Option(
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

    return _tail_events(
        targets=target,
        add_new_units=add_new_units,
        level=level,
        replay=replay,
        printer=printer,
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


def _get_debug_log(cmd):
    # to easily allow mocking in tests
    return JPopen(cmd)


def _tail_events(
    targets: List[str] = None,
    add_new_units: bool = True,
    level: LEVELS = "DEBUG",
    replay: bool = True,  # listen from beginning of time?
    dry_run: bool = False,
    framerate: float = 0.5,
    length: int = 10,
    show_defer: bool = False,
    show_ns: bool = False,
    flip: bool = False,
    show_trace_ids: bool = False,
    watch: bool = True,
    color: _Color = "auto",
    files: List[Union[str, Path]] = None,
    event_filter: str = None,
    # for script use only
    _on_event: Callable[[EventLogMsg], None] = None,
    model: str = None,
    output: str = None,
    printer: Literal["rich", "raw"] = "rich",
    auto_bump_loglevel: bool = False,
):
    if output:
        logger.debug("output mode. Overriding watch.")
        watch = False
        auto_bump_loglevel = (
            False  # it's too late for that, we're replaying the history and transforming it.
        )

    if isinstance(level, str):
        level = getattr(LEVELS, level.upper())

    if not isinstance(level, LEVELS):
        raise ValueError(level)

    if level not in {LEVELS.DEBUG, LEVELS.TRACE}:
        logger.debug(f"we won't be able to track events with level={level}")

    if not targets and add_new_units:
        logger.debug("targets not provided; overruling add_new_units param.")
        add_new_units = False

    if files and replay:
        logger.debug("ignoring `replay` because files were provided")
        replay = False

    if files and watch:
        logger.debug("ignoring `watch` because files were provided")
        watch = False

    logger.debug("starting to read logs")
    cmd = (
        ["juju", "debug-log"]
        + (["-m", model] if model else [])
        + (["--tail"] if watch else [])
        + ["--level", level.value]
    )

    if dry_run:
        print(" ".join(cmd))
        return

    previous_loglevel = ""
    if auto_bump_loglevel:
        previous_loglevel = bump_loglevel()

    event_filter_pattern = re.compile(event_filter) if event_filter else None
    leaders = find_leaders(targets, model=model)
    processor = Processor(
        targets,
        leaders=leaders,
        add_new_units=add_new_units,
        max_length=length,
        show_ns=show_ns,
        show_trace_ids=show_trace_ids,
        printer=printer,
        color=color,
        show_defer=show_defer,
        event_filter_re=event_filter_pattern,
        model=model,
        flip=flip,
        output=output,
        framerate=framerate,
    )

    if replay:
        logger.debug("doing replay")
        proc = _get_debug_log(
            ["juju", "debug-log"]
            + (["-m", model] if model else [])
            + ["--level", level.value]
            + ["--replay", "--no-tail"]
        )
        for line in iter(proc.stdout.readlines()):
            processor.process(line.decode("utf-8").strip())

        logger.debug("replay complete")
        logger.debug(f"captured: {processor.printer._count_events(processor._captured_logs)}")

    try:
        if files:
            # handle input from files
            log_getter = DebugLogInterlacer(files)
            logger.debug("setting up file-watcher next-line generator")

            def next_line():
                try:
                    # Encode to be similar to other input sources
                    return log_getter.readline().encode("utf-8")
                except StopIteration:
                    return ""

        else:
            proc = _get_debug_log(cmd)

            if not watch:
                stdout = iter(proc.stdout.readlines())
                logger.debug("setting up no-watch next-line generator")

                def next_line():
                    try:
                        return next(stdout)
                    except StopIteration:
                        return ""

            else:
                logger.debug("setting up standard next-line generator")

                def next_line():
                    line = proc.stdout.readline()
                    return line

        while True:
            line = next_line()

            if line:
                msg = line.decode("utf-8").strip()
                captured = processor.process(msg)

                # notify listeners that an event has been captured.
                if _on_event and captured:
                    _on_event(captured)

            else:
                logger.debug("no new line received; interrupting tail")
                # if we didn't get a line, it is because there are no new logs.
                if not watch or not files:
                    break

                # if we've been called with the --output flag,
                # we write what we have replayed to file and exit
                if output:
                    exit()

                continue

    except KeyboardInterrupt:
        pass  # quit
    finally:
        if auto_bump_loglevel and previous_loglevel:
            debump_loglevel(previous_loglevel)

        processor.quit()

    return processor  # for testing


def _put(s: str, index: int, char: Union[str, Dict[str, str]], placeholder=" "):
    if isinstance(char, str):
        char = {None: char}

    if len(s) <= index:
        s += placeholder * (index - len(s)) + char[None]
        return s

    charlist = list(s)
    charlist[index] = char.get(charlist[index], char[None])
    return "".join(charlist)


def bump_loglevel() -> Optional[str]:
    cmd = "juju model-config logging-config"
    old_config = getoutput(cmd).strip()
    cfgs = old_config.split(";")
    new_config = []

    for cfg in cfgs:
        if "ERROR" in cfg:
            logger.error(f"failed bumping loglevel to unit=TRACE: {cfg}")
            return

        n, lvl = cfg.split("=")
        if n == "unit":
            logger.debug(f"existing unit-level logging config found: was {lvl}")
            continue
        new_config.append(cfg)

    new_config.append("unit=TRACE")

    cmd = f"juju model-config logging-config={';'.join(new_config)!r}"
    run(shlex.split(cmd))
    return old_config


def debump_loglevel(previous: str):
    cmd = f"juju model-config logging-config={previous!r}"
    run(shlex.split(cmd))


if __name__ == "__main__":
    import cProfile
    import io
    import pstats
    from pstats import SortKey

    pr = cProfile.Profile()
    pr.enable()
    try:
        _tail_events(length=30, replay=True)
    finally:
        pr.disable()
        s = io.StringIO()
        sortby = SortKey.CUMULATIVE
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats()
        print(s.getvalue())
