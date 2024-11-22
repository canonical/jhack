import math

import typing
from typing import Sequence

import sys

import os
from qtpy.QtCore import Qt, QPointF
from qtpy.QtWidgets import QMdiArea, QMessageBox
from nodeeditor.node_editor_widget import NodeEditorWidget
from nodeeditor.node_editor_window import NodeEditorWindow
from nodeeditor.utils import loadStylesheets
from qtpy.QtGui import QAction

from jhack.blackpearl.blackpearl.view.edges import RelationEdge, PeerRelationEdge
from jhack.blackpearl.blackpearl.view.helpers import get_icon
from jhack.blackpearl.blackpearl.view.nodes import AppNode

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.model.model import JujuApp
    from jhack.utils.helpers.gather_endpoints import RelationBinding, PeerBinding


class NodeNotFoundError(Exception):
    pass


class BPView(NodeEditorWindow):
    SHOW_MAXIMIZED = False

    def initUI(self):
        self.name_company = "Canonical"
        self.name_product = "Blackpearl"

        self.stylesheet_filename = os.path.join(
            os.path.dirname(__file__), "qss/nodeeditor.qss"
        )
        loadStylesheets(
            os.path.join(os.path.dirname(__file__), "qss/nodeeditor-dark.qss"),
            self.stylesheet_filename,
        )

        self.empty_icon = get_icon("code_blocks")
        self.nodeeditor = NodeEditorWidget()
        self.setCentralWidget(self.nodeeditor)

        self.create_actions()
        self.create_menus()
        # self.create_toolbars()
        self.create_status_bar()

        self.set_title()
        # self.setWindowIcon(get_icon("theatre_logo", suffix="png"))

    def closeEvent(self, event):
        self.writeSettings()
        event.accept()
        # hacky fix for PyQt 5.14.x
        import sys

        sys.exit(0)

    def create_actions(self):
        self.actAbout = QAction(
            "&About",
            self,
            statusTip="Show the application's About box",
            triggered=self._about,
        )

    @property
    def current_node_editor(self):
        active_subwindow = self.mdiArea.activeSubWindow()
        if active_subwindow:
            return active_subwindow.widget()
        return None

    def get_title(self):
        """Generate window title."""
        return "Blackpearl"

    def set_title(self):
        """Update window title."""
        self.setWindowTitle(self.get_title())

    def _about(self):
        about_txt = "\n".join(
            (
                f"This is Blackpearl v0.1.",
                f"python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            )
        )

        QMessageBox.about(self, "About", about_txt)

    def create_menus(self):
        self.windowMenu = self.menuBar().addMenu("&Window")
        self.update_window_menu()
        self.windowMenu.aboutToShow.connect(self.update_window_menu)

        self.menuBar().addSeparator()

        self.helpMenu = self.menuBar().addMenu("&Help")
        self.helpMenu.addAction(self.actAbout)

    def update_window_menu(self):
        menu = self.windowMenu
        menu.clear()

        menu.addSeparator()
        menu.addAction(self.actAbout)

    def create_status_bar(self):
        self.statusBar().showMessage("Ready")

    def add_app(self, app: "JujuApp"):
        return AppNode(self.nodeeditor.scene, app)

    def get_app(self, model: str, name: str) -> AppNode:
        for node in self.nodeeditor.scene.nodes:
            app: "JujuApp" = node.app
            if app.name == name and app.model.name == model:
                return node

        raise NodeNotFoundError(model, name)

    def add_relation(
        self,
        model: str,
        provider_name: str,
        requirer_name: str,
        binding: "RelationBinding",
    ):
        """Regular in-model relation."""
        provider = self.get_app(model, provider_name)
        requirer = self.get_app(model, requirer_name)
        edge = RelationEdge(
            scene=self.nodeeditor.scene, start=provider, end=requirer, binding=binding
        )
        self.nodeeditor.scene.addEdge(edge)
        provider.add_edge(edge)
        requirer.add_edge(edge)
        return edge

    def add_peer_relation(
        self,
        model: str,
        app: str,
        binding: "PeerBinding",
    ):
        """Regular in-model relation."""
        provider = self.get_app(model, app)
        edge = PeerRelationEdge(
            scene=self.nodeeditor.scene, node=provider, binding=binding
        )
        provider.add_edge(edge)
        return edge

    def spread(
        self,
        nodes: Sequence[AppNode],
        center: QPointF = None,
        diameter_ratio: float = 1.1,
    ):
        """"""
        center = center or QPointF()
        dist = len(nodes) * 10 * diameter_ratio + 200
        angle = 360 / len(nodes)
        for i, node in enumerate(nodes):
            rad = math.radians(i * angle)
            pos = center + QPointF(math.sin(rad) * dist, math.cos(rad) * dist)
            node.setPos(pos.x(), pos.y())
