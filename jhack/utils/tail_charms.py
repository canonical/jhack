import enum
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from subprocess import Popen, PIPE, STDOUT
from typing import Sequence, Optional, Iterable, List, Dict, Tuple

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

    lane: int = None
    # the original event we're deferring or re-deferring
    msg: EventLogMsg = None


@dataclass
class EventReemittedLogMsg(EventLogMsg):
    event_cls: str
    charm_name: str
    n: str

    deferred: EventDeferredLogMsg = None


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
                 history_length: int = 10):
        self.targets = list(targets)
        self.add_new_targets = add_new_targets
        self.history_length = history_length
        self.messages = {t.unit_name: [] for t in targets}
        self.console = console = Console()
        self.table = table = Table(show_footer=False, expand=True)
        self._unit_grids = {}

        table.add_column(header="timestamp")
        unit_grids = []
        for target in targets:
            tgt_grid = Table.grid('', '', expand=True)
            table.add_column(header=target.unit_name)
            self._unit_grids[target.unit_name] = tgt_grid
            unit_grids.append(tgt_grid)

        self._timestamps_grid = Table.grid('', expand=True)
        table.add_row(self._timestamps_grid, *unit_grids)

        self.table_centered = table_centered = Align.center(table)
        self.live = Live(table_centered, console=console,
                         screen=False, refresh_per_second=20)

        self.evt_count = 0

        # used to determine the deferral lane
        self.deferred_evt_count = 0
        self._events_tracked: Dict[str, List[EventLogMsg]] = defaultdict(list)
        self._deferred: Dict[str, List[EventDeferredLogMsg]] = defaultdict(list)

    def _track(self, evt: EventLogMsg):
        self.evt_count += 1
        self._events_tracked[evt.unit].append(evt)

        if self.add_new_targets and evt.unit not in self.messages:
            self._add_new_target(evt)

        if evt.unit in self.messages:  # target tracked
            self.messages[evt.unit].append(evt)
            print(f"tracking {evt.event}")

    def _defer(self, deferred: EventDeferredLogMsg):
        # find the original message we're deferring
        def _search_in_deferred():
            for dfrd in self._deferred[deferred.unit]:
                if dfrd.n == deferred.n:
                    # not the first time we defer this boy
                    return dfrd.msg

        def _search_in_tracked():
            for msg in self.messages[deferred.unit]:
                if msg.event == deferred.event:
                    return msg

        msg = _search_in_deferred() or _search_in_tracked()
        deferred.msg = msg
        if isinstance(msg, EventDeferredLogMsg):
            deferred.lane = msg.lane
        else:
            self.deferred_evt_count += 1
            deferred.lane = self.deferred_evt_count

        self._deferred[deferred.unit].append(deferred)
        print(f"deferred {deferred.event}; lane {deferred.lane}")

    def _reemit(self, reemitted: EventReemittedLogMsg):
        # search deferred queue first to last
        unit = reemitted.unit
        for defrd in list(self._deferred[unit]):
            if defrd.n == reemitted.n:
                reemitted.deferred = defrd
                self._deferred[unit].remove(defrd)
                # we track it.
                self.messages[unit].append(reemitted)
                print(f"reemitted {reemitted.event}")
                return

        raise RuntimeError(f"cannot reemit {reemitted.event}; no "
                           f"matching deferred event could be found "
                           f"in {self._deferred[unit]}.")

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

        self.messages[msg.unit] = []
        self.targets.append(new_target)
        self.table.add_column(header=new_target.unit_name)
        grid = Table.grid('', expand=True)

        self._unit_grids[new_target.unit_name] = grid
        self.table.columns[-1]._cells.append(grid)

    def process(self, log: str):
        """process a log line"""
        if msg := self._match_event_emitted(log):
            self._track(msg)
            self.display(msg)

        elif deferred := self._match_event_deferred(log):
            self._defer(deferred)
            self._display_deferred(deferred)

        elif reemitted := self._match_event_reemitted(log):
            self._reemit(reemitted)
            self.display(reemitted, reemitted=True)

        Console().print(self.table)

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

    def display(self, msg: EventLogMsg, reemitted: bool = False):
        # if reemit_idx is not None: that means that this event,
        # which we are emitting, is in fact a previously deferred
        # event which we are only now reemitting.
        unit = msg.unit
        unit_grid = self._unit_grids[unit]

        # add the event and the deferred events tree to the unit grid for
        # this unit
        deferred_events = self._deferred[unit]

        lane = ''
        if deferred_events:
            lanes = {d.lane: d for d in deferred_events}
            max_lane = max(lanes)
            this_lane = -1
            if reemitted:
                this_lane = msg.deferred.lane

            for lane_n in range(1, max_lane + 1):
                if lane_n == this_lane:
                    lane += self._ldown
                    continue
                lane_busy = lanes.get(lane_n)
                lane += (self._vline if lane_busy else self._nothing_to_report)
        else:
            if reemitted:
                lane += self._ldown

        if reemitted:
            cell = self._pad + self._close + lane
        else:
            cell = self._dpad + lane

        n = f"({msg.n}) " if hasattr(msg, 'n') else ""
        unit_grid.add_row(f"{n}{msg.event}", cell)
        # move last to first, because we can't add row to the top
        self._rotate(unit_grid, 0)
        self._rotate(unit_grid, 1)

        self._add_timestamp(msg)
        self._crop()

    def _display_deferred(self, msg: EventDeferredLogMsg):
        # the problem is, we've emitted this event in the past.
        # so instead of adding a new line we need to grab the right line and replace the deferral cell.
        # the index of this event in the deferral queue, corresponding to the line index

        # original message
        # todo: might be gone by now!
        original_evt_idx = list(reversed(self.messages[msg.unit])).index(msg.msg)

        # restyle the original row
        self._unit_grids[msg.unit].columns[0]._cells[original_evt_idx] = f"({msg.n}) {msg.event}"
        deferral_cell = self._unit_grids[msg.unit].columns[1]._cells[original_evt_idx]
        deferrals = list(deferral_cell)[2:]

        def _update_lane(deferrals):
            lane = msg.lane
            if len(deferrals) <= lane:
                deferrals += [self._nothing_to_report] * (lane - len(deferrals) + 1)
            deferrals[lane] = self._lup

        _update_lane(deferrals)
        new_cell = self._pad + self._open + ''.join(deferrals)
        self._unit_grids[msg.unit].columns[1]._cells[original_evt_idx] = new_cell


        return

        # it might be that between the emitted event and *now* other events have been reemitted (and redeferred?)
        # example:
        # 0 emit install                # cell 1
        # 1 defer install               # will update cell 1 with corner and line
        # 2 update-status               # event; cell 2; knows of 0: one deferral line
        # 3 reemit queued install
        # 4 re-defer install            # knows of 0 but not yet of 5: updates with bounce, keeps one line
        # 5 defer update-status         # deferral; cell 2 is now wrong: there should be two deferral lines.

        # that means that we need to update all rows between 2 and 5,
        # because when they were rendered they only knew of one deferred event
        # being present (install), but now we know that also update-status is being deferred.
        # for cell in unit_grid.columns[1]._cells[:deferred_idx]:
        #     cell += self._vline

        # search if this event has been reemitted before; if so we
        # need to turn that reemit into a bounce
        reemitted_idx = None
        for i, defrd in enumerate(deferred_events):
            if defrd.n == msg.n:
                reemitted_idx = i

        if reemitted_idx:
            previous_deferral_cell = unit_grid.columns[1]._cells[reemitted_idx]
            # if self._ldown in previous_deferral_cell:
            # we've just reemitted this event. We're apparently deferring it again.

            print(len(deferred_events))
            unit_grid.columns[1]._cells[
                reemitted_idx] = previous_deferral_cell.replace(
                self._ldown, self._lupdown).replace(
                self._close, self._bounce)

            previous_event_name_cell = unit_grid.columns[0]._cells[
                reemitted_idx]
            if not f"({msg.n})" in previous_event_name_cell:
                # first time we defer it:
                # update the event row by adding the event n
                n_evt = f"({msg.n}) {msg.event}"
                unit_grid.columns[0]._cells[reemitted_idx] = n_evt

        # and now about all other lines in between:
        for i, cell in enumerate(unit_grid.columns[1]._cells[:reemitted_idx]):
            newcell = list(cell)
            diff = (msg.lane - len(cell))
            if diff >= 0:
                newcell += ' ' * (diff + 1)
            newcell[msg.lane] = self._vline
            unit_grid.columns[1]._cells[i] = ''.join(newcell)
        return  # we also don't need to add timestamps or crop

    @staticmethod
    def _rotate(table, column):
        table.columns[column]._cells.insert(0, table.columns[
            column]._cells.pop())  # noqa

    def _add_timestamp(self, msg: EventLogMsg):
        timestamps = self._timestamps_grid
        timestamps.add_row(msg.timestamp)
        # move last to first, because we can't add row to the top
        self._rotate(timestamps, 0)

    def _crop(self):
        # crop all:
        for table in (self._timestamps_grid, *self._unit_grids.values()):
            if len(table.rows) > self.history_length:
                logger.info('popping a row...')
                for column in table.columns:
                    column._cells.pop()  # pop last
                table.rows.pop()  # pop last


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
        watch: bool = True,
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
                       history_length=length) as processor:
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


if __name__ == '__main__':
    tail_events(targets='traefik-k8s/0', length=10000, watch=False)
