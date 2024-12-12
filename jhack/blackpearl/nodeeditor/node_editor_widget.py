# -*- coding: utf-8 -*-
"""
A module containing ``NodeEditorWidget`` class
"""
from PyQt6.QtGui import QMouseEvent
from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGraphicsItem,
)

from jhack.blackpearl.nodeeditor.node_graphics_view import QDMGraphicsView
from jhack.blackpearl.nodeeditor.node_scene import Scene


class NodeEditorWidget(QWidget):
    Scene_class = Scene
    GraphicsView_class = QDMGraphicsView

    """The ``NodeEditorWidget`` class"""

    def __init__(self, parent: QWidget = None):
        """
        :param parent: parent widget
        :type parent: ``QWidget``

        :Instance Attributes:

        - **filename** - currently graph's filename or ``None``
        """
        super().__init__(parent)

        self.filename = None
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        # crate graphics scene
        self.scene = self.__class__.Scene_class()

        # create graphics view
        self.view = self.__class__.GraphicsView_class(self.scene.gr_scene, self)
        self.layout.addWidget(self.view)

    def get_selected_items(self) -> list:
        """Shortcut returning `Scene`'s currently selected items

        :return: list of ``QGraphicsItems``
        :rtype: list[QGraphicsItem]
        """
        return self.scene.get_selected_items()

    @property
    def nodes(self):
        return self.scene.nodes

    def mousePressEvent(self, a0: QMouseEvent):
        super().mousePressEvent(a0)
        print(f"unhandled click on {self}")
