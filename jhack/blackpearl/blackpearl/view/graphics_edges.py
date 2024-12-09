import math
import typing
from typing import Union

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QPen, QPainterPath, QPolygonF
from PyQt6.QtWidgets import (
    QGraphicsPathItem,
    QWidget,
    QGraphicsItem,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)

from jhack.blackpearl.blackpearl.view import zvalues
from jhack.blackpearl.blackpearl.view.helpers import get_color, translated

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.view.edges import (
        RelationEdge,
        PeerRelationEdge,
        CMREdge,
    )
    from jhack.blackpearl.blackpearl.view.app_node import AppNode


class GraphicsEdge(QGraphicsPathItem):
    _styles = {
        "color": "white",
        "color_selected": "coral",
        "color_annotation": "azure1",
        "color_hovered": "darkorange",
        "width": 1.0,
        "width_selected": 2.0,
        "width_hovered": 3.0,
        "style": Qt.SolidLine,
    }

    def __init__(
        self,
        edge: "Union[RelationEdge, PeerRelationEdge, CMREdge]",
        parent: QWidget = None,
    ):
        super().__init__(parent)

        self.edge = edge

        # create instance of our path class
        self.pather = DirectPath(self, edge.start, edge.end)

        # init our flags
        self._last_selected_state = False
        self.hovered = False
        self.show_direction = True

        # init our variables
        self.source = [0, 0]
        self.destination = [0, 0]

        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

        self.setZValue(zvalues.edges)
        self.setToolTip(edge.tooltip)
        self.set_style(**self._styles)

        binding = self.edge.binding

        self.labels = [
            RelationEndpointGraphicsLabel(binding.provider_endpoint),
            RelationInterfaceGraphicsLabel(binding.interface),
        ]
        self._label_positions = (0.1, 0.4, 0.7)

        if hasattr(binding, "requirer_endpoint"):
            # regular relation
            self.labels.append(RelationEndpointGraphicsLabel(binding.requirer_endpoint))

    def set_style(
        self,
        color="white",
        color_selected="coral",
        color_annotation="azure1",
        color_hovered="darkorange",
        width=1.0,
        width_selected=2.0,
        width_hovered=3.0,
        style=Qt.SolidLine,
    ):
        self._color = get_color(color)
        self._color_selected = get_color(color_selected)
        self._color_annotation = get_color(color_annotation)
        self._color_hovered = QColor(color_hovered)
        self._pen = QPen(self._color)
        self._pen_selected = QPen(self._color_selected)
        self._pen_hovered = QPen(self._color_hovered)
        self._pen_annotation = QPen(self._color_annotation)

        self._pen.setWidthF(width)
        self._pen.setStyle(style)
        self._pen_selected.setWidthF(width_selected)
        self._pen_hovered.setWidthF(width_hovered)

    def update(self, *__args):
        super().update(*__args)
        if self.isSelected() or self.hovered:
            for label in self.labels:
                label.show()
        else:
            for label in self.labels:
                label.hide()

    def set_color(self, color):
        """Change color of the edge from string hex value '#00ff00'"""
        # print("^Called change color to:", color.red(), color.green(), color.blue(), "on edge:", self.edge)
        self._color = QColor(color) if type(color) == str else color
        self._pen = QPen(self._color)
        self._pen.setWidthF(3.0)

    def onSelected(self):
        """Our event handling when the edge was selected"""
        self.edge.scene.grScene.itemSelected.emit()

    def doSelect(self, new_state: bool = True):
        """Safe version of selecting the `Graphics Node`. Takes care about the selection state flag used internally

        :param new_state: ``True`` to select, ``False`` to deselect
        :type new_state: ``bool``
        """
        self.setSelected(new_state)
        self._last_selected_state = new_state
        if new_state:
            self.onSelected()

    def mouseReleaseEvent(self, event):
        """Overridden Qt's method to handle selecting and deselecting this `Graphics Edge`"""
        super().mouseReleaseEvent(event)
        if self._last_selected_state != self.isSelected():
            self.edge.scene.reset_last_selected_state()
            self._last_selected_state = self.isSelected()
            self.onSelected()

    def hoverEnterEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        """Handle hover effect"""
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        """Handle hover effect"""
        self.hovered = False
        self.update()

    def set_source(self, pos: QPointF):
        self.source = [pos.x(), pos.y()]
        self._update_label_positions()

    def set_destination(self, pos: QPointF):
        self.destination = [pos.x(), pos.y()]
        self._update_label_positions()

    def boundingRect(self) -> QRectF:
        """Defining Qt' bounding rectangle"""
        return self.shape().boundingRect()

    def shape(self) -> QPainterPath:
        """Returns ``QPainterPath`` representation of this `Edge`

        :return: path representation
        :rtype: ``QPainterPath``
        """
        return self.path()

    def paint(self, painter, QStyleOptionGraphicsItem, widget=None):
        """Qt's overridden method to paint this Graphics Edge. Path calculated
        in :func:`~nodeeditor.node_graphics_edge.QDMGraphicsEdge.path` method"""
        path = self.path()

        painter.setRenderHint(painter.Antialiasing)
        painter.setBrush(Qt.NoBrush)

        if self.hovered:
            pen = self._pen_hovered
        elif self.isSelected():
            pen = self._pen_selected
        else:
            pen = self._pen

        painter.setPen(pen)
        painter.drawPath(path)
        self.setPath(path)
        try:
            arrows = self.get_arrow(path.pointAtPercent(0.5), path.pointAtPercent(0.51))
            painter.drawPolyline(arrows)
        except ZeroDivisionError:
            pass

    def get_arrow(self, start_point, end_point):
        arrow_width = 4
        arrow_height = 5
        sx, sy = start_point.x(), start_point.y()
        ex, ey = end_point.x(), end_point.y()

        dx, dy = sx - ex, sy - ey

        leng = math.sqrt(dx**2 + dy**2)
        normX, normY = dx / leng, dy / leng  # normalize

        # perpendicular vectors
        perpX = -normY
        perpY = normX

        point2 = QPointF(
            ex + arrow_height * normX + arrow_width * perpX,
            ey + arrow_height * normY + arrow_width * perpY,
        )
        point3 = QPointF(
            ex + arrow_height * normX - arrow_width * perpX,
            ey + arrow_height * normY - arrow_width * perpY,
        )

        return QPolygonF([point2, end_point, point3])

    def intersectsWith(self, p1: QPointF, p2: QPointF) -> bool:
        """Does this Graphics Edge intersect with the line between point A and point B ?

        :param p1: point A
        :type p1: ``QPointF``
        :param p2: point B
        :type p2: ``QPointF``
        :return: ``True`` if this `Graphics Edge` intersects
        :rtype: ``bool``
        """
        cutpath = QPainterPath(p1)
        cutpath.lineTo(p2)
        path = self.path()
        return cutpath.intersects(path)

    def path(self) -> QPainterPath:
        return self.pather.path()

    def _update_label_positions(self):
        path = self.path()

        for label, relpos in zip(self.labels, self._label_positions):
            # anchor at center
            label.setPos(path.pointAtPercent(relpos))
            label.setRotation(-path.angleAtPercent(relpos))


class CMRGraphicsEdge(GraphicsEdge):
    _styles = {
        "color": "blue1",
        "color_selected": "coral",
        "color_annotation": "azure1",
        "color_hovered": "darkorange",
        "width": 1.0,
        "width_selected": 2.0,
        "width_hovered": 3.0,
        "style": Qt.DashLine,
    }


class PeerRelationGraphicsEdge(GraphicsEdge):
    _styles = {
        "color": "white",
        "color_selected": "coral",
        "color_annotation": "azure1",
        "color_hovered": "darkorange",
        "width": 1.0,
        "width_selected": 2.0,
        "width_hovered": 3.0,
        "style": Qt.DotLine,
    }


class DirectPath:
    def __init__(
        self, owner: "GraphicsEdge", start: "AppNode", end: "AppNode", offset: int = 0
    ):
        self.owner = owner
        self.start = start
        self.end = end
        # offset to separate parallel edges in case of multiple relations
        self.offset = offset
        self.arrows = True

    def path(self) -> QPainterPath:
        path = QPainterPath(QPointF(self.owner.source[0], self.owner.source[1]))
        path.lineTo(self.owner.destination[0], self.owner.destination[1])

        angle = math.radians(180 + path.angleAtPercent(0))
        dist = 10 * self.offset
        path.translate(math.sin(angle) * dist, math.cos(angle) * dist)
        return path


class Arrow(QPolygonF):
    def __init__(self, center: QPointF, direction: float, length: float, width: float):
        super().__init__()
        self.center = center
        self.direction = direction
        self.length = length

        tip = translated(center, direction, length)
        p1_l = translated(center, direction + 180, width / 2)
        p2_r = translated(center, direction - 90, width / 2)

        self.append(tip)
        self.append(p1_l)
        self.append(p2_r)
        self.append(tip)


class CenteredBezierPath:
    """Better Cubic line connection Graphics Edge"""

    EDGE_CP_ROUNDNESS = 100  #: Bezier control point distance on the line
    WEIGHT_SOURCE = 0.2  #: factor for square edge to change the midpoint between start and end socket

    EDGE_IBCP_ROUNDNESS = (
        75  #: Scale EDGE_CURVATURE with distance of the edge endpoints
    )
    NODE_DISTANCE = 12
    EDGE_CURVATURE = 2

    def __init__(self, owner: "GraphicsEdge"):
        self.owner = owner

    def path(self) -> QPainterPath:
        """Calculate the Direct line connection

        :returns: ``QPainterPath`` of the painting line
        :rtype: ``QPainterPath``
        """
        sx, sy = self.owner.source
        dx, dy = self.owner.destination
        distx, disty = dx - sx, dy - sy
        dist = math.sqrt(distx * distx + disty * disty)

        path = QPainterPath(QPointF(sx, sy))

        if abs(dist) > self.NODE_DISTANCE:
            curvature = max(
                self.EDGE_CURVATURE,
                (self.EDGE_CURVATURE * abs(dist)) / self.EDGE_IBCP_ROUNDNESS,
            )

            path.lineTo(sx, sy)

            path.cubicTo(
                QPointF(sx * curvature, sy),
                QPointF(dx * curvature, dy),
                QPointF(dx, dy),
            )

            path.lineTo(dx, dy)

        path.lineTo(dx, dy)

        return path


LABEL_BGCOLOR = get_color("dimgray")


class RelationGraphicsLabel(QGraphicsSimpleTextItem):
    @property
    def path(self):
        path = QPainterPath()
        boundingrect = self.boundingRect()
        path.addRoundedRect(
            -3,
            -1,
            boundingrect.width() + 6,
            boundingrect.height() + 2,
            10,
            10,
        )
        return path

    def paint(self, painter, option, widget):
        painter.setBrush(LABEL_BGCOLOR)
        painter.drawPath(self.path)
        super().paint(painter, option, widget)


class RelationEndpointGraphicsLabel(RelationGraphicsLabel):
    pass


class RelationInterfaceGraphicsLabel(RelationGraphicsLabel):
    _padding = 2

    @property
    def path(self):
        path = QPainterPath()
        boundingrect = self.boundingRect()
        h, w = boundingrect.height(), boundingrect.width()
        cursor = boundingrect.topLeft()
        poly = QPolygonF()

        for transform in (
            QPointF(-2, -2),  # initial point
            QPointF(w, 0),
            QPointF(10, h / 2 + 2),  # arrowtip
            QPointF(-10, h / 2 + 2),
            QPointF(-w, 0),
            QPointF(0, -h - 2),
        ):
            cursor += transform
            poly.append(cursor)

        path.addPolygon(poly)
        return path
