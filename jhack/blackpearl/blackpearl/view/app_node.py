from collections import OrderedDict

import typing
from qtpy.QtCore import QPointF
from qtpy.QtGui import QPen
from qtpy.QtWidgets import QWidget, QVBoxLayout, QLabel

from jhack.blackpearl.blackpearl.model.model import JujuApp
from jhack.blackpearl.blackpearl.view.edges import RelationEdge, PeerRelationEdge
from jhack.blackpearl.blackpearl.view.helpers import get_color
from jhack.blackpearl.blackpearl.view.node import NodeBase, GrNodeBase
from jhack.blackpearl.nodeeditor.node_graphics_node import QDMGraphicsNode
from jhack.blackpearl.nodeeditor.node_scene import Scene
from jhack.blackpearl.nodeeditor.node_serializable import Serializable


if typing.TYPE_CHECKING:
    from jhack.blackpearl.nodeeditor.node_scene import Scene
    from jhack.blackpearl.blackpearl.model.model import JujuApp


class AppNode(NodeBase):
    def __init__(
        self,
        scene: "Scene",
        app: "JujuApp",
    ):
        self.app = app
        super().__init__(app, scene, app.name)
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
        self.content = AppNodeContentWidget(self)
        self.grNode = AppGraphicsNode(self)

    def setPos(self, x: float, y: float):
        self.grNode.setPos(x, y)
        for edge in self.edges:
            edge.update()

    def updateConnectedEdges(self):
        """Recalculate (Refresh) positions of all connected `Edges`. Used for updating Graphics Edges"""
        for edge in self.edges:
            edge.update()


class AppGraphicsNode(GrNodeBase):
    def __init__(self, node: "AppNode", parent: QWidget = None):
        self.width = 180
        self.height = 90
        self.edge_roundness = 10.0
        self.edge_padding = 10
        self.title_height = 24
        self.title_horizontal_padding = 4.0
        self.title_vertical_padding = 4.0

        super().__init__(node, parent)
        # node inherits model color
        self._color = get_color(node.app.model.ui_color)
        self._pen_default = QPen(self._color)

    def initSizes(self):
        pass

    @property
    def center(self):
        return self.pos() + QPointF(self.width / 2, self.height / 2)

    def onSelected(self):
        super().onSelected()
        for edge in self.node.edges:
            edge.grEdge.setSelected(True)
            edge.grEdge.show_labels()
            edge.grEdge.update()

    def onDeselected(self):
        super().onDeselected()
        for edge in self.node.edges:
            edge.grEdge.setSelected(False)
            edge.grEdge.hide_labels()
            edge.grEdge.update()

    def hoverEnterEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        super().hoverEnterEvent(event)
        for edge in self.node.edges:
            edge.grEdge.hovered = True
            edge.grEdge.show_labels()
            edge.grEdge.update()

    def hoverLeaveEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        super().hoverLeaveEvent(event)
        for edge in self.node.edges:
            edge.grEdge.hovered = False
            edge.grEdge.hide_labels()
            edge.grEdge.update()


class AppNodeContentWidget(QWidget, Serializable):
    def __init__(self, node: "AppNode", parent: QWidget = None):
        self.node = node
        super().__init__(parent)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        self.wdg_label = QLabel("todo")
        self.layout.addWidget(self.wdg_label)

    def serialize(self) -> OrderedDict:
        return OrderedDict([])

    def deserialize(
        self, data: dict, hashmap: dict = None, restore_id: bool = True
    ) -> bool:
        return True
