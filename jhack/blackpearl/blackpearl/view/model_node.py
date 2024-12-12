import typing

from qtpy.QtCore import QPointF, QRectF
from qtpy.QtCore import Qt
from qtpy.QtGui import QPainterPath
from qtpy.QtWidgets import QWidget

from jhack.blackpearl.blackpearl.model.edge_map import EdgeMap
from jhack.blackpearl.blackpearl.view.helpers import get_color
from jhack.blackpearl.blackpearl.view.node import NodeBase, GrNodeBase


if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.model.model import JujuApp


class ModelNode(NodeBase):
    def __init__(
        self,
        model: "JujuModel",
        edges: EdgeMap,
    ):
        self.model = model
        super().__init__(
            parent=model,
            title=f"M.{model.name}",
            edges=edges,
            gr_node=ModelGraphicsNode,
        )


class ModelGraphicsNode(GrNodeBase):
    node: "ModelNode"
    _scale = 50

    def __init__(self, node: "ModelNode", parent: QWidget = None):

        super().__init__(node, parent, color=get_color(node.model.ui_color))
        # self.title_item.setPos(self.mapToScene(self.boundingRect().topLeft()))

        self.radius = self._scale
        # updated later, as apps are added AFTER the model is created

    def update_size(self):
        # 10 applications kind of fit well in 1000 units
        self.radius = max(self._scale, self._scale * len(self.node.model.apps))

    def boundingRect(self) -> QRectF:
        """Defining Qt' bounding rectangle"""
        return QRectF(
            -self.radius, -self.radius, self.radius * 2, self.radius * 2
        ).normalized()

    def paint(self, painter, QStyleOptionGraphicsItem, widget=None):
        """Paint the model circle."""
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
