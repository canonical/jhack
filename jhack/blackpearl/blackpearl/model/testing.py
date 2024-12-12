from typing import (
    List,
    Optional,
    Sequence,
    Union,
    Iterable,
)
from unittest.mock import MagicMock

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.model.edge_map import EdgeMap
from jhack.blackpearl.blackpearl.model.model import JujuModel, JujuController, BPModel
from jhack.blackpearl.blackpearl.model.testing_data import SAMPLE_MATRIX
from jhack.utils.helpers.gather_endpoints import PeerBinding, RelationBinding

logger = bp_logger.getChild(__file__)


class TestingBPModel(BPModel):
    def __init__(
        self,
        models: Optional[Sequence[str]] = None,
        controllers: Optional[Sequence[str]] = None,
    ):
        self.juju_apps = set()
        self.juju_models = set()
        self.juju_controllers = set()

        self.edges = EdgeMap()

        self._apps = {
            "model1": {
                "alertmanager": {},
                "catalogue": {},
                "grafana": {},
                "istio-beacon-k8s": {},
                "loki": {},
                "minio": {},
                "prometheus": {},
                "s3": {},
                "tempo": {"charm-name": "tempo-coordinator-k8s"},
                "traefik": {},
                "worker": {},
            },
            "model2": {
                "alertmanager": {},
                "catalogue": {},
                "grafana": {},
                "istio-beacon-k8s": {},
                "loki": {},
                "minio": {},
                "prometheus": {},
                "s3": {},
                "tempo": {},
                "traefik": {},
                "worker": {},
            },
        }
        controller = TestingJujuController(
            "controller1",
            apps=self._apps,
            matrices={"model1": SAMPLE_MATRIX, "model2": SAMPLE_MATRIX},
            cmrs={
                "model1": [
                    RelationBinding(
                        provider_app="alertmanager",
                        provider_model="model1",
                        provider_endpoint="grafana-dashboard",
                        interface="grafana_dashboard",
                        requirer_app="tempo",
                        requirer_model="model2",
                        requirer_endpoint="grafana-dashboard",
                    ),
                ]
            },
        )
        self.controllers = [controller]

    def show_application(self, app_name: str, model: str):
        return self._apps[model][app_name]


class TestingJujuModel(JujuModel):
    def __init__(
        self,
        name: str,
        apps: Iterable[str],
        matrix: List[List[Union[List[PeerBinding], List[RelationBinding]]]],
        cmrs: List[RelationBinding],
        controller,
    ):
        super().__init__(
            meta={
                "short-name": name,
                "name": name,
                "type": "k8s",
                "life": "alive",
                "model-uuid": "1234",
                "model-name": name,
                "cloud": "foo",
                "region": "foo",
                "owner": "foo",
            },
            controller=controller,
        )
        self._matrix = matrix
        self._apps = list(apps)
        self.cmrs.extend(cmrs)

    @property
    def imatrix(self):
        mm = MagicMock()
        mm.matrix = self._matrix
        mm.apps = self._apps
        mm.model = "servicegraph"

        def get_integrations(
            provider_app: str, requirer_app: str
        ) -> Union[List[PeerBinding], List[RelationBinding]]:
            """Get the list of peer or regular relation bindings for these apps."""
            return self._matrix[self._apps.index(provider_app)][
                self._apps.index(requirer_app)
            ]

        mm.get_integrations = get_integrations
        return mm


class TestingJujuController(JujuController):
    def __init__(self, name: str, apps, matrices, cmrs):
        super().__init__(name, meta={"uuid": "123", "current-model": "foo"})
        self.models = [
            TestingJujuModel(
                mname, apps[mname], matrices[mname], cmrs.get(mname, []), self
            )
            for mname in apps
        ]
