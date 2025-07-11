import re
import sys
from pathlib import Path
from typing import (
    Callable,
    List,
    Literal,
    Union,
    Optional,
)

import jhack.utils.tail_charms.ui.printer
from jhack.helpers import JPopen, find_leaders
from jhack.logger import logger as jhack_logger
from jhack.utils.debug_log_interlacer import DebugLogInterlacer
from jhack.utils.tail_charms.core.juju_model_loglevel import (
    Level,
    juju_loglevel_bumpctx,
    model_loglevel,
)
from jhack.utils.tail_charms.core.processor import Processor, EventLogMsg
from jhack.utils.tail_charms.ui.printer import PoorPrinter, RichPrinter

logger = jhack_logger.getChild(__file__)


def _get_debug_log(cmd):
    # to easily allow mocking in tests
    return JPopen(cmd)


def _do_replay(processor: Processor, model: str):
    logger.debug("doing replay")
    proc = _get_debug_log(
        ["juju", "debug-log"]
        + (["-m", model] if model else [])
        + ["--level", "DEBUG"]
        + ["--replay", "--no-tail"]
    )
    for line in iter(proc.stdout.readlines()):
        processor.process(line.decode("utf-8").strip())

    logger.debug("replay complete")
    logger.debug(
        f"captured: {processor.printer.count_events(processor._captured_logs)}"
    )


def _logs_from_stdin() -> Callable[[], str]:
    # handle input from stdin
    log_getter = sys.stdin
    logger.debug("setting up stdin next-line generator")

    def next_line():
        try:
            # Encode to be similar to other input sources
            return log_getter.readline().encode("utf-8")
        except StopIteration:
            return ""

    return next_line


def _logs_from_files(files: List[Union[Path, str]]) -> Callable[[], str]:
    # handle input from files
    log_getter = DebugLogInterlacer(files)
    logger.debug("setting up file-watcher next-line generator")

    def next_line():
        try:
            # Encode to be similar to other input sources
            return log_getter.readline().encode("utf-8")
        except StopIteration:
            return ""

    return next_line


def _logs_from_jdl_no_watch(cmd: List[str]) -> Callable[[], str]:
    logger.debug("setting up no-watch next-line generator")

    proc = _get_debug_log(cmd)
    stdout = iter(proc.stdout.readlines())

    def next_line():
        try:
            return next(stdout)
        except StopIteration:
            return ""

    return next_line


def _logs_from_jdl(cmd: List[str]) -> Callable[[], str]:
    logger.debug("setting up standard next-line generator")
    proc = _get_debug_log(cmd)

    def next_line():
        line = proc.stdout.readline()
        return line

    return next_line


def _validate_level(level: Optional[Union[str, Level]]) -> Optional[Level]:
    if level is None:
        return None
    if isinstance(level, str):
        level = getattr(Level, level.upper())
    if not isinstance(level, Level):
        raise ValueError(level)

    if level not in {Level.DEBUG, Level.TRACE}:
        logger.debug(f"we won't be able to track events with level={level}")

    return level


def tail_charms(
    targets: List[str] = None,
    add_new_units: bool = True,
    level: Level = None,
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
    """Tail charms."""

    targets = targets or []

    if output:
        logger.debug("output mode. Overriding watch.")
        watch = False
        auto_bump_loglevel = False  # it's too late for that, we're replaying the history and transforming it.

    # FIXME: when debugging, this heuristic is incorrect.
    read_from_stdin = not sys.stdin.isatty()
    # read_from_stdin = False

    level = _validate_level(level)
    if level is None:
        if read_from_stdin:
            logger.warning(
                "jhack cannot know what loglevel the logs being streamed to stdin "
                "were captured at. "
                "We'll assume it was WARNING. Which means you'll only see hook events, "
                "even if the model was set to a more verbose loglevel. "
                "Pass the loglevel explicitly to `--level`."
            )
            level = Level.WARNING

    if (read_from_stdin or files) and auto_bump_loglevel:
        logger.debug("static input mode. Overriding auto loglevel bumping.")
        auto_bump_loglevel = False

    if not targets and add_new_units:
        logger.debug("targets not provided; overruling add_new_units param.")
        add_new_units = False

    # right now we only accept one input stream at a time:
    # either a live juju model, or logfiles, or stdin.
    # stdin has precedence.
    if read_from_stdin:
        if files:
            # the user asked something we just can't support at the moment
            exit("only one input stream at a time is supported")
        if replay:
            # this defaults to False, which means the user passed --replay;
            # this option only makes sense if the user passed --watch, which doesn't make sense if
            # we're reading from stdin.
            # be tolerant and let it slip with a warning.
            logger.warn("when you pass logs over stdin, --replay is implied")
            replay = False
        if watch:
            # this defaults to True, which means we have to be lenient.
            # when you pass logs over stdin, you cannot --watch: the tail stops when stdin ends
            logger.debug("reading from stdin: overriding --watch option.")
            watch = False

    cmd = (
        ["juju", "debug-log"]
        + (["-m", model] if model else [])
        + (["--tail"] if watch else [])
        + ["--level", "DEBUG"]
    )

    if dry_run:
        print(" ".join(cmd))
        return

    with juju_loglevel_bumpctx(model, auto_bump_loglevel):
        printer = _build_printer(
            color=color,
            flip=flip,
            framerate=framerate,
            length=length,
            output=output,
            printer=printer,
            show_defer=show_defer,
            show_ns=show_ns,
            show_trace_ids=show_trace_ids,
        )

        leaders = {} if files or read_from_stdin else find_leaders(targets, model=model)

        # loglevel at which the logs we're going to parse were emitted;
        # if it's being passed by the caller we don't have to get it ourselves from the live model.
        # handy if there isn't a live model to begin with.
        loglevel = Level(level or model_loglevel(model=model))

        processor = Processor(
            targets,
            leaders=leaders,
            add_new_units=add_new_units,
            show_ns=show_ns,
            show_trace_ids=show_trace_ids,
            show_operator_events=show_operator_events,
            printer=printer,
            show_defer=show_defer,
            event_filter_re=re.compile(event_filter) if event_filter else None,
            flip=flip,
            output=output,
            level=loglevel,
        )

        if replay:
            _do_replay(processor, model=model)

        # obtain the function we're going to call to generate loglines
        if read_from_stdin:
            next_line = _logs_from_stdin()
        elif files:
            next_line = _logs_from_files(files)
        elif watch:
            next_line = _logs_from_jdl(cmd)
        else:
            next_line = _logs_from_jdl_no_watch(cmd)

        try:
            # main listen loop
            while True:
                # obtain next logline
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

                    # if we've been called with the --output flag we exit here
                    if output:
                        # todo: consider doing a break here instead of exit()
                        exit()

                    continue

        except KeyboardInterrupt:
            pass  # quit
        finally:
            processor.quit()

    return processor  # for testing


def _build_printer(
    printer: Literal["rich", "raw"] = "rich",
    color: jhack.utils.tail_charms.ui.printer.Color = "auto",
    framerate: float = 0.5,
    length: int = 10,
    show_defer: bool = False,
    show_ns: bool = False,
    flip: bool = False,
    show_trace_ids: bool = False,
    output: str = None,
):
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
    return printer


if __name__ == "__main__":

    def profile():
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

    def run():
        tail_charms(length=30, replay=True)

    run()
