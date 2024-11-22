from collections import OrderedDict
from typing import Union

import math
import typing
from enum import Enum
from nodeeditor.node_scene import Scene
from nodeeditor.node_serializable import Serializable
from qtpy.QtCore import Qt, QRectF, QPointF
from qtpy.QtGui import QColor, QPen, QPainterPath
from qtpy.QtWidgets import (
    QGraphicsPathItem,
    QWidget,
    QGraphicsItem,
    QGraphicsSimpleTextItem,
)

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.view.helpers import get_color
from jhack.utils.helpers.gather_endpoints import RelationBinding, PeerBinding

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.view.nodes import Node, AppNode

logger = bp_logger.getChild(__file__)


class EdgeType(Enum):
    DIRECT = 1  #:
    BEZIER = 2  #:
    SQUARE = 3  #:
    IMPROVED_SHARP = 4  #:
    IMPROVED_BEZIER = 5  #:


class Edge(Serializable):
    """
    Class for representing Edge in NodeEditor.
    """

    binding: typing.Union[RelationBinding, PeerBinding]

    def __repr__(self):
        return self.tooltip

    def __init__(
        self,
        scene: "Scene",
    ):
        super().__init__()
        self.scene = scene

        # create Graphics Edge instance
        self.grEdge = GraphicsEdge(self)
        self.scene.addEdge(self)
        self.scene.grScene.addItem(self.grEdge)

        for label in self.grEdge.labels:
            label.hide()  # begin hidden
            self.scene.grScene.addItem(label)

        self.update()

    @property
    def tooltip(self):
        return "n/a"

    def get_other(self, known: "Node"):
        return self.start if known == self.end else self.end

    def update(self):
        self.grEdge.set_source(self.start.center)
        self.grEdge.set_destination(self.end.center)
        self.grEdge.update()

    def remove(self, silent=False):
        ends = [self.start, self.end]
        self.start = None
        self.end = None

        self.grEdge.hide()
        self.scene.grScene.removeItem(self.grEdge)
        self.scene.grScene.update()

        try:
            self.scene.removeEdge(self)
        except ValueError:
            pass

        for end in ends:
            if silent:
                continue
            try:
                end.onEdgeConnectionChanged(self)
            except Exception as e:
                logger.exception(f"failed to notify node {end} that {self} is going")

    def serialize(self) -> OrderedDict:
        return OrderedDict(
            [
                ("id", self.id),
                ("start", self.start.id if self.start is not None else None),
                ("end", self.end.id if self.end is not None else None),
            ]
        )

    def deserialize(
        self, data: dict, hashmap: dict = {}, restore_id: bool = True, *args, **kwargs
    ) -> bool:
        if restore_id:
            self.id = data["id"]
        self.start = hashmap[data["start"]]
        self.end = hashmap[data["end"]]
        return True


class RelationEdge(Edge):
    def __init__(
        self, scene: "Scene", binding: RelationBinding, start: "AppNode", end: "AppNode"
    ):
        self.binding = binding
        self.start = start
        self.end = end
        super().__init__(scene)

    @property
    def tooltip(self):
        binding = self.binding
        return f"<{binding.provider_endpoint} -- [{binding.interface}] --> {binding.requirer_endpoint}>"


class PeerRelationEdge(Edge):
    def __init__(
        self,
        scene: "Scene",
        binding: PeerBinding,
        node: "Node",
    ):
        self.binding = binding
        self.start = node
        self.end = node
        super().__init__(scene)

    @property
    def tooltip(self):
        return f"<{self.binding.provider_endpoint} <-- [{self.binding.interface}]>"


class DirectPath:
    def __init__(self, owner: "GraphicsEdge", start: "AppNode", end: "AppNode"):
        self.owner = owner
        self.start = start
        self.end = end

    def path(self) -> QPainterPath:
        """Calculate the Direct line connection

        :returns: ``QPainterPath`` of the direct line
        :rtype: ``QPainterPath``
        """
        path = QPainterPath(QPointF(self.owner.source[0], self.owner.source[1]))
        path.lineTo(self.owner.destination[0], self.owner.destination[1])
        return path


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


class GraphicsEdge(QGraphicsPathItem):
    def __init__(
        self, edge: "Union[RelationEdge, PeerRelationEdge]", parent: QWidget = None
    ):
        super().__init__(parent)

        self.edge = edge

        # create instance of our path class
        self.pather = DirectPath(self, edge.start, edge.end)

        # init our flags
        self._last_selected_state = False
        self.hovered = False

        # init our variables
        self.source = [0, 0]
        self.destination = [200, 100]

        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

        self.setZValue(-1)
        self.setToolTip(edge.tooltip)

        self._color = self._default_color = get_color("white")
        self._color_selected = get_color("coral")
        self._color_annotation = get_color("azure1")
        self._color_hovered = QColor("darkorange")
        self._pen = QPen(self._color)
        self._pen_selected = QPen(self._color_selected)
        self._pen_hovered = QPen(self._color_hovered)
        self._pen_annotation = QPen(self._color_annotation)
        self._pen.setWidthF(1.0)
        self._pen_selected.setWidthF(2.0)
        self._pen_hovered.setWidthF(3.0)

        binding = self.edge.binding

        self.labels = [
            QGraphicsSimpleTextItem(binding.provider_endpoint),
            QGraphicsSimpleTextItem(binding.interface),
        ]
        self._label_positions = (0, 0.5, 1)

        if hasattr(binding, "requirer_endpoint"):
            # regular relation
            self.labels.append(QGraphicsSimpleTextItem(binding.requirer_endpoint))

    def show_labels(self):
        for label in self.labels:
            label.show()

    def hide_labels(self):
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
            self.edge.scene.resetLastSelectedStates()
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
        self.setPath(self.path())

        painter.setBrush(Qt.NoBrush)

        if self.hovered:
            pen = self._pen_hovered
        elif self.isSelected():
            pen = self._pen_selected
        else:
            pen = self._pen

        painter.setPen(pen)
        painter.drawPath(self.path())

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
        """Will handle drawing QPainterPath from Point A to B. Internally there exist self.pather which
        is an instance of derived :class:`~nodeeditor.node_graphics_edge_path.GraphicsEdgePathBase` class
        containing the actual `path()` function - computing how the edge should look like.

        :returns: ``QPainterPath`` of the edge connecting `source` and `destination`
        :rtype: ``QPainterPath``
        """
        return self.pather.path()

    def _update_label_positions(self):
        path = self.path()

        for label, relpos in zip(self.labels, self._label_positions):
            # label.setTransformOriginPoint()
            label.setPos(path.pointAtPercent(relpos))
            label.setRotation(path.angleAtPercent(relpos))
