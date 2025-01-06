import re
import typing
from collections import defaultdict

from PyQt6.QtGui import QColor
from itertools import cycle

import subprocess
from typing import List, Dict, Any, Optional, Literal, Generator, Sequence, Set, Tuple

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.model.edge_map import EdgeMap
from jhack.blackpearl.blackpearl.model.jujucli import Juju, Status
from jhack.blackpearl.blackpearl.view.app_node import AppNode
from jhack.blackpearl.blackpearl.view.controller_node import ControllerNode
from jhack.blackpearl.blackpearl.view.edges import (
    RelationEdge,
    PeerRelationEdge,
    CMREdge,
)
from jhack.blackpearl.blackpearl.view.helpers import get_color
from jhack.blackpearl.blackpearl.view.model_node import ModelNode
from jhack.utils.helpers.gather_endpoints import RelationBinding
from jhack.utils.integrate import IntegrationMatrix, IMatrix, gather_imatrix
from jhack.helpers import show_application, modify_remote_file

logger = bp_logger.getChild(__file__)


class NodeNotFoundError(Exception):
    pass


class NotFoundError(Exception):
    pass


class BPModel:
    def __init__(
        self,
        models: Optional[Sequence[str]] = None,
        controllers: Optional[Sequence[str]] = None,
    ):
        self.edges = EdgeMap()
        # sets of nodes
        self.app_nodes: typing.Set[AppNode] = set()
        self.model_nodes: typing.Set[ModelNode] = set()
        self.controller_nodes: typing.Set[ControllerNode] = set()

        self.juju_controllers: List["JujuController"] = []
        self._juju_controller_names = controllers
        self._juju_model_names = models

    def bootstrap(self):
        logger.info("bootstrapping controllers...")
        self.juju_controllers = get_controllers(self._juju_controller_names)
        for controller in self.juju_controllers:
            logger.info(f"bootstrapping models from controller {controller.name}...")
            controller.load_models(self._juju_model_names)
            for model in tuple(controller.models):
                logger.info(f"bootstrapping model {model.name}...")
                success = model.bootstrap()
                if not success:
                    logger.warning(f"bootstrap FAILED for {model.name}")
                    controller.models.remove(model)

    def add_controller(self, controller: "JujuController") -> ControllerNode:
        node = ControllerNode(controller, edges=self.edges)
        self.controller_nodes.add(node)
        logger.info(f"added controller node: {controller.name}: {node}")
        return node

    def add_model(self, model: "JujuModel") -> ModelNode:
        node = ModelNode(model, edges=self.edges)
        self.model_nodes.add(node)
        logger.info(f"added model node: {model.name}: {node}")
        return node

    def add_app(self, app: "JujuApp") -> AppNode:
        node = AppNode(app, edges=self.edges)
        self.app_nodes.add(node)
        logger.info(f"added app node: {app.name}: {node}")
        return node

    def add_relation(
        self,
        provider_node: AppNode,
        requirer_node: AppNode,
        binding: "RelationBinding",
    ):
        """Regular in-model relation."""
        edge = RelationEdge(
            start=provider_node,
            end=requirer_node,
            binding=binding,
        )
        self.edges.add(edge)
        provider_node.add_edge(edge, self.edges)  # only attach to source
        # requirer_node.add_edge(edge)
        return edge

    def add_cmr(
        self,
        provider_node: AppNode,
        requirer_node: AppNode,
        binding: "RelationBinding",
    ):
        """Cross-model relation."""
        edge = CMREdge(
            start=provider_node,
            end=requirer_node,
            binding=binding,
        )
        self.edges.add(edge)
        provider_node.add_edge(edge, self.edges)
        # requirer_node.add_edge(edge)
        return edge

    def add_peer_relation(
        self,
        app: AppNode,
        binding: "PeerBinding",
    ):
        """Add a peer relation."""
        edge = PeerRelationEdge(node=app, binding=binding)
        self.edges.add(edge)
        app.add_edge(edge, self.edges)
        return edge

    def find_app(self, model: "JujuModel", name: str) -> "AppNode":
        for app_node in self.app_nodes:
            app: "JujuApp" = app_node.app
            if app.name == name and app.model is model:
                return app_node
        raise NodeNotFoundError(model.full_name, name)

    def find_controller(self, name: str) -> "ControllerNode":
        for controller_node in self.controller_nodes:
            controller: "JujuController" = controller_node.controller
            if controller.name == name:
                return controller_node
        raise NodeNotFoundError(name)

    def find_model(
        self, name: str, controller: typing.Union["JujuController", str]
    ) -> "ModelNode":
        controller_ = (
            self.find_controller(controller).controller
            if isinstance(controller, str)
            else controller
        )
        for model_node in self.model_nodes:
            model: "JujuModel" = model_node.model
            if model.name == name and model.controller is controller_:
                return model_node
        raise NodeNotFoundError(name)

    def get_app_node(self, app: "JujuApp") -> "AppNode":
        for app_node in self.app_nodes:
            if app_node.app is app:
                return app_node
        raise NodeNotFoundError(app)

    def get_model_node(self, model: "JujuModel") -> "ModelNode":
        for model_node in self.model_nodes:
            if model_node.model is model:
                return model_node
        raise NodeNotFoundError(model)

    def get_controller_node(self, controller: "JujuController") -> "ControllerNode":
        for controller_node in self.controller_nodes:
            if controller_node.controller is controller:
                return controller_node
        raise NodeNotFoundError(controller)

    @property
    def object_tree(
        self,
    ) -> typing.Dict[ControllerNode, typing.Dict[ModelNode, typing.Tuple[AppNode]]]:
        out = defaultdict(dict)
        for controller in self.controller_nodes:
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

    def show_application(self, app_name: str, model: str):
        return show_application(app_name, model=model)

    def clear(self):
        self.edges.clear()
        self.app_nodes.clear()
        self.model_nodes.clear()
        self.controller_nodes.clear()


class JujuController:
    """Juju controller datastructure wrapper."""

    def __repr__(self):
        return f"<JujuController {self.name}>"

    _CONTROLLER_COLOR_CYCLER = cycle(
        ("controller_1", "controller_2", "controller_3", "controller_4", "controller_5")
    )

    _CONTROLLER_COLORS: Dict["JujuController", QColor] = {}

    def _get_ui_color(self):
        if color := self._CONTROLLER_COLORS.get(self):
            return color
        self._CONTROLLER_COLORS[self] = get_color(next(self._CONTROLLER_COLOR_CYCLER))
        return self._CONTROLLER_COLORS.get(self)

    def __hash__(self):
        return hash(self.uuid)

    def __init__(self, name: str, meta: Dict[str, Any]):
        self.name = name
        self._meta = meta
        self.uuid = meta["uuid"]
        self.current: Optional[str] = meta.get("current-model", None)
        self.models: List[JujuModel] = []
        self.ui_color = self._get_ui_color()

    def load_models(self, models: Optional[Sequence[str]]):
        self.models = get_models(self, models)

    def update(self):
        pass


class JujuModel:
    """Juju model datastructure wrapper."""

    def __repr__(self):
        return f"<JujuModel {self.name}>"

    _MODEL_COLOR_CYCLER = cycle(
        (
            "model_1",
            "model_2",
            "model_3",
            "model_4",
            "model_5",
            "model_6",
            "model_7",
            "model_8",
        )
    )
    _MODEL_COLORS: Dict["JujuModel", QColor] = {}

    def _get_ui_color(self):
        if color := self._MODEL_COLORS.get(self):
            return color
        self._MODEL_COLORS[self] = get_color(next(self._MODEL_COLOR_CYCLER))
        return self._MODEL_COLORS.get(self)

    def __hash__(self):
        return hash((self.controller, self.name))

    def __init__(self, meta: Dict[str, Any], controller: JujuController):
        self.controller = controller
        self._meta = meta
        self.apps: Set[JujuApp] = set()
        self.name: str = meta["short-name"]
        self.full_name: str = meta["name"]
        self.type: Literal["lxd", "k8s"] = meta["type"]
        self.life: Literal["alive", "dying"] = meta["life"]
        self.uuid: str = meta["model-uuid"]
        self.cloud: str = meta["cloud"]
        self.region: str = meta["region"]
        self.owner: str = meta["owner"]

        self.cli = Juju(self.name)
        self._status: Optional[Status] = None
        self.ui_color = self._get_ui_color()
        self.imatrix: Optional["IMatrix"] = None

    @property
    def cmrs(self) -> Tuple["RelationBinding", ...]:
        if not self.imatrix:
            raise ValueError(f"{self} not bootstrapped")
        return self.imatrix.cmrs

    def status(self, refresh=False) -> Status:
        """Get juju status"""
        if refresh:
            self._status = None
        if not self._status:
            self._status = self.cli.status()
        return self._status

    def bootstrap(self):
        if self.life == "dying":
            logger.info(f"skipping model {self.name} as it is dying")
            return False
        try:
            self.imatrix = gather_imatrix(
                model=self.name,
                include_peers=True,
                include_cmrs=True,
                include_inactive=False,
            )
        except:
            logger.exception(f"failed to collect imatrix for model {self.name}")
            return False
        return True


class JujuApp:
    """Juju app datastructure wrapper."""

    def __repr__(self):
        return f"<JujuApp {self.name}>"

    def __hash__(self):
        return hash((self.name, self.model.uuid))

    def __init__(self, name: str, meta: Dict[str, Any], model: JujuModel):
        # meta from juju show-application
        self.name = name
        self.model = model
        self.model.apps.add(self)
        self._meta = meta

        self.charm: str = meta.get("charm-name", "unknown")
        self.base: str = meta.get("base", "unknown")
        self.scale: int = meta.get("scale", 1)
        self.channel: str = meta.get("charm-channel", "unknown")


def get_models(
    controller: JujuController, names: Optional[List[str]]
) -> List[JujuModel]:
    logger.info(f"gathering models for {controller}...")
    try:
        models = Juju().models(controller.name)
    except subprocess.CalledProcessError:
        logger.exception(
            f"unable to fetch models for {controller.name}, verify your juju"
        )
        return []

    return [
        JujuModel(meta=meta, controller=controller)
        for meta in models
        if (not names or meta["short-name"] in names)
    ]


def get_controllers(names: Optional[Sequence[str]]) -> List[JujuController]:
    logger.info("gathering controllers...")
    try:
        controllers = Juju().controllers()
    except subprocess.CalledProcessError:
        logger.exception("unable to fetch controllers, verify your juju")
        return []

    return [
        JujuController(name, meta=meta)
        for name, meta in controllers.items()
        if (not names or name in names)
    ]
