from collections import defaultdict

import math

import math
import os
import sys
import typing

from PyQt6.QtWidgets import QGraphicsTextItem
from qtpy.QtCore import QPointF
from qtpy.QtGui import QAction
from qtpy.QtWidgets import QMessageBox
from typing import Sequence

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.model.model import JujuController
from jhack.blackpearl.blackpearl.model.model import JujuModel
from jhack.blackpearl.blackpearl.view.app_node import AppNode
from jhack.blackpearl.blackpearl.view.controller_node import ControllerNode
from jhack.blackpearl.blackpearl.view.edges import (
    RelationEdge,
    PeerRelationEdge,
    CMREdge,
)
from jhack.blackpearl.blackpearl.view.model_node import ModelNode
from jhack.blackpearl.nodeeditor.node_editor_widget import NodeEditorWidget
from jhack.blackpearl.nodeeditor.node_editor_window import NodeEditorWindow
from jhack.blackpearl.nodeeditor.utils import loadStylesheets
from jhack.utils.helpers.gather_endpoints import RelationBinding

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.model.model import JujuApp
    from jhack.utils.helpers.gather_endpoints import (
        RelationBinding,
        PeerBinding,
        logger,
    )

logger = bp_logger.getChild("view")


class NodeNotFoundError(Exception):
    pass


class BPView(NodeEditorWindow):
    SHOW_MAXIMIZED = False

    def __init__(self):
        super().__init__()
        self.name_company = "Canonical"
        self.name_product = "Blackpearl"

        # sets of nodes
        self._juju_apps: typing.Set[AppNode] = set()
        self._juju_models: typing.Set[ModelNode] = set()
        self._juju_controllers: typing.Set[ControllerNode] = set()

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

        self.current_node_editor_widget()
        # self.setWindowIcon(get_icon("theatre_logo", suffix="png"))

    def create_actions(self):
        self.actAbout = QAction(
            "&About",
            self,
            statusTip="Show the application's About box",
            triggered=self._about,
        )
        self.actSpread = QAction(
            "&Spread",
            self,
            statusTip="Auto-arrange all nodes.",
            triggered=self.spread,
        )
        self.actCollapseRelations = QAction(
            "&Collapse relations",
            self,
            statusTip="Show all relations as individual edges.",
            triggered=self.collapse_relations,
            checkable=True,
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
        self.windowMenu = self.menuBar().addMenu("&Window")
        self.update_window_menu()
        self.windowMenu.aboutToShow.connect(self.update_window_menu)

        self.menuBar().addSeparator()

        self.viewMenu = self.menuBar().addMenu("&View")
        self.viewMenu.addAction(self.actSpread)
        self.viewMenu.addAction(self.actCollapseRelations)

        self.helpMenu = self.menuBar().addMenu("&Help")
        self.helpMenu.addAction(self.actAbout)

    def update_window_menu(self):
        menu = self.windowMenu
        menu.clear()

        menu.addSeparator()
        menu.addAction(self.actAbout)

    def create_status_bar(self):
        self.statusBar().showMessage("Ready")

    def add_controller(self, controller: "JujuController") -> ControllerNode:
        node = ControllerNode(self.nodeeditor.scene, controller)
        self._juju_controllers.add(node)
        logger.info(f"added controller node: {controller.name}: {node}")
        return node

    def add_model(self, model: "JujuModel") -> ModelNode:
        node = ModelNode(self.nodeeditor.scene, model)
        self._juju_models.add(node)
        logger.info(f"added model node: {model.name}: {node}")
        return node

    def add_app(self, app: "JujuApp") -> AppNode:
        node = AppNode(self.nodeeditor.scene, app)
        self._juju_apps.add(node)
        logger.info(f"added app node: {app.name}: {node}")
        return node

    def find_app(self, model: "JujuModel", name: str) -> "AppNode":
        for app_node in self._juju_apps:
            app: "JujuApp" = app_node.app
            if app.name == name and app.model is model:
                return app_node
        raise NodeNotFoundError(model.full_name, name)

    def find_model(self, name: str, controller: "JujuController") -> "ModelNode":
        for model_node in self._juju_models:
            model: "JujuModel" = model_node.model
            if model.name == name and model.controller is controller:
                return model_node
        raise NodeNotFoundError(name)

    def get_app_node(self, app: "JujuApp") -> "AppNode":
        for app_node in self._juju_apps:
            if app_node.app is app:
                return app_node
        raise NodeNotFoundError(app)

    def get_model_node(self, model: "JujuModel") -> "ModelNode":
        for model_node in self._juju_models:
            if model_node.model is model:
                return model_node
        raise NodeNotFoundError(model)

    def get_controller_node(self, controller: "JujuController") -> "ControllerNode":
        for controller_node in self._juju_controllers:
            if controller_node.controller is controller:
                return controller_node
        raise NodeNotFoundError(controller)

    def add_relation(
        self,
        provider_node: AppNode,
        requirer_node: AppNode,
        binding: "RelationBinding",
    ):
        """Regular in-model relation."""
        edge = RelationEdge(
            scene=self.nodeeditor.scene,
            start=provider_node,
            end=requirer_node,
            binding=binding,
        )
        self.nodeeditor.scene.add_edge(edge)
        provider_node.add_edge(edge)
        requirer_node.add_edge(edge)
        return edge

    def add_cmr(
        self,
        provider_node: AppNode,
        requirer_node: AppNode,
        binding: "RelationBinding",
    ):
        """Cross-model relation."""
        edge = CMREdge(
            scene=self.nodeeditor.scene,
            start=provider_node,
            end=requirer_node,
            binding=binding,
        )
        self.nodeeditor.scene.add_edge(edge)
        provider_node.add_edge(edge)
        requirer_node.add_edge(edge)
        return edge

    def add_peer_relation(
        self,
        app: AppNode,
        binding: "PeerBinding",
    ):
        """Add a peer relation."""
        edge = PeerRelationEdge(scene=self.nodeeditor.scene, node=app, binding=binding)
        app.add_edge(edge)
        return edge

    @property
    def object_tree(
        self,
    ) -> typing.Dict[ControllerNode, typing.Dict[ModelNode, typing.Tuple[AppNode]]]:
        out = defaultdict(dict)
        for controller in self._juju_controllers:
            out[controller] = defaultdict(list)
            for j_model in controller.controller.models:
                model = self.get_model_node(j_model)
                out[controller][model] = list(map(self.get_app_node, model.model.apps))
        return out

    def bind_all(self):
        """Ensure that when a parent object moves, all children are moved along."""
        otree = self.object_tree
        for controller, models in otree.items():
            controller.bind_children(models)
            for model, apps in models.items():
                model.bind_children(apps)

    def show_point(self, pt: QPointF, name: str):
        i = QGraphicsTextItem(name)
        i.setPos(i.mapToItem(i, pt))
        self.nodeeditor.view.scene().addItem(i)

    def collapse_relations(
        self,
        collapse: bool = True,
    ):
        if collapse:
            for node in self.nodeeditor.nodes:
                if isinstance(node, AppNode):
                    node.edges

    def spread(
        self,
        center: QPointF = None,
        # scale: float = 1.0,
    ):
        otree = self.object_tree
        center = center or QPointF(0, 0)
        self.show_point(center, "center")

        self._spread_controller_nodes(
            sorted(self._juju_controllers, key=lambda c: c.controller.uuid),
            center=center,
        )
        for controller, models in otree.items():
            self.show_point(center, "controller")
            self._spread_model_nodes(models=list(models), center=controller.center)

            for model, apps in models.items():
                self.show_point(center, f"model {model.title}")
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
