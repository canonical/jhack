import datetime
import time
from subprocess import Popen

import typer


def fast_forward(
        timeout: int = typer.Option(
            None, help="Time after which ffwd will automatically stop. "
                       "If unfilled, it will continue until CTRL+C."),
        fast_interval: int = typer.Option(
            5, help="Time in seconds for the speed up."),
        slow_interval: str = typer.Option(
            '5m', help="Time (as a string) at which the speed will be reset"
                       "when ffwd terminates. Examples: 5m, 10m, 2h, 20s.")):
    """Utility to speed up update-status hook intervals."""
    cmd = Popen(
        f"juju model-config update-status-hook-interval={fast_interval}s".split(
            ' '))
    cmd.wait()
    start = datetime.datetime.now()
    ping = start
    print('fast-forwarding... (CTRL+C to abort)')
    if timeout:
        print(f'\ttimeout set at {timeout}s\n')

    try:
        while True:
            now = datetime.datetime.now()
            elapsed = (now - start).seconds
            time_since_last_ping = (now - ping).seconds
            if time_since_last_ping >= fast_interval:
                ping = now
                if timeout:
                    remaining = timeout - elapsed
                    print(remaining, end='', flush=True)
                else:
                    print('.', end='', flush=True)

            if timeout and elapsed >= timeout:
                print(' ||\n', flush=True)
                break

            if not timeout or timeout >= 5:
                time.sleep(1)
            print('.', end='', flush=True)

    except KeyboardInterrupt:
        print('(aborted)')

    cmd = Popen(f"juju model-config "
                f"update-status-hook-interval={slow_interval}".split(' '))
    cmd.wait()
