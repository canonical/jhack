from PyQt6.QtGui import QColor
from itertools import cycle

import subprocess
from typing import List, Dict, Any, Optional, Literal, Generator, Sequence, Set

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.model.jujucli import Juju, Status
from jhack.blackpearl.blackpearl.view.helpers import get_color
from jhack.utils.integrate import IntegrationMatrix
from jhack.helpers import show_application

logger = bp_logger.getChild(__file__)


class NotFoundError(Exception):
    pass


class BPModel:
    def __init__(
        self,
        models: Optional[Sequence[str]] = None,
        controllers: Optional[Sequence[str]] = None,
    ):
        self.controllers = get_controllers(controllers)
        for controller in self.controllers:
            controller.load_models(models)

    def get_juju_model(self, model_name: str) -> "JujuModel":
        for controller in self.controllers:
            for model in controller.models:
                if model.name == model_name:
                    return model
        raise NotFoundError(model_name)

    def show_application(self, app_name: str, model: str):
        return show_application(app_name, model=model)


class JujuController:
    """Juju controller datastructure wrapper."""

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

    def status(self, refresh=False) -> Status:
        """Get juju status"""
        if refresh:
            self._status = None
        if not self._status:
            self._status = self.cli.status()
        return self._status

    @property
    def imatrix(self) -> Optional[IntegrationMatrix]:
        if self.life == "dying":
            logger.info(f"skipping model {self.name} as it is dying")
            return
        try:
            return IntegrationMatrix(model=self.name, include_peers=True)
        except:
            logger.exception(f"failed to collect imatrix for model {self.name}")
            return

    def update(self):
        pass


class JujuApp:
    """Juju app datastructure wrapper."""

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
