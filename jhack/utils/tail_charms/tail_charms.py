import re
from pathlib import Path
from typing import (
    Callable,
    List,
    Literal,
    Union,
)

import jhack.utils.tail_charms.ui.printer
from jhack import helpers
from jhack.helpers import JPopen, find_leaders
from jhack.logger import logger as jhack_logger
from jhack.utils.debug_log_interlacer import DebugLogInterlacer
from jhack.utils.tail_charms.core.juju_model_loglevel import (
    bump_loglevel,
    debump_loglevel,
)
from jhack.utils.tail_charms.core.juju_model_loglevel import (
    LEVELS,
)
from jhack.utils.tail_charms.ui.printer import PoorPrinter, RichPrinter
from jhack.utils.tail_charms.core.processor import Processor, EventLogMsg

logger = jhack_logger.getChild(__file__)


def _get_debug_log(cmd):
    # to easily allow mocking in tests
    return JPopen(cmd)


def tail_charms(
    targets: List[str] = None,
    add_new_units: bool = True,
    level: LEVELS = "DEBUG",
    replay: bool = True,  # listen from beginning of time?
    dry_run: bool = False,
    framerate: float = 0.5,
    length: int = 10,
    show_defer: bool = False,
    show_ns: bool = False,
    show_operator_events: bool = False,
    flip: bool = False,
    show_trace_ids: bool = False,
    watch: bool = True,
    color: jhack.utils.tail_charms.ui.printer.Color = "auto",
    files: List[Union[str, Path]] = None,
    event_filter: str = None,
    # for script use only
    _on_event: Callable[["EventLogMsg"], None] = None,
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
        previous_loglevel = bump_loglevel(model=model)

    if previous_loglevel is None:
        # this usually means the model doesn't exist.
        try:
            helpers.juju_status(model=model)
        except helpers.GetStatusError:
            if model:
                exit(
                    f"unable to connect to model {model}. "
                    f"Does the model exist on the current controller?"
                )
            else:
                exit("unable to connect to current juju model. Are you switched to one?")

    event_filter_pattern = re.compile(event_filter) if event_filter else None
    leaders = find_leaders(targets, model=model)

    if printer == "raw":
        if flip or (color != "auto"):
            logger.warning("'flip' and 'color' args unavailable in this printer mode.")
        printer = PoorPrinter(
            live=True,
            output=Path(output) if output else None,
        )
        # poor printer won't display a 'listening for events...' message.
        logger.info("[raw printer] listening for events...")

    elif printer == "rich":
        printer = RichPrinter(
            color=color,
            flip=flip,
            show_defer=show_defer,
            show_ns=show_ns,
            show_trace_ids=show_trace_ids,
            output=Path(output) if output else None,
            max_length=length,
            framerate=framerate,
        )
    else:
        exit(f"unknown printer type: {printer}")

    processor = Processor(
        targets,
        leaders=leaders,
        add_new_units=add_new_units,
        show_ns=show_ns,
        show_trace_ids=show_trace_ids,
        show_operator_events=show_operator_events,
        printer=printer,
        show_defer=show_defer,
        event_filter_re=event_filter_pattern,
        model=model,
        flip=flip,
        output=output,
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
            debump_loglevel(previous_loglevel, model=model)

        processor.quit()

    return processor  # for testing


if __name__ == "__main__":
    import cProfile
    import io
    import pstats
    from pstats import SortKey

    pr = cProfile.Profile()
    pr.enable()
    try:
        tail_charms(length=30, replay=True)
    finally:
        pr.disable()
        s = io.StringIO()
        sortby = SortKey.CUMULATIVE
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats()
        print(s.getvalue())
