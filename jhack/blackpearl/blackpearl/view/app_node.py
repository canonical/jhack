import typing

from qtpy.QtWidgets import QWidget, QLabel

from jhack.blackpearl.blackpearl.model.edge_map import EdgeMap
from jhack.blackpearl.blackpearl.view.helpers import get_color
from jhack.blackpearl.blackpearl.view.node import NodeBase, GrNodeBase
from jhack.blackpearl.nodeeditor.node_content_widget import QDMNodeContentWidget

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.model.model import JujuApp


class AppNode(NodeBase):
    def __init__(
        self,
        app: "JujuApp",
        edges: EdgeMap,
    ):
        self.app = app
        super().__init__(
            parent=app,
            title=app.name,
            edges=edges,
            content=AppNodeContentWidget,
            gr_node=AppGraphicsNode,
        )


class AppGraphicsNode(GrNodeBase):
    def __repr__(self):
        return f"<AppGrNode {self.title}>"

    def __init__(self, node: "AppNode", parent: QWidget = None):
        super().__init__(
            node,
            parent,
            color=get_color(node.app.model.ui_color),
        )

    def onSelected(self):
        super().onSelected()
        for edge in self.node.edges_from:
            edge.gr_edge.selected = True
            edge.gr_edge.update()

    def onDeselected(self):
        super().onDeselected()
        for edge in self.node.edges_from:
            edge.gr_edge.selected = False
            edge.gr_edge.update()

    def hoverEnterEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        super().hoverEnterEvent(event)
        for edge in self.node.edges_from:
            edge.gr_edge.hovered = True
            edge.gr_edge.update()

    def hoverLeaveEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        super().hoverLeaveEvent(event)
        for edge in self.node.edges_from:
            edge.gr_edge.hovered = False
            edge.gr_edge.update()


class AppNodeContentWidget(QDMNodeContentWidget):
    @property
    def widget(self):
        return QLabel(self.node.app.charm)
