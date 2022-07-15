import enum
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, Field, field
from subprocess import Popen, PIPE, STDOUT
from typing import Sequence, Optional, Iterable, List, Dict, Tuple, Union

import parse
import typer
from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.table import Table

from jhack.config import JUJU_COMMAND

logger = logging.getLogger(__file__)


@dataclass
class Target:
    app: str
    unit: int
    leader: bool = False

    @staticmethod
    def from_name(name: str):
        app, unit_ = name.split('/')
        leader = unit_.endswith('*')
        unit = unit_.strip('*')
        return Target(app, unit, leader=leader)

    @property
    def unit_name(self):
        return f"{self.app}/{self.unit}"

    def __hash__(self):
        return hash((self.app, self.unit, self.leader))


def get_all_units() -> Sequence[Target]:
    cmd = Popen(f"{JUJU_COMMAND} status".split(' '), stdout=PIPE)
    output = cmd.stdout.read().decode('utf-8')

    units = []
    units_section = False
    for line in output.split('\n'):
        if units_section and not line.strip():
            # empty line after units section: end of units section
            units_section = False
            break

        first_part, *_ = line.split(' ')
        if first_part == 'Unit':
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

    targets_ = targets.split(';')
    out = set()
    for target in targets_:
        if '/' in target:
            out.add(Target.from_name(target))
        else:
            if not all_units:
                all_units = get_all_units()
            # target is an app name: we need to gather all units of that app
            out.update((u for u in all_units if u.app == target))
    return tuple(out)


class LEVELS(enum.Enum):
    DEBUG = 'DEBUG'
    TRACE = 'TRACE'
    INFO = 'INFO'
    ERROR = 'ERROR'


@dataclass
class EventLogMsg:
    pod_name: str
    timestamp: str
    loglevel: str
    unit: str
    event: str
    # relation: str = None
    # relation_id: str = None


@dataclass
class EventDeferredLogMsg(EventLogMsg):
    event_cls: str
    charm_name: str
    n: str

    # the original event we're deferring or re-deferring
    msg: EventLogMsg = None


@dataclass
class EventReemittedLogMsg(EventLogMsg):
    event_cls: str
    charm_name: str
    n: str

    deferred: EventDeferredLogMsg = None


@dataclass
class RawTable:
    events: List[str] = field(default_factory=list)
    deferrals: List[str] = field(default_factory=list)
    ns: List[str] = field(default_factory=list)
    currently_deferred: List[EventLogMsg] = field(default_factory=list)

    def add(self, msg: Union[EventLogMsg]):
        self.events.insert(0, msg.event)
        self.deferrals.insert(0, '  ')
        self.ns.insert(0, getattr(msg, 'n', None))


class Processor:
    # FIXME: why does sometime event/relation_event work, and sometimes
    #  uniter_event does? OF Version?
    event = parse.compile(
        "{pod_name}: {timestamp} {loglevel} unit.{unit}.juju-log Emitting Juju event {event}.")
    relation_event = parse.compile(
        "{pod_name}: {timestamp} {loglevel} unit.{unit}.juju-log {relation}:{relation_id}: Emitting Juju event {event}.")
    uniter_event = parse.compile(
        '{pod_name}: {timestamp} {loglevel} juju.worker.uniter.operation ran "{event}" hook (via hook dispatching script: dispatch)')
    # Deferring <UpdateStatusEvent via TraefikIngressCharm/on/bork[247]>.
    event_deferred = parse.compile(
        '{pod_name}: {timestamp} {loglevel} unit.{unit}.juju-log Deferring <{event_cls} via {charm_name}/on/{event}[{n}]>.')
    # unit-traefik-k8s-0: 12:16:47 DEBUG unit.traefik-k8s/0.juju-log Re-emitting <UpdateStatusEvent via TraefikIngressCharm/on/update_status[130]>.
    event_reemitted = parse.compile(
        '{pod_name}: {timestamp} {loglevel} unit.{unit}.juju-log Re-emitting <{event_cls} via {charm_name}/on/{event}[{n}]>.'
    )

    def __init__(self, targets: Iterable[Target],
                 add_new_targets: bool = True,
                 history_length: int = 10,
                 show_ns: bool = True,
                 show_defer: bool = False):
        self.targets = list(targets)
        self.add_new_targets = add_new_targets
        self.history_length = history_length
        self.console = console = Console()
        self._raw_tables: Dict[str, RawTable] = {
            target.unit_name: RawTable() for target in targets}
        self._timestamps = []

        self._show_ns = show_ns and show_defer
        self._show_defer = show_defer
        self.live = Live(None, console=console,
                         screen=False, refresh_per_second=20)

        self.evt_count = 0
        self._lanes = {}
        self.tracking: Dict[str, List[EventLogMsg]] = {tgt.unit_name: [] for tgt
                                                       in targets}
        self.render()

    def _track(self, evt: EventLogMsg):
        if self.add_new_targets and evt.unit not in self.tracking:
            self._add_new_target(evt)

        if evt.unit in self.tracking:  # target tracked
            self.evt_count += 1
            self.tracking[evt.unit].insert(0, evt)
            self._raw_tables[evt.unit].add(evt)
            logger.debug(f"tracking {evt.event}")

    def _defer(self, deferred: EventDeferredLogMsg):
        # find the original message we're deferring
        raw_table = self._raw_tables[deferred.unit]
        is_already_deferred = False

        def _search_in_deferred():
            for dfrd in raw_table.currently_deferred:
                if dfrd.n == deferred.n:
                    # not the first time we defer this boy
                    is_already_deferred = True
                    return dfrd.msg

        def _search_in_tracked():
            for msg in self.tracking.get(deferred.unit, ()):
                if msg.event == deferred.event:
                    return msg

        msg = _search_in_deferred() or _search_in_tracked()
        deferred.msg = msg
        if not isinstance(msg, EventDeferredLogMsg):
            self.evt_count += 1

        if not is_already_deferred:
            raw_table.currently_deferred.append(deferred)

        logger.debug(f"deferred {deferred.event}")

    def _reemit(self, reemitted: EventReemittedLogMsg):
        # search deferred queue first to last
        unit = reemitted.unit
        raw_table = self._raw_tables[unit]

        for defrd in list(raw_table.currently_deferred):
            if defrd.n == reemitted.n:
                reemitted.deferred = defrd
                raw_table.currently_deferred.remove(defrd)
                # we track it.
                self.tracking[unit].append(reemitted)
                logger.debug(f"reemitted {reemitted.event}")
                return

        raise RuntimeError(
            f"cannot reemit {reemitted.event}({reemitted.n}); no "
            f"matching deferred event could be found "
            f"in {raw_table.currently_deferred}.")

    def __enter__(self):
        self.live.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.live.__exit__(exc_type, exc_val, exc_tb)

    def _match_event_deferred(self, log: str) -> Optional[EventDeferredLogMsg]:
        match = self.event_deferred.parse(log)
        if match:
            return EventDeferredLogMsg(**match.named)

    def _match_event_reemitted(self, log: str) -> Optional[
        EventReemittedLogMsg]:
        match = self.event_reemitted.parse(log)
        if match:
            return EventReemittedLogMsg(**match.named)

    def _match_event_emitted(self, log: str) -> Optional[EventLogMsg]:
        # log format =
        # unit-traefik-k8s-0: 10:36:19 DEBUG unit.traefik-k8s/0.juju-log ingress-per-unit:38: Emitting Juju event ingress_per_unit_relation_changed.
        # unit-prometheus-k8s-0: 13:06:09 DEBUG unit.prometheus-k8s/0.juju-log ingress:44: Emitting Juju event ingress_relation_changed.

        match = self.event.parse(log)

        # search for relation events
        if not match:
            match = self.relation_event.parse(log)
            if match:
                params = match.named
                # we don't have any use for those (yet?).
                del params['relation']
                del params['relation_id']

        # attempt to match in another format ?
        if not match:
            # fallback
            if match := self.uniter_event.parse(log):
                unit = parse.compile("unit-{}").parse(match.named['pod_name'])
                params = match.named
                *names, number = unit.fixed[0].split('-')
                name = '-'.join(names)
                params['unit'] = '/'.join([name, number])
            else:
                return

        else:
            params = match.named

        # uniform
        params['event'] = params['event'].replace('-', '_')
        return EventLogMsg(**params)

    def _add_new_target(self, msg: EventLogMsg):
        logger.info(f"adding new unit {msg.unit}")
        new_target = Target.from_name(msg.unit)

        self.tracking[msg.unit] = []
        self.targets.append(new_target)
        self._raw_tables[new_target.unit_name] = RawTable()

    def process(self, log: str):
        """process a log line"""
        if msg := self._match_event_emitted(log):
            mode = 'emit'
            self._track(msg)
        elif self._show_defer:
            if msg := self._match_event_deferred(log):
                mode = 'defer'
            elif msg := self._match_event_reemitted(log):
                self._track(msg)
                mode = 'reemit'
            else:
                return
        else:
            return

        if not self._is_tracking(msg):
            return

        if mode == 'defer':
            self._defer(msg)
        elif mode == 'reemit':
            self._reemit(msg)

        if mode in {'reemit', 'emit'}:
            self._timestamps.append(msg.timestamp)
            self._crop()

        if self._show_defer and self._is_tracking(msg) and mode != 'emit':
            self.update_defers(msg)

        self.render()

    def render(self, _debug=False):
        # we're rendering the table and flipping it every time. more efficient
        # to add new rows to the top and keep old ones, but how do we know if
        # deferral lines have changed?
        table = Table(show_footer=False, expand=True)
        table.add_column(header="timestamp")
        unit_grids = []
        for target in self.targets:
            tgt_grid = Table.grid('', '', expand=True, padding=(0, 1, 0, 1))
            raw_table = self._raw_tables[target.unit_name]
            for event, deferral, n in zip(raw_table.events, raw_table.deferrals,
                                          raw_table.ns):
                evt = event
                if self._show_ns and n is not None:
                    evt = f"({n}) {evt}"
                tgt_grid.add_row(evt, deferral)

            table.add_column(header=target.unit_name)
            unit_grids.append(tgt_grid)

        _timestamps_grid = Table.grid('', expand=True)
        for tstamp in self._timestamps:
            _timestamps_grid.add_row(tstamp)

        table.add_row(_timestamps_grid, *unit_grids)
        if _debug:
            Console().print(table)
            return table

        table_centered = Align.center(table)
        self.live.update(table_centered)

    def _is_tracking(self, msg):
        return msg.unit in self.tracking

    _pad = " "
    _dpad = _pad * 2
    _nothing_to_report = "."
    _vline = "│"
    _cross = "┼"
    _lup = "┘"
    _lupdown = "┤"
    _bounce = "⭘"
    _ldown = "┐"
    _hline = "─"
    _close = "❮"
    _open = "❯"

    def update_defers(self, msg: EventLogMsg):
        # all the events we presently know to be deferred
        unit = msg.unit
        raw_table = self._raw_tables[unit]
        deferred = raw_table.currently_deferred

        tail = self._vline * len(tuple(d for d in deferred if d is not msg))

        previous_msg_idx = None
        deferring = isinstance(msg, EventDeferredLogMsg)
        reemitting = isinstance(msg, EventReemittedLogMsg)
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
                pass

        if deferring:
            # we did not find (in scope) a previous logline emitting
            # this event by number; let's search by name.
            if previous_msg_idx is None:
                try:
                    previous_msg_idx = raw_table.events.index(msg.event)
                except StopIteration:
                    # should really not happen
                    logger.error(f"{msg.event} not found in raw table")
                    raise

                if known_n := raw_table.ns[previous_msg_idx] is not None:
                    assert known_n == msg.n, f"mismatching n; {known_n} != {msg.n}"

                # store it
                raw_table.ns[previous_msg_idx] = msg.n
                # if previous_msg_idx == 0, that's the case in
                # which we're deferring the last event we emitted.
                # otherwise we're deferring something we've re-emitted.
                original_cell = raw_table.deferrals[previous_msg_idx]
                if self._vline in original_cell:
                    tail_cell = original_cell
                else:
                    tail_cell = original_cell + tail
                new_cell = tail_cell.replace(
                    self._dpad,
                    self._open + self._hline).replace(
                    self._vline, self._cross) + self._lup

                raw_table.deferrals[previous_msg_idx] = new_cell
                lane = new_cell.index(self._lup)

            else:
                # not the first time we defer you, boy
                original_cell = raw_table.deferrals[previous_msg_idx]
                new_cell = original_cell.replace(
                    self._close + self._hline,
                    self._pad + self._bounce
                ).replace(self._ldown, self._lupdown)
                raw_table.deferrals[previous_msg_idx] = new_cell
                lane = new_cell.index(self._lupdown)

            self._cache_lane(msg.n, lane)

        elif reemitting:
            if previous_msg_idx is None:
                # message must have been cropped away
                logger.debug(f'unable to grab fetch previous reemit, '
                             f'msg {msg.n} must be out of scope')

            lane = None
            if previous_msg_idx is not None:
                original_reemittal_cell = raw_table.deferrals[previous_msg_idx]

                # reopen previous reemittal if it's closed
                previous_reemittal_cell = original_reemittal_cell.replace(
                    self._close + self._hline,
                    self._pad + self._bounce
                ).replace(
                    self._ldown, self._lupdown)
                raw_table.deferrals[previous_msg_idx] = previous_reemittal_cell

                lane = None
                for sym in {self._lupdown, self._lup}:
                    if sym in previous_reemittal_cell:
                        lane = previous_reemittal_cell.index(sym)
                        break  # found
            if lane is None:
                lane = self._get_lane(msg.n)
                if lane is None:
                    raise RuntimeError(f'lane not cached for {msg.n}, and '
                                       f'message is out of scope. '
                                       f'Unable to proceed.')
            self._cache_lane(msg.n, lane)

            # now we look at the newly added cell and add a closure statement.
            current_cell = raw_table.deferrals[0]
            current_cell_new = current_cell.replace(
                self._dpad, self._close + self._hline)

            closed_cell = _put(current_cell_new, lane, self._ldown, self._hline)
            final_cell = list(closed_cell)
            for ln in range(lane):
                if final_cell[ln] == self._vline:
                    final_cell[ln] = self._cross
            raw_table.deferrals[0] = ''.join(final_cell)

            if previous_msg_idx is not None:
                rng = range(1, previous_msg_idx)
            else:
                # until the end of the visible table
                rng = range(1, len(raw_table.deferrals))

            for ln in rng:
                raw_table.deferrals[ln] = _put(
                    raw_table.deferrals[ln], lane,
                    {None: self._vline,
                     self._hline: self._cross,
                     self._ldown: self._lupdown},
                    self._nothing_to_report)

        else:
            raw_table.deferrals[0] += tail

    def _get_lane(self, n: str):
        return self._lanes.get(n)

    def _cache_lane(self, n: str, lane: int):
        self._lanes[n] = lane

    def _crop(self):
        # crop all:
        if len(self._timestamps) <= self.history_length:
            # nothing to do.
            return

        lst: List
        for lst in (self._timestamps,
                    *(raw.deferrals for raw in self._raw_tables.values()),
                    *(raw.events for raw in self._raw_tables.values()),
                    *(raw.ns for raw in self._raw_tables.values())):
            if len(lst) > self.history_length:
                logger.info('popping a row')
                lst.pop()  # pop first


def _get_debug_log(cmd):
    return Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=STDOUT)


def tail_events(
        targets: str = typer.Argument(
            None,
            help="Semicolon-separated list of targets to follow. "
                 "Example: 'foo/0;foo/1;bar/2'. By default, it will follow all "
                 "available targets."),
        add_new_targets: bool = True,
        level: LEVELS = 'DEBUG',
        replay: bool = True,  # listen from beginning of time?
        dry_run: bool = False,
        framerate: float = .5,
        length: int = typer.Option(10, '-n', '--length'),
        show_defer: bool = False,
        watch: bool = True
):
    """Pretty-print a table with the events that are fired on juju units
    in the current model.
    """
    if isinstance(level, str):
        level = getattr(LEVELS, level.upper())

    if not isinstance(level, LEVELS):
        raise ValueError(level)

    track_events = True
    if level not in {LEVELS.DEBUG, LEVELS.TRACE}:
        print(f"we won't be able to track events with level={level}")
        track_events = False

    if targets and add_new_targets:
        print('targets provided; overruling add_new_targets param.')
        add_new_targets = False

    targets = parse_targets(targets)

    cmd = ([JUJU_COMMAND, 'debug-log'] +
           (['--tail'] if watch else []) +
           (['--replay'] if replay else []) +
           ['--level', level.value])

    if dry_run:
        print(' '.join(cmd))
        return

    try:
        with Processor(targets, add_new_targets,
                       history_length=length,
                       show_defer=show_defer) as processor:
            proc = _get_debug_log(cmd)
            # when we're in replay mode we're catching up with the replayed logs
            # so we won't limit the framerate and just flush the output
            replay_mode = True

            if not watch:
                stdout = iter(proc.stdout.readlines())

                def next_line():
                    try:
                        return next(stdout)
                    except StopIteration:
                        return ''

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

                    if proc.poll() is not None:
                        # process terminated FIXME: this shouldn't happen
                        break

                    replay_mode = False
                    continue

                if line:
                    msg = line.decode('utf-8').strip()
                    processor.process(msg)

                if not replay_mode and (
                        elapsed := time.time() - start) < framerate:
                    time.sleep(framerate - elapsed)
                    print(f"sleeping {framerate - elapsed}")


    except KeyboardInterrupt:
        print('exiting...')
        return

    print(f"processed {processor.evt_count} events.")


def _put(s: str, index: int, char: Union[str, Dict[str, str]], placeholder=' '):
    if isinstance(char, str):
        char = {None: char}

    if len(s) <= index:
        s += placeholder * (index - len(s)) + char[None]
        return s

    l = list(s)
    l[index] = char.get(l[index], char[None])
    return ''.join(l)


if __name__ == '__main__':
    tail_events(targets='traefik-k8s/0', length=10000, watch=False)
