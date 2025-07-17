import re
from typing import Dict, Any, Optional
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild(__file__)


class LogLineParser:
    jdl_root_pattern = (
        r"^(?P<pod_name>\S+): (?P<timestamp>\S+(\s*\S+)?) (?P<loglevel>\S+) "
        r"unit\.(?P<unit>\S+)\.juju-log "
    )
    # the data platform team decided to mess with the root logger and add a `module_name:`
    # prefix to all their juju debug-logs. Then they opened a bug because jhack tail broke.
    # I fixed it thinking it was a VM/k8s divergence bug, but turns out it really is their fault.
    # keeping this not to break any promises, but this isn't scalable and further changes won't be
    # supported unless they're led by ops (or Alex Lutay applies enough flattery).
    _optional_prefix = "(\S+)?( )?"
    base_pattern = jdl_root_pattern + _optional_prefix

    base_relation_pattern = (
        base_pattern + "(?P<endpoint>\S+):(?P<endpoint_id>\S+): " + _optional_prefix
    )

    operator_event_suffix = "Charm called itself via hooks/(?P<event>\S+)\."
    operator_event = re.compile(base_pattern + operator_event_suffix)

    event_suffix = "Emitting Juju event (?P<event>\S+)\."
    event_emitted = re.compile(base_pattern + event_suffix)
    event_emitted_from_relation = re.compile(base_relation_pattern + event_suffix)

    # modifiers
    jhack_fire_evt_suffix = "The previous (?P<event>\S+) was fired by jhack\."
    event_fired_jhack = re.compile(base_pattern + jhack_fire_evt_suffix)
    jhack_replay_evt_suffix = (
        "(?P<event>\S+) \((?P<jhack_replayed_evt_timestamp>\S+(\s*\S+)?)\) was replayed by jhack\."
    )
    event_replayed_jhack = re.compile(base_pattern + jhack_replay_evt_suffix)

    event_repr = r"<(?P<event_cls>\S+) via (?P<charm_name>\S+)/on/(?P<event>\S+)\[(?P<n>\d+)\]>\."
    defer_suffix = "Deferring " + event_repr
    event_deferred = re.compile(base_pattern + defer_suffix)
    event_deferred_from_relation = re.compile(base_relation_pattern + defer_suffix)

    # unit-tempo-0: 12:28:24 DEBUG unit.tempo/0.juju-log Starting root trace with id=XXX.
    # we ignore the relation tag since we don't really care with modifier loglines
    trace_id = re.compile(
        base_pattern + "(.* )?" + r"Starting root trace with id='(?P<trace_id>\S+)'\."
    )

    custom_event_suffix = "Emitting custom event " + event_repr
    custom_event = re.compile(base_pattern + custom_event_suffix)  # ops >= 2.1
    custom_event_from_relation = re.compile(
        base_relation_pattern + custom_event_suffix
    )  # ops >= 2.1

    reemitted_suffix_old = "Re-emitting " + event_repr  # ops < 2.1
    event_reemitted_old = re.compile(base_pattern + reemitted_suffix_old)
    event_reemitted_from_relation_old = re.compile(base_relation_pattern + reemitted_suffix_old)

    reemitted_suffix_new = "Re-emitting deferred event " + event_repr  # ops >= 2.1
    event_reemitted_new = re.compile(base_pattern + reemitted_suffix_new)
    event_reemitted_from_relation_new = re.compile(base_relation_pattern + reemitted_suffix_new)

    lobotomy_suffix = "(?:selective|full) lobotomy ACTIVE: event hooks\/(?P<event>\S+) ignored."
    lobotomy_skipped_event = re.compile(base_pattern + lobotomy_suffix)

    uniter_operation_prefix = (
        r"^unit-(?P<unit_name>\S+)-(?P<unit_number>\d+): (?P<timestamp>\S+( \S+)?) "
        r"(?P<loglevel>\S+) juju\.worker\.uniter\.operation "
    )
    uniter_event_ran_suffix = (
        r'ran "(?P<event>\S+)" hook \(via hook dispatching script: dispatch\)'
    )
    uniter_event = re.compile(uniter_operation_prefix + uniter_event_ran_suffix)

    event_failed_suffix = (
        r"hook \"(?P<event>\S+)\" \(via hook dispatching script: dispatch\) "
        r"failed: exit status (?P<exit_code>\S+)"
    )
    event_failed = re.compile(uniter_operation_prefix + event_failed_suffix)

    uniter_debug_hooks_evt = re.compile(
        r"^unit-(?P<unit_name>\S+)-(?P<unit_number>\d+): (?P<timestamp>\S+( \S+)?) "
        r"(?P<loglevel>\S+) juju\.worker\.uniter\.runner executing (?P<event>\S+) via debug-hooks; "
        r"hook dispatching script: dispatch"
    )

    tags = {
        operator_event: ("operator",),
        event_fired_jhack: ("jhack", "fire"),
        lobotomy_skipped_event: ("jhack", "lobotomy"),
        event_replayed_jhack: ("jhack", "replay"),
        custom_event: ("custom",),
        custom_event_from_relation: ("custom",),
        trace_id: ("trace_id",),
        event_failed: ("failed",),
    }

    def __init__(
        self,
        capture_operator_events: bool = False,
    ):
        self._capture_operator_events = capture_operator_events
        # initially, we assume we'll only receive uniter events (because the loglevel is WARNING)
        self._uniter_events_only = True

    @staticmethod
    def _sanitize_match_dict(dct: Dict[str, str]):
        out: Dict[str, Any] = dct.copy()
        out["event"] = out.get("event", "").replace("-", "_")

        if ec := out.get("exit_code"):
            out["exit_code"] = int(ec)

        if "unit_name" in out and "unit_number" in out:
            unit = out.pop("unit_name")
            n = out.pop("unit_number")
            out["pod_name"] = f"{unit}-{n}"
            out["unit"] = f"{unit}/{n}"

        if "date" in out:
            del out["date"]
        return out

    def _match(self, msg, *matchers) -> Optional[Dict[str, Any]]:
        if not matchers:
            raise ValueError("no matchers provided")

        for matcher in matchers:
            if match := matcher.match(msg):
                dct: Dict[str, Any] = self._sanitize_match_dict(match.groupdict())
                dct["tags"] = self.tags.get(matcher, ())
                if self._uniter_events_only and dct.get("loglevel") in {
                    "DEBUG",
                    "TRACE",
                }:
                    logger.debug("uniter-only set to False")
                    self._uniter_events_only = False

                return dct
        return None

    def match_event_deferred(self, msg):
        if self._uniter_events_only:
            return None
        return self._match(msg, self.event_deferred, self.event_deferred_from_relation)

    def match_event_emitted(self, msg):
        if match := self._match(msg, self.lobotomy_skipped_event):
            return match

        if self._uniter_events_only:
            return self._match(
                msg,
                self.uniter_event,
                self.uniter_debug_hooks_evt,
                self.event_emitted,  # give it a chance
            )

        matchers = [
            # self.uniter_event,
            # self.uniter_debug_hooks_evt,
            self.event_emitted,
            self.lobotomy_skipped_event,
            self.event_emitted_from_relation,
            self.custom_event,
            self.custom_event_from_relation,
        ]
        if self._capture_operator_events:
            # the obscure "charm called itself via..." logline
            matchers.append(self.operator_event)

        return self._match(msg, *matchers)

    def match_modifiers(self, msg, trace_id: bool = False):
        # matches certain loglines that modify the meaning of previously parsed loglines.
        # some may also be emitted by jhack, for example fire/replay
        mods = [self.event_failed]
        if not self._uniter_events_only:
            mods.extend((self.event_fired_jhack, self.event_replayed_jhack))
            if trace_id:
                # don't search for trace ids unless they are enabled
                mods.append(self.trace_id)
        match = self._match(msg, *mods)
        return match

    def match_event_reemitted(self, msg):
        if self._uniter_events_only:
            return None
        return self._match(
            msg,
            self.event_reemitted_old,
            self.event_reemitted_from_relation_old,
            self.event_reemitted_new,
            self.event_reemitted_from_relation_new,
        )
