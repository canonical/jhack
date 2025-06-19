import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence, Dict, List, Set, Optional, Tuple

from jhack.logger import logger as jhack_logger
from jhack.utils.tail_charms.core.deferral_status import DeferralStatus
from jhack.utils.tail_charms.core.juju_model_loglevel import (
    Level,
    BEST_LOGLEVELS,
)
from jhack.utils.tail_charms.core.parser import (
    LogLineParser,
)
from jhack.utils.tail_charms.ui.printer import Printer, PoorPrinter

logger = jhack_logger.getChild(__file__)


@dataclass
class EventLogMsg:
    type = "emitted"

    pod_name: str
    timestamp: str
    loglevel: str
    unit: str
    event: str
    mocked: bool
    deferred: DeferralStatus = DeferralStatus.null

    event_cls: str = None
    charm_name: str = None
    n: int = None

    tags: Tuple[str, ...] = ()

    # we don't have any use for these, and they're only present if this event
    # has been (re)emitted/deferred during a relation hook call.
    endpoint: str = ""
    endpoint_id: str = ""

    # special for jhack-replay-emitted loglines
    jhack_replayed_evt_timestamp: str = ""

    # special for charm-tracing-enabled charms
    trace_id: str = ""

    # juju exec-event exit code. Specific for event messages.
    exit_code: int = 0


@dataclass
class EventDeferredLogMsg(EventLogMsg):
    type = "deferred"
    event_cls: str = ""
    charm_name: str = ""
    n: str = ""

    def __hash__(self):
        return hash((self.type, self.charm_name, self.n, self.event))


@dataclass
class EventReemittedLogMsg(EventDeferredLogMsg):
    type = "reemitted"


class Processor:
    def __init__(
        self,
        targets: Sequence[str] = None,
        printer: Printer = None,
        leaders: Dict[str, str] = None,
        add_new_units: bool = True,
        show_ns: bool = True,
        show_trace_ids: bool = False,
        show_operator_events: bool = False,
        show_defer: bool = False,
        event_filter_re: re.Pattern = None,
        output: str = None,
        # only available in rich printing mode
        flip: bool = False,
        level: Level = Level.DEBUG,
    ):
        self.targets = list(targets) if targets else []
        self.printer = printer or PoorPrinter()
        self.leaders = leaders or {}
        self.output = Path(output) if output else None
        self.add_new_units = add_new_units

        self.event_filter_re = event_filter_re
        self._captured_logs: List[EventLogMsg] = []
        self._currently_deferred: Set[EventLogMsg] = set()

        self._show_ns = show_ns and show_defer
        self._show_defer = show_defer
        self._flip = flip
        self._show_trace_ids = show_trace_ids
        self._next_msg_trace_id: Optional[str] = None
        self._next_msg_fail = False
        self._has_just_emitted = False
        self._warned_about_orphans = False

        self.parser = LogLineParser(
            capture_operator_events=show_operator_events,
            uniter_events_only=level.value not in BEST_LOGLEVELS,
        )

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

    def _defer(self, deferred: EventDeferredLogMsg):
        # find the original message we're deferring
        found = None
        for captured in filter(
            lambda e: e.unit == deferred.unit, self._captured_logs[::-1]
        ):
            if captured.event == deferred.event:
                found = captured
                break

        if not found:
            # we're deferring an event we've not seen before: logging just started.
            # so we pretend we've seen it, to be safe.
            found = EventLogMsg(
                pod_name=deferred.pod_name,
                timestamp="",
                loglevel=deferred.loglevel,
                unit=deferred.unit,
                event=deferred.event,
                mocked=True,
                deferred=DeferralStatus.deferred,
            )
            self._captured_logs.append(found)
            logger.debug(
                f"Mocking {found}: we're deferring it but we've not seen it before."
            )

        currently_deferred_ns = {d.n for d in self._currently_deferred}
        is_already_deferred = deferred.n in currently_deferred_ns
        found.n = deferred.n
        if found.deferred == DeferralStatus.reemitted:
            # the event we found
            found.deferred = DeferralStatus.bounced
        else:
            found.deferred = DeferralStatus.deferred

        if not is_already_deferred:
            logger.debug(f"deferring {deferred}")
            self._currently_deferred.add(deferred)
        else:
            # not the first time we defer this boy
            logger.debug(f"bouncing {deferred.event}")

    def _reemit(self, reemitted: EventReemittedLogMsg):
        # search deferred queue first to last
        deferred = None
        for _deferred in list(self._currently_deferred):
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

            self._defer(deferred)
            logger.debug(
                f"mocking {deferred}: we're reemitting it but we've not seen it before."
            )
            # the 'happy path' would have been: _emit, _defer, _emit, _reemit,
            # so we need to _emit it once more to pretend we've seen it.

        reemitted.deferred = DeferralStatus.reemitted
        self._currently_deferred.remove(deferred)

        logger.debug(f"reemitted {reemitted.event}")

    def _match_filter(self, event_name: str) -> bool:
        """If the user specified an event name regex filter, run it."""
        if not self.event_filter_re:
            return True
        match = self.event_filter_re.match(event_name)
        return bool(match)

    def _match_event_deferred(self, log: str) -> Optional[EventDeferredLogMsg]:
        if "Deferring" not in log:
            return None
        match = self.parser.match_event_deferred(log)
        if match:
            if not self._match_filter(match["event"]):
                return None
            return EventDeferredLogMsg(**match, mocked=False)

    def _match_event_reemitted(self, log: str) -> Optional[EventReemittedLogMsg]:
        if "Re-emitting" not in log:
            return None
        match = self.parser.match_event_reemitted(log)
        if match:
            if not self._match_filter(match["event"]):
                return None
            return EventReemittedLogMsg(**match, mocked=False)

    def _match_event_emitted(self, log: str) -> Optional[EventLogMsg]:
        match = self.parser.match_event_emitted(log)
        if match:
            if not self._match_filter(match["event"]):
                return None
            return EventLogMsg(**match, mocked=False)

    def _match_jhack_modifiers(self, log: str) -> Optional[EventLogMsg]:
        match = self.parser.match_modifiers(log, trace_id=self._show_trace_ids)
        if match:
            if not self._match_filter(match["event"]):
                return None
            return EventLogMsg(**match, mocked=False)

    def _apply_jhack_mod(self, msg: EventLogMsg):
        def _get_referenced_msg(
            event: Optional[str], unit: str
        ) -> Optional[EventLogMsg]:
            # this is the message we're referring to, the one we're modifying
            logs = self._captured_logs
            if not event:
                if not logs:
                    logger.error("cannot reference the previous event: no messages.")
                    return None
                return logs[-1]
            # try to find last event of this type emitted on the same unit:
            # that is the one we're referring to
            try:
                referenced_log = next(
                    filter(lambda e: e.event == event and e.unit == unit, logs[::-1])
                )
            except StopIteration:
                logger.error(f"{unit}:{event} not found in history... simulating one.")
                log = EventLogMsg(
                    pod_name=msg.pod_name,
                    timestamp=msg.timestamp,
                    loglevel=msg.loglevel,
                    unit=msg.unit,
                    event=msg.event,
                    mocked=True,  # set mocked.
                )
                self._captured_logs.append(log)
                return log
            return referenced_log

        if "fire" in msg.tags:
            # the previous event of this type was fired by jhack.
            # copy over the tags
            referenced_msg = _get_referenced_msg(msg.event, msg.unit)
            if referenced_msg:
                referenced_msg.tags = msg.tags

        elif "failed" in msg.tags:
            # the previous logged event of this type has exited with an error.
            # tag the event message with 'failed'.
            referenced_msg = _get_referenced_msg(msg.event, msg.unit)
            if referenced_msg:
                referenced_msg.tags += ("failed",)
                referenced_msg.exit_code = msg.exit_code

        elif "trace_id" in msg.tags:
            # the NEXT logged event of this type was traced by Tempo's trace_charm library.
            # tag the event message with the trace id.
            self._next_msg_trace_id = msg.trace_id

        elif "replay" in msg.tags:
            # the previous event of this type was replayed by jhack.
            # we log as if we emitted one.
            self._captured_logs.append(msg)

            original_evt_timestamp = msg.jhack_replayed_evt_timestamp
            original_event = None
            for msg in self._captured_logs:
                if msg.timestamp == original_evt_timestamp:
                    original_event = msg
                    break
            if original_event:
                # add tags: if the original event was jhack-fired, we don't want to lose that info.
                original_event.tags += ("jhack", "replay", "source")
            else:
                logger.debug(
                    f"original event out of scope: {original_evt_timestamp} is "
                    f"too far in the past."
                )
            msg.tags = ("jhack", "replay", "replayed")

        else:
            raise ValueError(f"unsupported jhack modifier tags: {msg.tags}")

    def process(self, log: str) -> Optional[EventLogMsg]:
        """process a log line"""
        if msg := self._match_jhack_modifiers(log):
            mode = "jhack-mod"
        elif msg := self._match_event_emitted(log):
            mode = "emit"
        elif self._show_defer:
            if msg := self._match_event_deferred(log):
                mode = "defer"
            elif msg := self._match_event_reemitted(log):
                mode = "reemit"
            else:
                return None
        else:
            return None

        if not self._is_tracking(msg.unit):
            logger.debug("skipped event as untracked")
            return None

        self._update_leader(msg)

        if mode in {"emit", "reemit"}:
            logger.debug("captured event!")
            self._captured_logs.append(msg)
        if mode == "defer":
            self._defer(msg)
        elif mode == "reemit":
            self._reemit(msg)
        elif mode == "jhack-mod":
            self._apply_jhack_mod(msg)

        if mode in {"reemit", "emit"} or (mode == "jhack-mod" and "replay" in msg.tags):
            if self._next_msg_trace_id:
                # the trace id is one of the first thing the lib logs.
                # Therefore, it actually occurs BEFORE the logline presenting the event is emitted.
                # so we have to store it and pop it when the emission event logline comes in.
                msg.trace_id = self._next_msg_trace_id
                self._next_msg_trace_id = None

        self.printer.render(
            events=self._captured_logs,
            currently_deferred=self._currently_deferred,
            leaders=self.leaders,
        )
        return msg

    def quit(self):
        self.printer.quit(self._captured_logs)

    @lru_cache()
    def _is_tracking(self, unit: str):
        if not self.targets:
            return True

        def get_app(unit_name: str):
            return unit_name.split("/")[0]

        match_app = self.add_new_units

        for target in self.targets:
            u_app = get_app(unit)
            if match_app and get_app(target) == u_app:
                return True

            # target is a unit name
            if target == unit:
                return True

            # target is an app name
            elif "/" not in target and target == u_app:
                return True

        return False

    def _update_leader(self, msg: EventLogMsg):
        if msg.event == "leader_elected":
            unit = msg.unit
            self.leaders[unit.split("/")[0]] = unit
