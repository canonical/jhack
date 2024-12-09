from collections import OrderedDict

import typing
from qtpy.QtCore import QPointF
from qtpy.QtGui import QPen
from qtpy.QtWidgets import QWidget, QVBoxLayout, QLabel

from jhack.blackpearl.blackpearl.model.model import JujuApp
from jhack.blackpearl.blackpearl.view.edges import RelationEdge, PeerRelationEdge, Edge
from jhack.blackpearl.blackpearl.view.helpers import get_color
from jhack.blackpearl.blackpearl.view.node import NodeBase, GrNodeBase
from jhack.blackpearl.nodeeditor.node_content_widget import QDMNodeContentWidget
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
        super().__init__(
            app,
            scene,
            app.name,
            content=AppNodeContentWidget,
            gr_node=AppGraphicsNode,
        )


class AppGraphicsNode(GrNodeBase):
    def __init__(self, node: "AppNode", parent: QWidget = None):
        super().__init__(
            node,
            parent,
            color=get_color(node.app.model.ui_color),
        )

    def onSelected(self):
        super().onSelected()
        for edge in self.node.edges:
            edge.grEdge.setSelected(True)
            edge.grEdge.update()

    def onDeselected(self):
        super().onDeselected()
        for edge in self.node.edges:
            print("node deselected")
            edge.grEdge.setSelected(False)
            edge.grEdge.update()

    def hoverEnterEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        super().hoverEnterEvent(event)
        for edge in self.node.edges:
            edge.grEdge.hovered = True
            edge.grEdge.update()

    def hoverLeaveEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        super().hoverLeaveEvent(event)
        for edge in self.node.edges:
            edge.grEdge.hovered = False
            edge.grEdge.update()


class AppNodeContentWidget(QDMNodeContentWidget):
    @property
    def widget(self):
        return QLabel(self.node.app.charm)
