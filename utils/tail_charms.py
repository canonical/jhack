import asyncio
import enum
import time
from dataclasses import dataclass
from enum import Enum
from itertools import chain
from subprocess import Popen, PIPE, STDOUT
from typing import Sequence, Literal

import rich


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

    def as_include(self):
        return f"{self.app}/{self.unit}"


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


def tail_events(targets: str = None,
                # semicolon-separated list of targets to follow
                level: LEVELS = 'DEBUG',
                replay: bool = True,  # listen from beginning of time?
                dry_run: bool = False,
                framerate: float = .5
                ):
    print("initializing...")

    if isinstance(level, str):
        level = getattr(LEVELS, level.upper())

    if not isinstance(level, LEVELS):
        raise ValueError(level)

    track_events = True
    if level not in {LEVELS.DEBUG, LEVELS.TRACE}:
        print(f"we won't be able to track events with level={level}")
        track_events = False

    targets = parse_targets(targets)

    cmd = (['juju', 'debug-log'] +
           (['--replay'] if replay else []) +
           ['--level', level.value] +
           list(chain(*[
               ['--include', target.as_include()]
               for target in targets]))
           )

    if dry_run:
        print(' '.join(cmd))
        return

    try:
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
                print(line.decode('utf-8').strip())

            if not replay_mode and (elapsed := time.time() - start) < framerate:
                time.sleep(framerate - elapsed)
                print(f"sleeping {framerate - elapsed}")


    except KeyboardInterrupt:
        print('exiting...')
        return


if __name__ == '__main__':
    tail_events()
