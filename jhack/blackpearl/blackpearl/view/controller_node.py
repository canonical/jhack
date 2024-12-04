from collections import OrderedDict

import typing
from qtpy.QtCore import Qt
from qtpy.QtGui import QPainterPath
from qtpy.QtCore import QPointF, QRectF
from qtpy.QtGui import QPen
from qtpy.QtWidgets import QWidget, QVBoxLayout, QLabel


from jhack.blackpearl.blackpearl.model.model import JujuController
from jhack.blackpearl.blackpearl.view.edges import RelationEdge, PeerRelationEdge
from jhack.blackpearl.blackpearl.view.helpers import get_color
from jhack.blackpearl.blackpearl.view.node import NodeBase, GrNodeBase
from nodeeditor.node_graphics_node import QDMGraphicsNode
from nodeeditor.node_scene import Scene
from nodeeditor.node_serializable import Serializable


class ControllerNode(NodeBase):
    def __init__(
        self,
        scene: "Scene",
        controller: "JujuController",
    ):
        self.controller = controller
        super().__init__(controller, scene, f"C.{controller.name}")
        self.edges: typing.List[RelationEdge] = []

    def add_edge(self, edge: typing.Union[RelationEdge, PeerRelationEdge]):
        # we want to know how many parallel edges there are,
        # (i.e. between the same two nodes, direction doesn't matter)
        nodes = {edge.start, edge.end}
        n_parallel_edges = len(
            tuple(e for e in self.edges if e.start in nodes and e.end in nodes)
        )

        offset = n_parallel_edges
        if n_parallel_edges % 2:
            offset = -(offset - 1)
        edge.grEdge.pather.offset = offset

        self.edges.append(edge)

    def initInnerClasses(self):
        """Sets up graphics Node (PyQt) and Content Widget"""
        self.grNode = ControllerGraphicsNode(self)

    def setPos(self, x: float, y: float):
        self.grNode.setPos(x, y)
        for edge in self.edges:
            edge.update()

    def updateConnectedEdges(self):
        """Recalculate (Refresh) positions of all connected `Edges`. Used for updating Graphics Edges"""
        for edge in self.edges:
            edge.update()


class ControllerGraphicsNode(GrNodeBase):
    node: "ControllerNode"

    def __init__(self, node: "ControllerNode", parent: QWidget = None):
        self.radius = 1000

        # needed for parent class
        self.width = 180
        self.height = 90
        self.edge_roundness = 10.0
        self.edge_padding = 10
        self.title_height = 24
        self.title_horizontal_padding = 4.0
        self.title_vertical_padding = 4.0

        super().__init__(node, parent)
        # node inherits model color
        self._color = get_color(node.controller.ui_color)
        self._pen_default = QPen(self._color)

    def update_size(self):
        # sum the radia of the model nodes to find out our own
        tot_child_radia = sum(child.grNode.radius for child in self.node.bound_children)
        self.radius = max(500, tot_child_radia)

    def initSizes(self):
        pass

    @property
    def center(self):
        # center is in local coordinates
        return self.boundingRect().center()

    def paint(self, painter, QStyleOptionGraphicsItem, widget=None):
        """Painting the hex `Node`"""
        # outline
        path_outline = QPainterPath()
        path_outline.addEllipse(0, 0, self.radius + 1, self.radius + 1)

        painter.setBrush(Qt.NoBrush)
        if self.hovered:
            painter.setPen(self._pen_hovered)
            painter.drawPath(path_outline.simplified())
            painter.setPen(self._pen_default)
            painter.drawPath(path_outline.simplified())
        else:
            painter.setPen(
                self._pen_default if not self.isSelected() else self._pen_selected
            )
            painter.drawPath(path_outline.simplified())
