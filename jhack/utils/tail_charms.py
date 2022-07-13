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


@dataclass
class EventReemittedLogMsg(EventDeferredLogMsg):
    pass


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
        table.add_column(header="timestamp")
        for target in targets:
            table.add_column(header=target.unit_name)
        self.table_centered = table_centered = Align.center(table)
        self.live = Live(table_centered, console=console,
                         screen=False, refresh_per_second=20)

        self._events_id_ctr = 0
        self._events_tracked: Dict[int, EventLogMsg] = {}
        self._deferred: Dict[
            str, List[Tuple[EventDeferredLogMsg, EventLogMsg]]] = defaultdict(
            list)

    @property
    def evt_count(self):
        return self._events_id_ctr

    def _track(self, evt: EventLogMsg):
        self._events_id_ctr += 1
        self._events_tracked[self._events_id_ctr] = evt

        if self.add_new_targets and evt.unit not in self.messages:
            self._add_new_target(evt)
        if evt.unit in self.messages:  # target tracked
            self.messages[evt.unit].append(evt)

    def _defer(self, deferred: EventDeferredLogMsg):
        last_evt = self._events_tracked[self._events_id_ctr - 1]
        self._deferred[deferred.unit].append((deferred, last_evt))

    def _reemit(self, reemitted: EventReemittedLogMsg):
        # search deferred queue first to last
        unit = reemitted.unit
        for i, (defrd, evt) in enumerate(self._deferred[unit]):

            # fixme technically we can't be sure that it's THE SAME event, can we?
            def is_same_event(evt1: str, evt2: str):
                if evt1 == evt2:
                    return True

                # deferrals dump events like so: 'my_relation-with_dashes-relation-joined'
                # but re-emittals dumps it like: 'my_relation_with_dashes_relation_joined'
                # so:
                from itertools import takewhile, zip_longest
                common_suffix = ''.join(
                    reversed([c[0] for c in
                              takewhile(lambda x: all(x[0] == y for y in x),
                                        zip_longest(reversed(evt1),
                                                    reversed(evt2)))])
                )
                if not common_suffix:
                    return False

                # if there is a shared suffix, e.g. "-relation-departed", or "-pebble-ready':
                return evt1.replace('-', '_') == evt2.replace('-', '_')

            if is_same_event(defrd.event, reemitted.event):
                self._deferred[unit].remove((defrd, evt))
                return i
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
        return EventLogMsg(**params)

    def _add_new_target(self, msg: EventLogMsg):
        logger.info(f"adding new unit {msg.unit}")
        new_target = Target.from_name(msg.unit)

        self.messages[msg.unit] = []
        self.targets.append(new_target)
        self.table.add_column(header=new_target.unit_name)

        # fill the new column with empty cells, else it will
        # crop all other columns
        prev, col = self.table.columns[-2:]
        for _ in range(len(prev._cells)):
            col._cells.append('')

    def process(self, log: str):
        """process a log line"""
        if msg := self._match_event_emitted(log):
            self._track(msg)
            self.display_new_event(msg)

        elif deferred := self._match_event_deferred(log):
            self._defer(deferred)
            self.display_deferred(deferred)

        elif reemitted := self._match_event_reemitted(log):
            i = self._reemit(reemitted)
            self.display_reemitted(reemitted, i)

    _vline = "│"
    _cross = "┼"
    _lup = "┘"
    _ldown = "┐"
    _hline = "─"
    _close = "⇤"
    _open = "⇥"

    def display_new_event(self, msg: EventLogMsg, reemit_idx: int = None):
        # if reemit_idx is not None: that means that this event,
        # which we are emitting, is in fact a previously deferred
        # event which we are only now reemitting.

        unit = msg.unit
        for idx, col in enumerate(self.table.columns):
            if col.header == unit:
                # we found the column index corresponding to this unit.
                deferred = self._deferred[unit]
                if reemit_idx is not None:
                    deferrals = [self._hline * 2]
                    for i, _ in enumerate(deferred):
                        if i == reemit_idx:
                            deferrals.append(self._ldown)
                        if len(deferred) > 0:
                            # if there are more deferred events,
                            # we don't want to skip them.
                            deferrals.append(
                                self._cross if i > reemit_idx else self._vline)

                    cell = msg.event + ''.join(deferrals)
                elif deferred:
                    cell = msg.event + "  " + self._vline * len(deferred)
                else:
                    cell = msg.event
                row = [(cell if idx == i else None) for i in
                       range(1, len(self.table.columns))]

                self.table.add_row(msg.timestamp, *row)
                # move last to first
                for column in self.table.columns:
                    last = column._cells.pop()
                    column._cells.insert(0, last)

                # crop
                if len(self.table.rows) > self.history_length:
                    logger.info('popping a row...')
                    for column in self.table.columns:
                        column._cells.pop()  # pop last
                    self.table.rows.pop()
                return

        raise ValueError(f"no column found for {unit}")

    def display_deferred(self, msg: EventDeferredLogMsg):
        unit = msg.unit
        for idx, col in enumerate(self.table.columns):
            if col.header == unit:
                evt_line = col._cells[0]
                if not ' ' in evt_line:
                    col._cells[0] += self._hline * 2
                else:
                    index = evt_line.index(' ')
                    prev = evt_line[index - 1]

                    # check if the event has already been deferred. If so don't
                    # add one more arrow but upgrade the existing one.
                    if prev.isdigit():
                        newprefix = str((int(prev) + 1) if int(
                            prev) < 9 else "∞") + self._hline
                    else:
                        prev = " "
                        newprefix = self._hline
                    col._cells[0] = col._cells[0].replace(
                        prev, newprefix).replace(
                        self._vline, self._cross)

                col._cells[0] += "┘"  # start event deferral line

    def display_reemitted(self, msg: EventReemittedLogMsg, idx: int):
        self.display_new_event(msg, reemit_idx=idx)


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
