import enum
import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from subprocess import PIPE, STDOUT
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Union,
    cast,
    Literal,
)

import parse
import typer
from rich.align import Align
from rich.color import Color
from rich.console import Console
from rich.live import Live
from rich.style import Style
from rich.table import Table
from rich.text import Text

from jhack.helpers import JPopen, juju_version
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
    cmd = JPopen(f"juju status".split(" "), stdout=PIPE)
    output = cmd.stdout.read().decode("utf-8")

    units = []
    units_section = False
    for line in output.split("\n"):
        if units_section and not line.strip():
            # empty line after units section: end of units section
            units_section = False
            break

        first_part, *_ = line.split(" ")
        if first_part == "Unit":
            units_section = True
            continue

        if units_section:
            target = Target.from_name(first_part)
            units.append(target)
    return tuple(units)


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
    events: List[str] = field(default_factory=list)
    deferrals: List[str] = field(default_factory=list)
    ns: List[str] = field(default_factory=list)
    n_colors: Dict[str, str] = field(default_factory=dict)
    currently_deferred: List[EventDeferredLogMsg] = field(default_factory=list)

    def get_color(self, n: str) -> str:
        return self.n_colors.get(n, _default_n_color)

    def add(self, msg: Union[EventLogMsg]):
        self.events.insert(0, msg.event)
        self.deferrals.insert(0, "  ")
        n = getattr(msg, "n", None)
        self.ns.insert(0, n)
        if n and n not in self.n_colors:
            self.n_colors[n] = _random_color()

    def add_blank_row(self):
        self.ns.insert(0, None)
        self.events.insert(0, None)
        self.deferrals.insert(0, "  ")


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
    ):
        self.targets = list(targets)
        self.add_new_targets = add_new_targets
        self.history_length = history_length

        if color == "no":
            color = None

        self.console = console = Console(color_system=color)
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

        self._has_just_emitted = False
        self.live = live = Live(console=console)
        live.start()

        self._warned_about_orphans = False

        base_pattern = "^(?P<pod_name>\S+): (?P<timestamp>\S+(\s*\S+)?) (?P<loglevel>\S+) unit\.(?P<unit>\S+)\.juju-log "
        base_relation_pattern = (
            base_pattern + "(?P<endpoint>\S+):(?P<endpoint_id>\S+): "
        )

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

        is_already_deferred = False

        for dfrd in raw_table.currently_deferred:
            if dfrd.n == deferred.n:
                # not the first time we defer this boy
                is_already_deferred = True
                return dfrd.msg

        if not is_already_deferred:
            logger.debug(f"deferring {deferred}")
            raw_table.currently_deferred.append(deferred)

        else:
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
            self.update_defers(deferred)

            # the 'happy path' would have been: _emit, _defer, _emit, _reemit,
            # so we need to _emit it once more.
            self._emit(reemitted)
            # free_lane = max(self._lanes.values() if self._lanes else [0]) + 1
            # self._cache_lane(reemitted.n, free_lane)

        raw_table.currently_deferred.remove(deferred)

        # start tracking the reemitted event.
        self.tracking[unit].append(reemitted)
        logger.debug(f"reemitted {reemitted.event}")

    def _uniform_event(self, event: str):
        return event.replace("-", "_")

    def _match_event_deferred(self, log: str) -> Optional[EventDeferredLogMsg]:
        if "Deferring" not in log:
            return
        match = self.event_deferred.match(
            log
        ) or self.event_deferred_from_relation.match(log)
        if match:
            params = match.groupdict()
            params["event"] = self._uniform_event(params["event"])
            return EventDeferredLogMsg(**params, mocked=False)

    def _match_event_reemitted(self, log: str) -> Optional[EventReemittedLogMsg]:
        if "Re-emitting" not in log:
            return
        match = self.event_reemitted.match(
            log
        ) or self.event_reemitted_from_relation.match(log)
        if match:
            params = match.groupdict()
            params["event"] = self._uniform_event(params["event"])
            return EventReemittedLogMsg(**params, mocked=False)

    def _match_event_emitted(self, log: str) -> Optional[EventLogMsg]:
        if match := self.event.match(log) or self.event_from_relation.match(log):
            params = match.groupdict()

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

        # uniform event names
        params["event"] = params["event"].replace("-", "_")

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

    def process(self, log: str) -> Optional[EventLogMsg]:
        """process a log line"""
        if msg := self._match_event_emitted(log):
            mode = "emit"
            self._emit(msg)
        elif self._show_defer:
            if msg := self._match_event_deferred(log):
                mode = "defer"
            elif msg := self._match_event_reemitted(log):
                self._emit(msg)
                mode = "reemit"
            else:
                return
        else:
            return

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
            tail = ""
            for evt in raw_table.currently_deferred:
                tail = _put(
                    tail, self._get_lane(evt.n), self._vline, self._nothing_to_report
                )
                tail = self._dpad + tail[2:]

            raw_table.deferrals[0] = tail

    def _get_event_color(self, event: str) -> Color:
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
        ns_shown = self._show_ns
        n_cols = 3 if ns_shown else 2

        targets = self.targets
        raw_tables = self._raw_tables
        for target in targets:
            tgt_grid = Table.grid(*(("",) * n_cols), expand=True, padding=(0, 1, 0, 1))
            raw_table = raw_tables[target.unit_name]
            for event, deferral, n in zip(
                raw_table.events, raw_table.deferrals, raw_table.ns
            ):
                rndr = (
                    Text(event, style=Style(color=self._get_event_color(event)))
                    if event
                    else ""
                )
                if ns_shown:
                    n_rndr = (
                        Text(n, style=Style(color=raw_table.get_color(n))) if n else ""
                    )
                    tgt_grid.add_row(n_rndr, rndr, deferral)
                else:
                    tgt_grid.add_row(rndr, deferral)

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

    _pad = " "
    _dpad = _pad * 2
    _nothing_to_report = "."
    _vline = "│"
    _cross = "┼"
    _lup = "┘"
    _lupdown = "┤"
    _ldown = "┐"
    _hline = "─"

    # todo: should we have a "console compatibility mode" using ascii here?
    _bounce = "●"  # "●•⭘" not all alternatives supported on all consoles
    _close = "❮"
    _open = "❯"

    def update_defers(self, msg: EventLogMsg):
        # all the events we presently know to be deferred
        unit = msg.unit
        raw_table = self._raw_tables[unit]

        previous_msg_idx = None
        deferring = msg.type == "deferred"
        reemitting = msg.type == "reemitted"
        if deferring or reemitting:
            if deferring:
                # if we're deferring, we're not adding a new logline so we can
                # start searching at 0
                offset = 0
            else:
                # if we're reemitting, we skip the first log because we want to
                # check the previous time this event was emitted or bounced, and
                # we just added a logline for this event
                offset = 1

            try:
                previous_msg_idx = raw_table.ns[offset:].index(msg.n) + offset
            except ValueError:
                logger.debug(f"n {msg.n} is new.")
                pass

        if deferring:
            assert isinstance(msg, EventDeferredLogMsg)  # type guard
            # we did not find (in scope) a previous logline emitting
            # this event by number; let's search by name.
            if msg.mocked and previous_msg_idx is None:
                # we are mocking an event whose first emission could be out of scope
                for idx, (evt, n) in enumerate(zip(raw_table.events, raw_table.ns)):
                    if evt == msg.event and n is None:
                        previous_msg_idx = idx
                        break

                if previous_msg_idx is None:
                    logger.debug(
                        f"Mocked event {msg.event}({msg.n}) is out of scope, and "
                        f"no not-yet-numbered companion can be "
                        f"found in the table."
                    )
                    # we need to find an empty lane for this new message.
                    busy = set(self._lanes.values())
                    free = None
                    for lane in range(max(busy)):
                        if lane not in busy:
                            free = lane
                            break
                    if free is None:
                        free = max(busy) + 1
                    self._cache_lane(msg.n, free)
                    return

            if msg.mocked or previous_msg_idx is None:
                if previous_msg_idx is None:
                    logger.debug(
                        "Deferring an event which we don't know it when was "
                        f"emitted first. Attempting to guess by indexing the "
                        f"event name ({msg.event}) in the raw table."
                    )
                    try:
                        previous_msg_idx = raw_table.events.index(msg.event)
                        logger.debug(
                            f"according to raw table, "
                            f"our index is {previous_msg_idx}"
                        )
                    except ValueError:
                        # should really not happen; it may mean that earlier logs
                        # are unavailable (user only got to DEBUG recently).
                        logger.error(f"{msg.event} not found in raw table")
                        previous_msg_idx = 0

                if (known_n := raw_table.ns[previous_msg_idx]) is not None:
                    if not known_n == msg.n:
                        logger.error(
                            f"The original log at line {previous_msg_idx} "
                            f"({raw_table.events[previous_msg_idx]}) has n = {known_n}, "
                            f"but the message we just parsed ({msg.event}) has n = {msg.n}"
                        )

                # store it
                raw_table.ns[previous_msg_idx] = msg.n
                # if previous_msg_idx == 0, that's the case in
                # which we're deferring the last event we emitted.
                # otherwise we're deferring something we've re-emitted.
                original_cell = raw_table.deferrals[previous_msg_idx]

                if previous_msg_idx == 0:
                    # we're deferring a just-emitted event.
                    # This means we have to generate the full cell from scratch.
                    new_cell = self._open + self._hline
                    for dfrd in raw_table.currently_deferred:
                        if dfrd is msg:
                            continue

                        # iterate through the busy lanes, put a cross there,
                        # leave a hline otherwise
                        lane = self._get_lane(dfrd.n)
                        if not lane:
                            raise ValueError(f"lane not cached for {dfrd}")

                        new_cell = _put(new_cell, lane, self._cross, self._hline)

                    # at the end:
                    new_cell += self._lup

                else:
                    # turn all vlines we meet into crosses, add a lup
                    new_cell = (
                        original_cell.replace(self._vline, self._cross) + self._lup
                    )

                raw_table.deferrals[previous_msg_idx] = new_cell
                lane = new_cell.index(self._lup)

            else:
                # not the first time we defer you, boy
                original_cell = raw_table.deferrals[previous_msg_idx]
                if self._close + self._hline not in original_cell:
                    raise ValueError(
                        f"Expected closure not found in original cell: "
                        f"{original_cell}; something wrong processing {msg}"
                    )

                new_cell = (
                    original_cell.replace(
                        self._close + self._hline, self._pad + self._bounce
                    )
                    .replace(self._ldown, self._lupdown)
                    .replace(self._vline, self._cross)
                )

                for _msg in raw_table.currently_deferred:
                    if _msg is msg:
                        continue
                    busy_lane = self._get_lane(_msg.n)
                    new_cell = _put(
                        new_cell, busy_lane, self._cross, self._nothing_to_report
                    )

                raw_table.deferrals[previous_msg_idx] = new_cell
                try:
                    lane = new_cell.index(self._lupdown)
                except ValueError:
                    logger.error(
                        f"Failed looking up lane by indexing lupdown in {new_cell}"
                        f"something wrong with {raw_table}"
                    )
                    raise

            self._cache_lane(msg.n, lane)

        elif reemitting:
            assert isinstance(msg, EventReemittedLogMsg)  # type guard

            if previous_msg_idx is None:
                # message must have been cropped away
                logger.debug(
                    f"unable to grab fetch previous reemit, "
                    f"msg {msg.n} must be out of scope"
                )

            lane = None
            if previous_msg_idx is not None:
                original_reemittal_cell = raw_table.deferrals[previous_msg_idx]
                lane = None
                for sym in {self._lupdown, self._lup}:
                    if sym in original_reemittal_cell:
                        lane = original_reemittal_cell.index(sym)
                        break  # found

            if lane is None:
                lane = self._get_lane(msg.n)
                if lane is None:
                    raise RuntimeError(
                        f"lane not cached for {msg.n}, and "
                        f"message is out of scope. "
                        f"Unable to proceed."
                    )
            self._cache_lane(msg.n, lane)

            # now we look at the newly added cell and add a closure statement.
            current_cell = raw_table.deferrals[0]
            current_cell_new = current_cell.replace(
                self._dpad, self._close + self._hline
            )

            closed_cell = _put(current_cell_new, lane, self._ldown, self._hline)
            final_cell = list(closed_cell)
            for ln in range(lane):
                if final_cell[ln] == self._vline:
                    final_cell[ln] = self._cross
            raw_table.deferrals[0] = "".join(final_cell)

            if previous_msg_idx is not None:
                # we clean up the previous line:
                # there could be a vline because of the tail present back then,
                # we need to replace it with cross.
                # reopen previous reemittal if it's closed
                previous_reemittal_cell = raw_table.deferrals[previous_msg_idx]
                for idx in range(2, lane):
                    previous_reemittal_cell = _put(
                        previous_reemittal_cell,
                        idx,
                        {
                            self._cross: self._cross,
                            self._vline: self._cross,
                            None: self._hline,
                        },
                        self._hline,
                    )

                raw_table.deferrals[previous_msg_idx] = previous_reemittal_cell
                rng = range(1, previous_msg_idx)
            else:
                # until the end of the visible table
                rng = range(1, len(raw_table.deferrals))

            for ln in rng:
                raw_table.deferrals[ln] = _put(
                    raw_table.deferrals[ln],
                    lane,
                    {
                        None: self._vline,
                        self._hline: self._cross,
                        self._ldown: self._lupdown,
                    },
                    self._nothing_to_report,
                )

        else:
            if self._has_just_emitted:
                # we just emitted twice, without deferring or reemitting anything in between,
                # that means we can do some cleanup.
                while raw_table.currently_deferred:
                    dfrd = raw_table.currently_deferred.pop()
                    logger.debug(
                        f"removed spurious deferred event {dfrd.event}({dfrd.n})"
                    )

            else:
                tail = raw_table.deferrals[0]
                for cdef in raw_table.currently_deferred:
                    lane = self._get_lane(cdef.n)
                    tail = _put(tail, lane, self._vline, self._nothing_to_report)
                    tail = self._dpad + tail[2:]
                raw_table.deferrals[0] = tail

            self._has_just_emitted = True
            return

        self._has_just_emitted = False

    def _get_lane(self, n: str):
        # todo: check that N is unique across units, else this will get messy
        return self._lanes.get(n)

    def _cache_lane(self, n: str, lane: int):
        self._lanes[n] = lane

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
        "['auto', 'standard', '256', 'truecolor', 'windows']"
        "no: disable colors entirely.",
    ),
    file: Optional[List[str]] = typer.Option(
        [],
        help="Text file with logs from `juju debug-log`.  Can be used in place of streaming "
        "logs directly from juju, and can be set multiple times to read from multiple "
        "files.  File must be exported from juju using `juju debug-log --date` to allow"
        " for proper sorting",
    ),
):
    """Pretty-print a table with the events that are fired on juju units
    in the current model.
    Examples:
        >>> jhack tail mongo-k8s/2
        >>> jhack tail -d
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
    color: bool = True,
    files: List[str] = None,
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

    targets = parse_targets(targets)

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

    processor = Processor(
        targets,
        add_new_targets,
        history_length=length,
        show_ns=show_ns,
        color=color,
        show_defer=show_defer,
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
    _tail_events(files=["/home/pietro/jdl.txt"])
