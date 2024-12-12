import math
import os
import sys
import typing
from typing import Sequence

from PyQt6.QtGui import QMouseEvent
from qtpy.QtCore import QSize
from qtpy.QtWidgets import QGraphicsTextItem, QLabel, QMainWindow
from qtpy.QtCore import QPointF
from qtpy.QtGui import QAction
from qtpy.QtWidgets import QMessageBox

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.nodeeditor.node_editor_widget import NodeEditorWidget
from jhack.blackpearl.nodeeditor.utils import loadStylesheets

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.view.controller_node import ControllerNode
    from jhack.blackpearl.blackpearl.view.model_node import ModelNode
    from jhack.blackpearl.blackpearl.view.app_node import AppNode
    from jhack.blackpearl.blackpearl.model.edge_map import EdgeMap
    from jhack.blackpearl.blackpearl.view.edges import Edge


logger = bp_logger.getChild("view")


class BPView(QMainWindow):
    SHOW_MAXIMIZED = False

    def __init__(self):
        super().__init__()
        self.name_company = "Canonical"
        self.name_product = "Blackpearl"

        self.stylesheet_filename = os.path.join(
            os.path.dirname(__file__), "qss/nodeeditor.qss"
        )
        loadStylesheets(
            os.path.join(os.path.dirname(__file__), "qss/nodeeditor-dark.qss"),
            self.stylesheet_filename,
        )

        self.nodeeditor = NodeEditorWidget()
        self.setCentralWidget(self.nodeeditor)

        self.create_actions()
        self.create_menus()
        # self.create_toolbars()
        self.create_status_bar()

        self.setWindowTitle(self.get_title())
        self.show()

        self.statusBar().showMessage("")
        self.status_mouse_pos = QLabel("")
        self.statusBar().addPermanentWidget(self.status_mouse_pos)
        self.nodeeditor.view.scenePosChanged.connect(self.on_scene_pos_changed)

        # self.setWindowIcon(get_icon("theatre_logo", suffix="png"))

    def on_scene_pos_changed(self, x: int, y: int):
        """Handle event when cursor position changed on the `Scene`

        :param x: new cursor x position
        :type x:
        :param y: new cursor y position
        :type y:
        """
        self.status_mouse_pos.setText("Scene Pos: [%d, %d]" % (x, y))

    def sizeHint(self):
        return QSize(800, 600)

    def create_actions(self):
        self.actAbout = QAction(
            "&About",
            self,
            statusTip="Show the application's About box",
            triggered=self._about,
        )

    def get_title(self):
        """Generate window title."""
        return "Blackpearl"

    def _about(self):
        about_txt = "\n".join(
            (
                f"This is Blackpearl v0.1.",
                f"python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            )
        )

        QMessageBox.about(self, "About", about_txt)

    def create_menus(self):
        self.window_menu = self.menuBar().addMenu("&Window")
        self.update_window_menu()
        self.window_menu.aboutToShow.connect(self.update_window_menu)

        self.menuBar().addSeparator()
        self.view_menu = self.menuBar().addMenu("&View")

        self.help_menu = self.menuBar().addMenu("&Help")
        self.help_menu.addAction(self.actAbout)

    def update_window_menu(self):
        menu = self.window_menu
        menu.clear()

    def create_status_bar(self):
        self.statusBar().showMessage("Ready")

    def show_point(self, pt: QPointF, name: str):
        i = QGraphicsTextItem(name)
        i.setPos(i.mapToItem(i, pt))
        self.nodeeditor.view.scene().addItem(i)

    def spread(
        self,
        controllers: typing.Iterable["ControllerNode"],
        object_tree,
        center: QPointF = None,
        # scale: float = 1.0,
    ):
        center = center or QPointF(0, 0)
        #  self.show_point(center, "center")

        self._spread_controller_nodes(
            sorted(controllers, key=lambda c: c.controller.uuid),
            center=center,
        )
        for controller, models in object_tree.items():
            #  self.show_point(center, "controller")
            self._spread_model_nodes(models=list(models), center=controller.center)

            for model, apps in models.items():
                #  self.show_point(center, f"model {model.title}")
                self._spread_app_nodes(apps=apps, center=model.gr_node.center)
                model.gr_node.update_size()

            controller.gr_node.update_size()

        self.nodeeditor.view.centerOn(center)

    def _spread_controller_nodes(
        self,
        controllers: Sequence["ControllerNode"],
        center: QPointF = None,
    ):

        for node, pos in zip(
            controllers,
            self._circular_spread(
                center=center or QPointF(),
                n=len(controllers),
                diameter_ratio=1.1,
                base_size=500,
            ),
        ):
            node.set_pos(pos)

    def _spread_model_nodes(
        self,
        models: Sequence["ModelNode"],
        center: QPointF = None,
    ):

        for node, pos in zip(
            models,
            self._circular_spread(
                center=center or QPointF(),
                n=len(models),
                diameter_ratio=15.0,
                base_size=300,
            ),
        ):
            node.set_pos(pos)

    def _spread_app_nodes(
        self,
        apps: Sequence["AppNode"],
        center: QPointF = None,
    ):
        for node, pos in zip(
            apps,
            self._circular_spread(
                center=center or QPointF(),
                n=len(apps),
                diameter_ratio=1.1,
                base_size=200,
            ),
        ):
            node.set_pos(pos, centered=True)

    def _circular_spread(
        self,
        center: QPointF,
        n: int,
        diameter_ratio: float = 1.1,
        base_size: float = 200.0,
    ):
        if n == 1:
            yield center
            return
        dist = n * 10 * diameter_ratio + base_size
        angle = 360 / n
        for i in range(n):
            rad = math.radians(i * angle)
            yield center + QPointF(math.sin(rad) * dist, math.cos(rad) * dist)

    def add_node(self, node):
        self.nodeeditor.scene.add_node(node)

    def add_edge(self, edge: "Edge"):
        self.nodeeditor.scene.add_edge(edge)

    def add_all(self, edges: "EdgeMap"):
        # add all existing edges to the scene
        for edge in edges.iter_all():
            self.nodeeditor.scene.add_edge(edge)

    def mousePressEvent(self, a0: QMouseEvent):
        super().mousePressEvent(a0)
        print(f"unhandled click on {self}")
