import random
import typing

from rich.color import Color

from jhack.utils.tail_charms.core.deferral_status import DeferralStatus

if typing.TYPE_CHECKING:
    from jhack.utils.tail_charms.core.processor import EventLogMsg


def _random_color():
    r = random.randint(0, 255)
    g = random.randint(0, 255)
    b = random.randint(0, 255)
    return Color.from_rgb(r, g, b)


event_colors_by_category = {
    "lifecycle": {
        "_action": Color.from_rgb(200, 200, 50),
        "stop": Color.from_rgb(184, 26, 71),
        "remove": Color.from_rgb(171, 81, 21),
        "start": Color.from_rgb(20, 147, 186),
        "install": Color.from_rgb(49, 183, 224),
        "update_status": Color.from_rgb(150, 150, 50),
        "collect_metrics": Color.from_rgb(50, 50, 50),
        "leader_elected": Color.from_rgb(26, 184, 68),
        "leader_settings_changed": Color.from_rgb(26, 184, 68),
    },
    "relation": {
        "_relation_created": Color.from_rgb(184, 26, 250),
        "_relation_joined": Color.from_rgb(184, 26, 230),
        "_relation_changed": Color.from_rgb(184, 26, 210),
        "_relation_departed": Color.from_rgb(184, 70, 190),
        "_relation_broken": Color.from_rgb(184, 80, 170),
    },
    "secrets": {
        "secret_changed": Color.from_rgb(10, 80, 240),
        "secret_expired": Color.from_rgb(10, 100, 250),
        "secret_remove": Color.from_rgb(10, 120, 230),
        "secret_rotate": Color.from_rgb(10, 140, 220),
    },
    "storage": {
        "_storage_attached": Color.from_rgb(184, 139, 26),
        "_storage_detaching": Color.from_rgb(184, 139, 26),
    },
    "workload": {
        "_pebble_ready": Color.from_rgb(212, 224, 40),
        "_pebble_custom_notice": Color.from_rgb(212, 210, 40),
        "_pebble_check_failed": Color.from_rgb(212, 200, 40),
        "_pebble_check_recovered": Color.from_rgb(212, 190, 40),
    },
}
_event_colors = {}
for sublist in event_colors_by_category.values():
    _event_colors.update(sublist)

header_bgcolor = Color.from_rgb(70, 70, 70)
last_event_bgcolor = Color.from_rgb(50, 50, 50)
alternate_row_bgcolor = Color.from_rgb(30, 30, 30)
default_event_color = Color.from_rgb(255, 255, 255)
_default_n_color = Color.from_rgb(255, 255, 255)
tstamp_color = Color.from_rgb(255, 160, 120)
operator_event_color = Color.from_rgb(252, 115, 3)
custom_event_color = Color.from_rgb(120, 150, 240)
_jhack_event_color = Color.from_rgb(200, 200, 50)
jhack_fire_event_color = Color.from_rgb(250, 200, 50)
jhack_lobotomy_event_color = Color.from_rgb(150, 210, 110)
jhack_replay_event_color = Color.from_rgb(100, 100, 150)
deferral_colors = {
    DeferralStatus.null: "",
    DeferralStatus.deferred: "red",
    DeferralStatus.reemitted: "green",
    DeferralStatus.bounced: Color.from_rgb(252, 115, 3),
}

trace_id_color = Color.from_rgb(100, 100, 210)


def get_event_color(event: "EventLogMsg") -> Color:
    """Color-code the events as they are displayed to make reading them easier."""
    # If we have a log message to start from, use any relevant tags to determine what type of event it is
    if "custom" in event.tags:
        return custom_event_color
    if "operator" in event.tags:
        return operator_event_color
    if "jhack" in event.tags:
        if "fire" in event.tags:
            return jhack_fire_event_color
        elif "replay" in event.tags:
            return jhack_replay_event_color
        elif "lobotomy" in event.tags:
            return jhack_lobotomy_event_color
        return _jhack_event_color

    # if we are coloring an event without tags,
    # use the event-specific color coding.
    if event.event in _event_colors:
        return _event_colors.get(event.event, default_event_color)
    else:
        for _e in _event_colors:
            if event.event.endswith(_e):
                return _event_colors[_e]
    return default_event_color
