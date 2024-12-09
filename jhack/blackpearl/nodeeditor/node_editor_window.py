# -*- coding: utf-8 -*-
"""
A module containing the Main Window class
"""
from qtpy.QtCore import QSize
from qtpy.QtWidgets import (
    QMainWindow,
    QLabel,
    QAction,
)

from jhack.blackpearl.nodeeditor.node_editor_widget import NodeEditorWidget


class NodeEditorWindow(QMainWindow):
    NodeEditorWidget_class = NodeEditorWidget

    """Class representing NodeEditor's Main Window"""

    def __init__(self):
        """
        :Instance Attributes:

        - **name_company** - name of the company, used for permanent profile settings
        - **name_product** - name of this App, used for permanent profile settings
        """
        super().__init__()

        self.name_company = "Jhack"
        self.name_product = "nodeeditor"
        self.actExit = QAction(
            "E&xit",
            self,
            shortcut="Ctrl+Q",
            statusTip="Exit application",
            triggered=self.close,
        )

        self.fileMenu = self.menuBar().addMenu("&File")
        self.fileMenu.addAction(self.actExit)

        # create node editor widget
        self.nodeeditor = self.__class__.NodeEditorWidget_class(self)
        self.nodeeditor.scene.on_modified(self.set_title)
        self.setCentralWidget(self.nodeeditor)

        self.statusBar().showMessage("")
        self.status_mouse_pos = QLabel("")
        self.statusBar().addPermanentWidget(self.status_mouse_pos)
        self.nodeeditor.view.scenePosChanged.connect(self.on_scene_pos_changed)

        # set window properties
        # self.setGeometry(200, 200, 800, 600)
        self.set_title()
        self.show()

    def sizeHint(self):
        return QSize(800, 600)

    def get_title(self):
        """Override this method."""
        return "title"

    def set_title(self):
        """Set the window title"""
        self.setWindowTitle(self.get_title())

    def current_node_editor_widget(self) -> NodeEditorWidget:
        """get current :class:`~nodeeditor.node_editor_widget`

        :return: get current :class:`~nodeeditor.node_editor_widget`
        :rtype: :class:`~nodeeditor.node_editor_widget`
        """
        return self.centralWidget()

    def on_scene_pos_changed(self, x: int, y: int):
        """Handle event when cursor position changed on the `Scene`

        :param x: new cursor x position
        :type x:
        :param y: new cursor y position
        :type y:
        """
        self.status_mouse_pos.setText("Scene Pos: [%d, %d]" % (x, y))
