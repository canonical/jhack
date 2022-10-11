import enum
import random
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path
from subprocess import PIPE, STDOUT
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Literal,
    Optional,
    Sequence,
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

from jhack.helpers import JPopen, juju_status, juju_version
from jhack.logger import logger as jhacklogger
from jhack.utils.debug_log_interlacer import DebugLogInterlacer

logger = jhacklogger.getChild(__file__)

JUJU_VERSION = juju_version()
_Color = Optional[Literal["auto", "standard", "256", "truecolor", "windows", "no"]]


@dataclass
class Target:
    app: str
    unit: int
    leader: bool = False

    @staticmethod
    def from_name(name: str):
        if "/" not in name:
            logger.warning(
                "invalid target name: expected `<app_name>/<unit_id>`; "
                f"got {name!r}."
            )
        app, unit_ = name.split("/")
        leader = unit_.endswith("*")
        unit = unit_.strip("*")
        return Target(app, unit, leader=leader)

    @property
    def unit_name(self):
        return f"{self.app}/{self.unit}"

    def __hash__(self):
        return hash((self.app, self.unit, self.leader))


def get_all_units() -> Sequence[Target]:
    status = juju_status(json=True)
    # sub charms don't have units
    units = list(
        chain(*(app.get("units", ()) for app in status["applications"].values()))
    )
    return tuple(map(Target.from_name, units))


def parse_targets(targets: str = None) -> Sequence[Target]:
    if not targets:
        return get_all_units()

    all_units = None  # cache of all units according to juju status

    targets_ = targets.split(";")
    out = set()
    for target in targets_:
        if "/" in target:
            out.add(Target.from_name(target))
        else:
            if not all_units:
                all_units = get_all_units()
            # target is an app name: we need to gather all units of that app
            out.update((u for u in all_units if u.app == target))
    return tuple(out)


class LEVELS(enum.Enum):
    DEBUG = "DEBUG"
    TRACE = "TRACE"
    INFO = "INFO"
    ERROR = "ERROR"


@dataclass
class EventLogMsg:
    type = "emitted"

    pod_name: str
    timestamp: str
    loglevel: str
    unit: str
    event: str
    mocked: bool

    # we don't have any use for these, and they're only present if this event
    # has been (re)emitted/deferred during a relation hook call.
    endpoint: str = ""
    endpoint_id: str = ""

    # whether this event is an operator event (charm calling itself)
    operator_event: bool = False


@dataclass
class EventDeferredLogMsg(EventLogMsg):
    type = "deferred"
    event_cls: str = ""
    charm_name: str = ""
    n: str = ""


@dataclass
class EventReemittedLogMsg(EventDeferredLogMsg):
    type = "reemitted"


@dataclass
class RawTable:
    msgs: List[EventLogMsg] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    deferrals: List[Optional[str]] = field(default_factory=list)
    ns: List[str] = field(default_factory=list)
    n_colors: Dict[str, str] = field(default_factory=dict)
    currently_deferred: List[EventDeferredLogMsg] = field(default_factory=list)

    def get_color(self, n: str) -> str:
        return self.n_colors.get(n, _default_n_color)

    def add(self, msg: Union[EventLogMsg]):
        self.msgs.insert(0, msg)
        self.events.insert(0, msg.event)
        self.deferrals.insert(0, None)
        n = getattr(msg, "n", None)
        self.ns.insert(0, n)
        if n and n not in self.n_colors:
            self.n_colors[n] = _random_color()

    def add_blank_row(self):
        self.msgs.insert(0, None)
        self.ns.insert(0, None)
        self.events.insert(0, None)
        self.deferrals.insert(0, None)


_event_colors = {
    "update_status": Color.from_rgb(50, 50, 50),
    "collect_metrics": Color.from_rgb(50, 50, 50),
    "leader_elected": Color.from_rgb(26, 184, 68),
    "leader_settings_changed": Color.from_rgb(26, 184, 68),
    "_relation_created": Color.from_rgb(184, 26, 250),
    "_relation_joined": Color.from_rgb(184, 26, 200),
    "_relation_changed": Color.from_rgb(184, 26, 150),
    "_relation_departed": Color.from_rgb(184, 70, 100),
    "_relation_broken": Color.from_rgb(184, 80, 50),
    "_storage_attached": Color.from_rgb(184, 139, 26),
    "_storage_detaching": Color.from_rgb(184, 139, 26),
    "stop": Color.from_rgb(184, 26, 71),
    "remove": Color.from_rgb(171, 81, 21),
    "start": Color.from_rgb(20, 147, 186),
    "install": Color.from_rgb(49, 183, 224),
    "-pebble-ready": Color.from_rgb(212, 224, 40),
}

_default_event_color = Color.from_rgb(255, 255, 255)
_default_n_color = Color.from_rgb(255, 255, 255)
_tstamp_color = Color.from_rgb(255, 160, 120)
_operator_event_color = Color.from_rgb(252, 115, 3)
_deferral_colors = {
    "deferred": "red",
    "reemitted": "green",
    "bounced": Color.from_rgb(252, 115, 3),
}


def _random_color():
    r = random.randint(0, 255)
    g = random.randint(0, 255)
    b = random.randint(0, 255)
    return Color.from_rgb(r, g, b)


class Processor:
    # FIXME: why does sometime event/relation_event work, and sometimes
    #  uniter_event does? OF Version?

    def __init__(
        self,
        targets: Iterable[Target],
        add_new_targets: bool = True,
        history_length: int = 10,
        show_ns: bool = True,
        color: _Color = "auto",
        show_defer: bool = False,
        event_filter_re: re.Pattern = None,
    ):
        self.targets = list(targets)
        self.add_new_targets = add_new_targets
        self.history_length = history_length

        if color == "no":
            color = None

        self.console = console = Console(color_system=color)
        self.event_filter_re = event_filter_re
        self._raw_tables: Dict[str, RawTable] = {
            target.unit_name: RawTable() for target in targets
        }
        self._timestamps = []

        self._show_ns = show_ns and show_defer
        self._show_defer = show_defer

        self.evt_count = Counter()
        self._lanes = {}
        self.tracking: Dict[str, List[EventLogMsg]] = {
            tgt.unit_name: [] for tgt in targets
        }

        # used to check for duplicate log messages (juju bug?)
        self._duplicate_cache = set()

        self._has_just_emitted = False
        self.live = live = Live(console=console)
        live.start()

        self._warned_about_orphans = False

        base_pattern = "^(?P<pod_name>\S+): (?P<timestamp>\S+(\s*\S+)?) (?P<loglevel>\S+) unit\.(?P<unit>\S+)\.juju-log "
        base_relation_pattern = (
            base_pattern + "(?P<endpoint>\S+):(?P<endpoint_id>\S+): "
        )

        operator_event_suffix = "Charm called itself via hooks/(?P<event>\S+)\."
        self.operator_event = re.compile(base_pattern + operator_event_suffix)

        event_suffix = "Emitting Juju event (?P<event>\S+)\."
        self.event = re.compile(base_pattern + event_suffix)
        self.event_from_relation = re.compile(base_relation_pattern + event_suffix)

        self.uniter_event = re.compile(
            '^unit-(?P<unit_name>\S+)-(?P<unit_number>\d+): (?P<timestamp>\S+( \S+)?) (?P<loglevel>\S+) juju\.worker\.uniter\.operation ran "(?P<event>\S+)" hook \(via hook dispatching script: dispatch\)'
        )

        event_repr = "<(?P<event_cls>\S+) via (?P<charm_name>\S+)/on/(?P<event>\S+)\[(?P<n>\d+)\]>\."
        defer_suffix = "Deferring " + event_repr
        self.event_deferred = re.compile(base_pattern + defer_suffix)
        self.event_deferred_from_relation = re.compile(
            base_relation_pattern + defer_suffix
        )

        reemitted_suffix = "Re-emitting " + event_repr
        self.event_reemitted = re.compile(base_pattern + reemitted_suffix)
        self.event_reemitted_from_relation = re.compile(
            base_relation_pattern + reemitted_suffix
        )
        self._rendered = False

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

    def _emit(self, evt: EventLogMsg):
        if self.add_new_targets and evt.unit not in self.tracking:
            self._add_new_target(evt)

        if evt.unit in self.tracking:  # target tracked
            self.evt_count[evt.unit] += 1
            self.tracking[evt.unit].insert(0, evt)
            self._raw_tables[evt.unit].add(evt)
            logger.debug(f"tracking {evt.event}")

    def _defer(self, deferred: EventDeferredLogMsg):
        # find the original message we're deferring
        raw_table = self._raw_tables[deferred.unit]

        if deferred.event not in raw_table.events:
            # we're deferring an event we've not seen before: logging just started.
            # so we pretend we've seen it, to be safe.
            mock_event = EventLogMsg(
                pod_name=deferred.pod_name,
                timestamp="",
                loglevel=deferred.loglevel,
                unit=deferred.unit,
                event=deferred.event,
                mocked=True,
            )
            self._emit(mock_event)
            logger.debug(
                f"Mocking {mock_event}: we're deferring it but "
                f"we've not seen it before."
            )

        currently_deferred_ns = {d.n for d in raw_table.currently_deferred}
        is_already_deferred = deferred.n in currently_deferred_ns

        if not is_already_deferred:
            logger.debug(f"deferring {deferred}")
            raw_table.currently_deferred.append(deferred)

        else:
            # not the first time we defer this boy
            logger.debug(f"re-deferring {deferred.event}")

    def _reemit(self, reemitted: EventReemittedLogMsg):
        # search deferred queue first to last
        unit = reemitted.unit
        raw_table = self._raw_tables[unit]

        deferred = None
        for _deferred in list(raw_table.currently_deferred):
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
            # this is a reemittal log, so we've _emitted it once, which has stored this n into raw_table.ns.
            # this will make update_defers believe that we've already deferred this event, which we haven't.
            self._timestamps.insert(0, deferred.timestamp + "*")

            self._defer(deferred)
            logger.debug(
                f"mocking {deferred}: we're reemitting it but "
                f"we've not seen it before."
            )

            # the 'happy path' would have been: _emit, _defer, _emit, _reemit,
            # so we need to _emit it once more.
            self._emit(reemitted)

        raw_table.currently_deferred.remove(deferred)

        # start tracking the reemitted event.
        self.tracking[unit].append(reemitted)
        logger.debug(f"reemitted {reemitted.event}")

    def _uniform_event(self, event: str):
        return event.replace("-", "_")

    def _match_filter(self, event_name: str) -> bool:
        """If the user specified an event name regex filter, run it."""
        if not self.event_filter_re:
            return True
        match = self.event_filter_re.match(event_name)
        return bool(match)

    def _match_event_deferred(self, log: str) -> Optional[EventDeferredLogMsg]:
        if "Deferring" not in log:
            return
        match = self.event_deferred.match(
            log
        ) or self.event_deferred_from_relation.match(log)
        if match:
            params = match.groupdict()
            params["event"] = event = self._uniform_event(params["event"])
            if not self._match_filter(event):
                return
            return EventDeferredLogMsg(**params, mocked=False)

    def _match_event_reemitted(self, log: str) -> Optional[EventReemittedLogMsg]:
        if "Re-emitting" not in log:
            return
        match = self.event_reemitted.match(
            log
        ) or self.event_reemitted_from_relation.match(log)
        if match:
            params = match.groupdict()
            params["event"] = event = self._uniform_event(params["event"])
            if not self._match_filter(event):
                return
            return EventReemittedLogMsg(**params, mocked=False)

    def _match_event_emitted(self, log: str) -> Optional[EventLogMsg]:
        if match := self.event.match(log) or self.event_from_relation.match(log):
            params = match.groupdict()

        elif match := self.operator_event.match(log):
            params = match.groupdict()
            params["operator_event"] = True

        # TODO: in juju2, sometimes we need to match events in a
        #  different way: understand why.
        elif JUJU_VERSION < "3.0" and (match := self.uniter_event.match(log)):
            params = match.groupdict()
            unit = params.pop("unit_name")
            n = params.pop("unit_number")
            params["pod_name"] = f"{unit}-{n}"
            params["unit"] = f"{unit}/{n}"

        else:
            return

        params["event"] = event = self._uniform_event(params["event"])
        if not self._match_filter(event):
            return

        # Ignore the unused date parameter
        if "date" in params:
            del params["date"]
        return EventLogMsg(**params, mocked=False)

    def _add_new_target(self, msg: EventLogMsg):
        logger.info(f"adding new unit {msg.unit}")
        new_target = Target.from_name(msg.unit)

        self.tracking[msg.unit] = []
        self.targets.append(new_target)
        self._raw_tables[new_target.unit_name] = RawTable()

    def _check_duplicate(self, msg: EventLogMsg):
        hsh = hash((msg.unit, msg.timestamp, msg.event))
        if hsh in self._duplicate_cache:
            return True
        self._duplicate_cache.add(hsh)

    def process(self, log: str) -> Optional[EventLogMsg]:
        """process a log line"""
        if msg := self._match_event_emitted(log):
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

        if self._check_duplicate(msg):
            logger.debug(f"{msg.timestamp}: {msg.event} is a duplicate. skipping...")
            return

        if mode in {"emit", "reemit"}:
            self._emit(msg)

        if not self._is_tracking(msg):
            return

        if mode == "defer":
            self._defer(msg)
        elif mode == "reemit":
            self._reemit(msg)

        if mode in {"reemit", "emit"}:
            self._timestamps.insert(0, msg.timestamp)
            # we need to update all *other* tables as well, to insert a
            # blank line where this event would appear
            self._extend_other_tables(msg)
            self._crop()

        if self._show_defer and self._is_tracking(msg):
            logger.info(f"updating defer for {msg.event}")
            self.update_defers(msg)

        self.render()
        return msg

    def _extend_other_tables(self, msg: EventLogMsg):
        raw_tables = self._raw_tables
        for unit, raw_table in raw_tables.items():
            if unit == msg.unit:
                # this raw_table: skip
                continue

            raw_table.add_blank_row()

    def _get_event_color(self, msg: EventLogMsg) -> Color:
        event = msg.event
        if msg.operator_event:
            return _operator_event_color
        if event in _event_colors:
            return _event_colors.get(event, _default_event_color)
        else:
            for _e in _event_colors:
                if event.endswith(_e):
                    return _event_colors[_e]
        return _default_event_color

    def render(self, _debug=False) -> Align:
        # we're rendering the table and flipping it every time. more efficient
        # to add new rows to the top and keep old ones, but how do we know if
        # deferral lines have changed?
        self._rendered = True
        table = Table(show_footer=False, expand=True)
        table.add_column(header="timestamp", style="")
        unit_grids = []
        n_cols = 1

        ns_shown = self._show_ns
        dfr_shown = self._show_defer
        if ns_shown:
            n_cols += 1
        if dfr_shown:
            n_cols += 1

        targets = self.targets
        raw_tables = self._raw_tables
        for target in targets:
            tgt_grid = Table.grid(*(("",) * n_cols), expand=True, padding=(0, 1, 0, 1))
            raw_table = raw_tables[target.unit_name]
            for i, (msg, event, n) in enumerate(
                zip(raw_table.msgs, raw_table.events, raw_table.ns)
            ):
                rndr = (
                    Text(event, style=Style(color=self._get_event_color(msg)))
                    if event
                    else ""
                )
                row = [rndr]

                if self._show_defer:
                    deferral_status = raw_table.deferrals[i] or "null"
                    deferral_symbol = self._deferral_status_to_symbol[deferral_status]
                    style = (
                        Style(color=_deferral_colors[deferral_status])
                        if deferral_status != "null"
                        else ""
                    )
                    deferral_rndr = Text(deferral_symbol, style=style)
                    row.append(deferral_rndr)

                if self._show_ns:
                    n_rndr = (
                        Text(n, style=Style(color=raw_table.get_color(n))) if n else ""
                    )
                    row.insert(0, n_rndr)

                tgt_grid.add_row(*row)

            table.add_column(header=target.unit_name, style="")
            unit_grids.append(tgt_grid)

        _timestamps_grid = Table.grid("", expand=True)
        for tstamp in self._timestamps:
            _timestamps_grid.add_row(tstamp, style=Style(color=_tstamp_color))

        table.add_row(_timestamps_grid, *unit_grids)
        if _debug:
            self.console.print(table)
            return table

        table_centered = Align.center(table)
        self.live.update(table_centered)

        if not self.live.is_started:
            logger.info("live started by render")
            self.live.start()

        return table_centered

    def _is_tracking(self, msg):
        return msg.unit in self.tracking

    # todo: should we have a "console compatibility mode" using ascii here?
    _bounce = "●"  # "●•⭘" not all alternatives supported on all consoles
    _close = "❮"
    _open = "❯"
    _null = ""

    _deferral_status_to_symbol = {
        "null": _null,
        "deferred": _open,
        "reemitted": _close,
        "bounced": _bounce,
    }

    def update_defers(self, msg: EventLogMsg):
        # all the events we presently know to be deferred
        unit = msg.unit
        raw_table = self._raw_tables[unit]

        if msg.type == "deferred":
            # if we're deferring, we're not adding a new logline, so we can
            # start searching at 0
            try:
                previous_msg_idx = raw_table.ns.index(msg.n)
            except ValueError:
                # are we deferring the last event?
                previous_msg = raw_table.msgs[0]
                if (
                    previous_msg
                    and previous_msg.event == msg.event
                    and previous_msg.unit == msg.unit
                ):
                    previous_msg_idx = 0
                else:
                    logger.debug(f"Deferring event {msg.n} which is out of scope.")
                    return

            new_state = "deferred"
            if raw_table.deferrals[previous_msg_idx] == "deferred":
                new_state = "bounced"
            raw_table.deferrals[previous_msg_idx] = new_state
            raw_table.ns[previous_msg_idx] = msg.n

        elif msg.type == "reemitted":
            last = None
            for i, n in enumerate(raw_table.ns):
                if n == msg.n:
                    raw_table.deferrals[i] = "bounced"
                    last = i

            if last is not None:
                raw_table.deferrals[last] = "deferred"

            raw_table.deferrals[0] = "reemitted"  # this event!

        else:
            return

    def _crop(self):
        # crop all:
        if len(self._timestamps) <= self.history_length:
            # nothing to do.
            return

        logger.info("cropping table")
        lst: List
        for lst in (
            self._timestamps,
            *(raw.deferrals for raw in self._raw_tables.values()),
            *(raw.events for raw in self._raw_tables.values()),
            *(raw.ns for raw in self._raw_tables.values()),
        ):
            while len(lst) > self.history_length:
                lst.pop()  # pop first

    def quit(self):
        """Print a goodbye message."""
        if not self._rendered:
            self.live.update("No events caught.", refresh=True)
            return

        table = cast(Table, self.render().renderable)
        table.rows[-1].end_section = True
        evt_count = self.evt_count

        nevents = []
        tgt_names = []
        for tgt in self.targets:
            nevents.append(str(evt_count[tgt.unit_name]))
            text = Text(tgt.unit_name, style="bold")
            tgt_names.append(text)
        table.add_row(Text("The end.", style="bold blue"), *tgt_names, end_section=True)

        table.add_row(Text("events emitted", style="green"), *nevents)

        if self._show_defer:
            cdefevents = []
            for tgt in self.targets:
                raw_table = self._raw_tables[tgt.unit_name]
                cdefevents.append(str(len(raw_table.currently_deferred)))
            table.add_row(Text("currently deferred events", style="green"), *cdefevents)

        table_centered = Align.center(table)
        self.live.update(table_centered)
        self.live.refresh()
        self.live.stop()

    def update_if_empty(self):
        if self._rendered:
            return
        self.live.update("Listening for events...", refresh=True)


def _get_debug_log(cmd):
    return JPopen(cmd, stdin=PIPE, stdout=PIPE, stderr=STDOUT)


def tail_events(
    targets: str = typer.Argument(
        None,
        help="Semicolon-separated list of targets to follow. "
        "Example: 'foo/0;foo/1;bar/2'. By default, it will follow all "
        "available targets.",
    ),
    add_new_targets: bool = typer.Option(
        True,
        "--add",
        "-a",
        help="Keep adding new units as they appear. Can't be used "
        "in combination with nonempty targets arg. ",
    ),
    level: LEVELS = "DEBUG",
    replay: bool = typer.Option(
        False, "--replay", "-r", help="Keep listening from beginning of time."
    ),
    dry_run: bool = typer.Option(
        False, help="Only print what you would have done, exit."
    ),
    framerate: float = typer.Option(0.5, help="Framerate cap."),
    length: int = typer.Option(
        10, "-l", "--length", help="Maximum history length to show."
    ),
    show_defer: bool = typer.Option(
        False, "-d", "--show-defer", help="Visualize the defer graph."
    ),
    show_ns: bool = typer.Option(
        False,
        "-n",
        "--show-defer-id",
        help="Prefix deferred events with their deferral ID. "
        "Only applicable if show_defer=True.",
    ),
    watch: bool = typer.Option(True, "--watch", help="Keep listening."),
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
):
    """Pretty-print a table with the events that are fired on juju units
    in the current model.
    Examples: jhack tail mongo-k8s/2  |  jhack tail -d
    """
    return _tail_events(
        targets=targets,
        add_new_targets=add_new_targets,
        level=level,
        replay=replay,
        dry_run=dry_run,
        framerate=framerate,
        length=length,
        show_defer=show_defer,
        show_ns=show_ns,
        watch=watch,
        color=color,
        files=file,
        event_filter=filter_events,
    )


def _tail_events(
    targets: str = None,
    add_new_targets: bool = True,
    level: LEVELS = "DEBUG",
    replay: bool = True,  # listen from beginning of time?
    dry_run: bool = False,
    framerate: float = 0.5,
    length: int = 10,
    show_defer: bool = False,
    show_ns: bool = False,
    watch: bool = True,
    color: str = "auto",
    files: List[Union[str, Path]] = None,
    event_filter: str = None,
    # for script use only
    _on_event: Callable[[EventLogMsg], None] = None,
):
    if isinstance(level, str):
        level = getattr(LEVELS, level.upper())

    if not isinstance(level, LEVELS):
        raise ValueError(level)

    track_events = True
    if level not in {LEVELS.DEBUG, LEVELS.TRACE}:
        logger.debug(f"we won't be able to track events with level={level}")
        track_events = False

    if targets and add_new_targets:
        logger.debug("targets provided; overruling add_new_targets param.")
        add_new_targets = False

    # if we pass files, we dont't grab targets from the env, we simply read them from the file
    targets = parse_targets(targets) if not files else (targets or [])
    if not targets and not add_new_targets:
        logger.warning(
            "no targets passed and `add_new_targets`=False: you will not see much."
        )
        sys.exit(1)

    if files and replay:
        logger.debug(f"ignoring `replay` because files were provided")
        replay = False

    if files and watch:
        logger.debug(f"ignoring `watch` because files were provided")
        watch = False

    logger.debug("starting to read logs")
    cmd = (
        ["juju", "debug-log"]
        + (["--tail"] if watch else [])
        + (["--replay"] if replay else [])
        + ["--level", level.value]
    )

    if dry_run:
        print(" ".join(cmd))
        return

    event_filter_pattern = re.compile(event_filter) if event_filter else None

    processor = Processor(
        targets,
        add_new_targets,
        history_length=length,
        show_ns=show_ns,
        color=color,
        show_defer=show_defer,
        event_filter_re=event_filter_pattern,
    )

    try:
        # when we're in replay mode we're catching up with the replayed logs
        # so we won't limit the framerate and just flush the output
        replay_mode = True

        if files:
            # handle input from files
            log_getter = DebugLogInterlacer(files)

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

                def next_line():
                    try:
                        return next(stdout)
                    except StopIteration:
                        return ""

            else:

                def next_line():
                    line = proc.stdout.readline()
                    return line

        while True:
            start = time.time()

            line = next_line()
            if not line:
                if not watch:
                    break

                if not files and proc.poll() is not None:
                    # process terminated FIXME: this shouldn't happen
                    # Checks only if we're watching a process
                    break

                replay_mode = False
                continue

            if line:
                msg = line.decode("utf-8").strip()
                captured = processor.process(msg)

                # notify listeners that an event has been processed.
                if _on_event and captured:
                    _on_event(captured)

            if not replay_mode and (elapsed := time.time() - start) < framerate:
                logger.debug(f"sleeping {framerate - elapsed}")
                time.sleep(framerate - elapsed)

            processor.update_if_empty()

    except KeyboardInterrupt:
        pass  # quit
    finally:
        processor.quit()

    return processor  # for testing


def _put(s: str, index: int, char: Union[str, Dict[str, str]], placeholder=" "):
    if isinstance(char, str):
        char = {None: char}

    if len(s) <= index:
        s += placeholder * (index - len(s)) + char[None]
        return s

    l = list(s)
    l[index] = char.get(l[index], char[None])
    return "".join(l)


if __name__ == "__main__":
    _tail_events(length=30, replay=True, show_defer=True, show_ns=True)
