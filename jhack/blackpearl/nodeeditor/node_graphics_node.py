# -*- coding: utf-8 -*-
"""
A module containing Graphics representation of :class:`~nodeeditor.node_node.Node`
"""
from typing import Optional

from qtpy.QtGui import QVector2D
from qtpy.QtWidgets import QGraphicsItem, QWidget, QGraphicsTextItem
from qtpy.QtGui import QFont, QColor, QPen, QBrush, QPainterPath
from qtpy.QtCore import Qt, QRectF


class QDMGraphicsNode(QGraphicsItem):
    """Class describing Graphics representation of :class:`~nodeeditor.node_node.Node`"""

    def __init__(
        self,
        node: "Node",
        parent: QWidget = None,
        width: float = 180,
        height: float = 90,
        edge_roundness: float = 10.0,
        edge_padding: float = 10,
        title_height: float = 24,
        title_horizontal_padding: float = 4.0,
        title_vertical_padding: float = 4.0,
        color: Optional[QColor] = None,
    ):
        """
        :param node: reference to :class:`~nodeeditor.node_node.Node`
        :type node: :class:`~nodeeditor.node_node.Node`
        :param parent: parent widget
        :type parent: QWidget

        :Instance Attributes:

            - **node** - reference to :class:`~nodeeditor.node_node.Node`
        """
        super().__init__(parent)
        self.node = node

        # init our flags
        self.hovered = False
        self._previous_position = None
        self._was_moved = False
        self._last_selected_state = False

        self.width = width
        self.height = height
        self.edge_roundness = edge_roundness
        self.edge_padding = edge_padding
        self.title_height = title_height
        self.title_horizontal_padding = title_horizontal_padding
        self.title_vertical_padding = title_vertical_padding

        self._title_color = Qt.white
        self._title_font = QFont("Ubuntu", 10)

        self._color = color or QColor("#7F000000")
        self._color_selected = QColor("#FFFFA637")
        self._color_hovered = QColor("#FF37A6FF")

        self._pen_default = QPen(self._color)
        self._pen_default.setWidthF(2.0)
        self._pen_selected = QPen(self._color_selected)
        self._pen_selected.setWidthF(2.0)
        self._pen_hovered = QPen(self._color_hovered)
        self._pen_hovered.setWidthF(3.0)

        self._brush_title = QBrush(QColor("#FF313131"))
        self._brush_background = QBrush(QColor("#E3212121"))
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setAcceptHoverEvents(True)

        # init title
        self.title_item = QGraphicsTextItem(self)
        self.title_item.node = self.node
        self.title_item.setDefaultTextColor(self._title_color)
        self.title_item.setFont(self._title_font)
        self.title_item.setPos(self.title_horizontal_padding, 0)
        self.title_item.setTextWidth(self.width - 2 * self.title_horizontal_padding)
        self._title = "title"
        self.title = self.node.title

        if self.content is not None:
            self.content.setGeometry(
                self.edge_padding,
                self.title_height + self.edge_padding,
                self.width - 2 * self.edge_padding,
                self.height - 2 * self.edge_padding - self.title_height,
            )

        # get the QGraphicsProxyWidget when inserted into the grScene
        self.grContent = self.node.scene.grScene.addWidget(self.content)
        self.grContent.node = self.node
        self.grContent.setParentItem(self)

    @property
    def content(self):
        """Reference to `Node Content`"""
        return self.node.content if self.node else None

    @property
    def title(self):
        """title of this `Node`

        :getter: current Graphics Node title
        :setter: stores and make visible the new title
        :type: str
        """
        return self._title

    @title.setter
    def title(self, value):
        self._title = value
        self.title_item.setPlainText(self._title)

    def onSelected(self):
        """Our event handling when the node was selected"""
        self.node.scene.grScene.itemSelected.emit()

    def doSelect(self, new_state=True):
        """Safe version of selecting the `Graphics Node`. Takes care about the selection state flag used internally

        :param new_state: ``True`` to select, ``False`` to deselect
        :type new_state: ``bool``
        """
        self.setSelected(new_state)
        self._last_selected_state = new_state
        if new_state:
            self.onSelected()

    def mouseMoveEvent(self, event):
        """Overridden event to detect that we moved with this `Node`"""
        super().mouseMoveEvent(event)

        # TODO optimize me! just update the selected nodes
        for node in self.scene().scene.nodes:
            if node.gr_node.isSelected():
                node.update_connected_edges()

        if self._previous_position:
            self.onMoved(self.pos() - self._previous_position)

        self._previous_position = self.pos()
        self._was_moved = True

    def onMoved(self, vec: QVector2D):
        pass

    def mouseReleaseEvent(self, event):
        """Overriden event to handle when we moved, selected or deselected this `Node`"""
        super().mouseReleaseEvent(event)

        # handle when gr_node moved
        if self._was_moved:
            self._was_moved = False
            self._previous_position = None
            self.node.scene.reset_last_selected_state()
            self.doSelect()  # also trigger itemSelected when node was moved

            # we need to store the last selected state, because moving does also select the nodes
            self.node.scene._last_selected_items = self.node.scene.get_selected_items()

            # now we want to skip storing selection
            return

        # handle when gr_node was clicked on
        if (
            self._last_selected_state != self.isSelected()
            or self.node.scene._last_selected_items
            != self.node.scene.get_selected_items()
        ):
            self.node.scene.reset_last_selected_state()
            self._last_selected_state = self.isSelected()
            self.onSelected()

    def mouseDoubleClickEvent(self, event):
        """Overriden event for doubleclick. Resend to `Node::onDoubleClicked`"""
        self.node.onDoubleClicked(event)

    def hoverEnterEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        """Handle hover effect"""
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event: "QGraphicsSceneHoverEvent") -> None:
        """Handle hover effect"""
        self.hovered = False
        self.update()

    def boundingRect(self) -> QRectF:
        """Defining Qt' bounding rectangle"""
        return QRectF(0, 0, self.width, self.height).normalized()

    def paint(self, painter, QStyleOptionGraphicsItem, widget=None):
        """Painting the rounded rectanglar `Node`"""
        # title
        path_title = QPainterPath()
        path_title.setFillRule(Qt.WindingFill)
        path_title.addRoundedRect(
            0,
            0,
            self.width,
            self.title_height,
            self.edge_roundness,
            self.edge_roundness,
        )
        path_title.addRect(
            0,
            self.title_height - self.edge_roundness,
            self.edge_roundness,
            self.edge_roundness,
        )
        path_title.addRect(
            self.width - self.edge_roundness,
            self.title_height - self.edge_roundness,
            self.edge_roundness,
            self.edge_roundness,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._brush_title)
        painter.drawPath(path_title.simplified())

        # content
        path_content = QPainterPath()
        path_content.setFillRule(Qt.WindingFill)
        path_content.addRoundedRect(
            0,
            self.title_height,
            self.width,
            self.height - self.title_height,
            self.edge_roundness,
            self.edge_roundness,
        )
        path_content.addRect(
            0, self.title_height, self.edge_roundness, self.edge_roundness
        )
        path_content.addRect(
            self.width - self.edge_roundness,
            self.title_height,
            self.edge_roundness,
            self.edge_roundness,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._brush_background)
        painter.drawPath(path_content.simplified())

        # outline
        path_outline = QPainterPath()
        path_outline.addRoundedRect(
            -1,
            -1,
            self.width + 2,
            self.height + 2,
            self.edge_roundness,
            self.edge_roundness,
        )
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
