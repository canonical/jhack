import enum
import enum
import logging
import time
from dataclasses import dataclass
from subprocess import Popen, PIPE, STDOUT
from typing import Sequence, Optional, Iterable

import parse
import typer
from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.table import Table

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
    cmd = Popen("juju status".split(' '), stdout=PIPE)
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
    relation: str = None
    relation_id: str = None


class Processor:
    # FIXME: why does sometime event/relation_event work, and sometimes
    #  uniter_event does? OF Version?
    event = parse.compile(
        "{pod_name}: {timestamp} {loglevel} unit.{unit}.juju-log Emitting Juju event {event}.")
    relation_event = parse.compile(
        "{pod_name}: {timestamp} {loglevel} unit.{unit}.juju-log {relation}:{relation_id}: Emitting Juju event {event}.")
    uniter_event = parse.compile(
        '{pod_name}: {timestamp} {loglevel} juju.worker.uniter.operation ran "{event}" hook (via hook dispatching script: dispatch)')

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

    def __enter__(self):
        self.live.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.live.__exit__(exc_type, exc_val, exc_tb)

    def process(self, log: str) -> Optional[EventLogMsg]:
        # log format =
        # unit-traefik-k8s-0: 10:36:19 DEBUG unit.traefik-k8s/0.juju-log ingress-per-unit:38: Emitting Juju event ingress_per_unit_relation_changed.
        # unit-prometheus-k8s-0: 13:06:09 DEBUG unit.prometheus-k8s/0.juju-log ingress:44: Emitting Juju event ingress_relation_changed.

        match = self.event.parse(log) or self.relation_event.parse(log)
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
        msg = EventLogMsg(**match.named)

        if self.add_new_targets and msg.unit not in self.messages:
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

        if msg.unit in self.messages:  # target tracked
            self.messages[msg.unit].append(msg)
            self.update(msg)

    def update(self, msg: EventLogMsg):
        # delete current line
        for idx, col in enumerate(self.table.columns):
            if col.header == msg.unit:
                row = [(msg.event if idx == i else None) for i in
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

        raise ValueError(f"no column found for {msg.unit}")


def tail_events(
        targets: str = typer.Argument(
            None,
            help="Semicolon-separated list of targets to follow. "
                 "Example: 'foo/0;foo/1;bar/2'"),
        add_new_targets: bool = True,
        level: LEVELS = 'DEBUG',
        replay: bool = True,  # listen from beginning of time?
        dry_run: bool = False,
        framerate: float = .5,
        length: int = typer.Option(10, '-n', '--length'),
):
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

    cmd = (['juju', 'debug-log', '--tail'] +
           (['--replay'] if replay else []) +
           ['--level', level.value])

    if dry_run:
        print(' '.join(cmd))
        return

    try:
        with Processor(targets, add_new_targets,
                       history_length=length) as processor:
            proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=STDOUT)
            # when we're in replay mode we're catching up with the replayed logs
            # so we won't limit the framerate and just flush the output
            replay_mode = True
            while True:
                start = time.time()

                line = proc.stdout.readline()
                if not line:
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


if __name__ == '__main__':
    tail_events(targets='database/0', length=100)
