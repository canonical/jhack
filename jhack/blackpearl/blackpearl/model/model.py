import subprocess
from typing import List, Dict, Any, Optional, Literal, Generator, Sequence

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.model.jujucli import Juju, Status
from jhack.utils.integrate import IntegrationMatrix

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

    @property
    def imatrices(self) -> Generator[IntegrationMatrix, None, None]:
        for controller in self.controllers:
            yield from filter(None, controller.imatrices)

    def get_juju_model(self, model_name: str) -> "JujuModel":
        for controller in self.controllers:
            for model in controller.models:
                if model.name == model_name:
                    return model
        raise NotFoundError(model_name)


class JujuController:
    """Juju controller datastructure wrapper."""

    def __init__(self, name: str, meta: Dict[str, Any]):
        self.name = name
        self._meta = meta
        self.current: Optional[str] = meta.get("current-model", None)
        self.models: List[JujuModel] = []

    def load_models(self, models: Optional[Sequence[str]]):
        self.models = get_models(self.name, models)

    @property
    def imatrices(self) -> Generator[IntegrationMatrix, None, None]:
        for model in self.models:
            yield model.imatrix

    def update(self):
        pass


class JujuModel:
    """Juju model datastructure wrapper."""

    def __init__(self, meta: Dict[str, Any]):
        self.name: str = meta["short-name"]
        self.full_name: str = meta["name"]
        self.type: Literal["lxd", "k8s"] = meta["type"]
        self.life: Literal["alive", "dying"] = meta["life"]
        self.uuid: str = meta["model-uuid"]
        self.cloud: str = meta["cloud"]
        self.region: str = meta["region"]
        self.owner: str = meta["owner"]
        self._meta = meta

        self.cli = Juju(self.name)
        self._status: Optional[Status] = None

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
        return IntegrationMatrix(model=self.name, include_peers=True)

    def update(self):
        pass


class JujuApp:
    """Juju app datastructure wrapper."""

    def __init__(self, name: str, meta: Dict[str, Any], model: JujuModel):
        # meta from juju show-application
        self.name = name
        self.model = model
        self._meta = meta

        self.charm: str = meta.get("charm-name", "unknown")
        self.base: str = meta.get("base", "unknown")
        self.scale: int = meta.get("scale", 1)
        self.channel: str = meta.get("charm-channel", "unknown")


def get_models(controller: str, names: Optional[List[str]]) -> List[JujuModel]:
    logger.info(f"gathering models for {controller}...")
    try:
        models = Juju().models(controller)
    except subprocess.CalledProcessError:
        logger.exception(f"unable to fetch models for {controller}, verify your juju")
        return []

    return [
        JujuModel(meta=meta)
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
