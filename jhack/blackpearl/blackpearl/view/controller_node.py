import typing

from qtpy.QtCore import QPointF, QRectF
from qtpy.QtCore import Qt
from qtpy.QtGui import QPainterPath
from qtpy.QtWidgets import QWidget

from jhack.blackpearl.blackpearl.view.helpers import get_color
from jhack.blackpearl.blackpearl.view.node import NodeBase, GrNodeBase

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.model.model import JujuController
    from jhack.blackpearl.blackpearl.model.edge_map import EdgeMap


class ControllerNode(NodeBase):
    def __init__(
        self,
        controller: "JujuController",
        edges: "EdgeMap",
    ):
        self.controller = controller
        super().__init__(
            parent=controller,
            edges=edges,
            title=f"C.{controller.name}",
            gr_node=ControllerGraphicsNode,
        )


class ControllerGraphicsNode(GrNodeBase):
    node: "ControllerNode"
    _scale = 1000

    def __init__(self, node: "ControllerNode", parent: QWidget = None):
        super().__init__(
            node,
            parent,
            color=get_color(node.controller.ui_color),
        )

        self.radius = self._scale

    def update_size(self):
        # sum the radia of the model nodes to find out our own
        tot_child_radia = sum(
            child.gr_node.radius for child in self.node.bound_children
        )
        self.radius = max(self._scale, tot_child_radia + 100)

    def boundingRect(self) -> QRectF:
        """Defining Qt' bounding rectangle"""
        return QRectF(
            -self.radius, -self.radius, self.radius * 2, self.radius * 2
        ).normalized()

    def paint(self, painter, QStyleOptionGraphicsItem, widget=None):
        """Painting the hex `Node`"""
        # outline
        path_outline = QPainterPath()
        path_outline.addEllipse(QPointF(0, 0), self.radius + 1, self.radius + 1)

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
