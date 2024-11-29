# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from urllib import request

import math
import typing
from PyQt6.QtGui import QImage
from pathlib import Path
from qtpy.QtCore import QPointF
from qtpy.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from qtpy.QtSvg import QSvgRenderer
from qtpy.QtWidgets import QMessageBox, QWidget
from typing import Optional

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.view.resources.x11_colors import X11_COLORS

RESOURCES_DIR = Path(__file__).parent / "resources"
logger = bp_logger.getChild("helpers")

ColorType = typing.Union[str, typing.Tuple[int, int, int]]
DEFAULT_ICON_PIXMAP_RESOLUTION = 100
CUSTOM_COLORS = {
    # state node icon
    "invalid": (138, 0, 0),
    "pastel green": (138, 255, 153),
    "pastel orange": (255, 185, 64),
    "pastel red": (245, 96, 86),
    # event edge colors
    "relation event": "#D474AF",
    "secret event": "#A9FAC8",
    "storage event": "#EABE8C",
    "workload event": "#87F6D3",
    "builtin event": "#96A1F6",
    "leader event": "#C6D474",
    "generic event": "#D6CA51",
    "update-status": "#4a708b",  # x11's skyblue4
}


def get_color(color: ColorType):
    if isinstance(color, QColor):
        return color
    elif isinstance(color, tuple):
        return QColor(*color)
    elif isinstance(color, str):
        for db in (CUSTOM_COLORS, X11_COLORS):
            if mapped_color := db.get(color, None):
                return (
                    QColor(mapped_color)
                    if isinstance(mapped_color, str)
                    else QColor(*mapped_color)
                )
    raise RuntimeError(f"invalid input: unable to map {color} to QColor.")


class Color(QWidget):
    def __init__(self, color):
        super(Color, self).__init__()
        self.setAutoFillBackground(True)

        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(color))
        self.setPalette(palette)


def show_error_dialog(
    parent, message: str, title="Whoopsiedaisies!", choices=QMessageBox.Ok
):
    return QMessageBox.critical(parent, title, message, choices)


def colorized(name: str, color: QColor, res: int = 500):
    path = RESOURCES_DIR / "icons" / name
    filename = path.with_suffix(".svg")
    renderer = QSvgRenderer(str(filename.absolute()))
    orig_svg = QImage(res, res, QImage.Format_ARGB32)
    painter = QPainter(orig_svg)

    renderer.render(painter)
    img_copy = orig_svg.copy()
    painter.end()

    painter.begin(img_copy)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(img_copy.rect(), color)
    painter.end()
    pxmp = QPixmap.fromImage(img_copy)
    return QIcon(pxmp)


def download_icon(name: str, filename: Path, opsz=24):
    """Atttempt to download material icon."""
    url = f"https://fonts.gstatic.com/s/i/short-term/release/materialsymbolsoutlined/{name}/default/{opsz}px.svg"
    out = request.urlopen(url).read()
    filename.write_bytes(out)
    logger.info(f"auto-downloaded material icon {name}")


def get_icon(
    name: str, color: Optional[ColorType] = None, path=("icons",), suffix: str = "svg"
) -> QIcon:
    if color:
        return colorized(name, get_color(color))

    path = RESOURCES_DIR.joinpath(*path) / name
    filename = path.with_suffix(f".{suffix}")

    if not filename.exists():
        try:
            download_icon(name, filename)
        except request.HTTPError:
            logger.error(f"material icon {name} could not be downloaded")
            return get_icon("bolt")

    abspath_str = str(filename.absolute())
    return QIcon(abspath_str)


_EVENT_SUFFIX_TO_ICON_NAME = {
    # lifecycle events
    "start": "start",
    "install": "download",
    "config_changed": "instant_mix",
    "stop": "close",
    "remove": "delete",
    "leader_elected": "footprint",
    "leader_settings_changed": "barefoot",
    "post_series_upgrade": "system_update_alt",
    "pre_series_upgrade": "system_update_alt",
    "update_status": "update",
    "upgrade_charm": "work_update",
    # storage events
    "storage_attached": "cloud_done",
    "storage_detaching": "thunderstorm",
    # secret events
    "secret_changed": "lock",
    "secret_rotate": "lock_reset",
    "secret_removed": "no_encryption",
    "secret_expired": "timer_off",
    # relation events
    "relation_joined": "join",
    "relation_broken": "heart_broken",
    "relation_departed": "flight_takeoff",
    "relation_created": "heart_plus",
    "relation_changed": "tune",
    # workload events
    "pebble_ready": "package_2",
}
_DEFAULT_EVENT_ICON_NAME = "line_start"


def get_event_icon(event_name: str):
    """Helper to obtain icons for events."""
    bare = _EVENT_SUFFIX_TO_ICON_NAME.get(event_name)
    if bare:
        return get_icon(bare)

    suffix = "_".join(event_name.split("_")[-2:])
    return get_icon(_EVENT_SUFFIX_TO_ICON_NAME.get(suffix, _DEFAULT_EVENT_ICON_NAME))


def translated(pt: QPointF, angle: float, distance: float) -> QPointF:
    radians = math.radians(angle)
    return pt + QPointF(math.sin(radians) * distance, math.cos(radians) * distance)
