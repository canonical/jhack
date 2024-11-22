import itertools

import typing

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.helpers import show_application
from jhack.blackpearl.blackpearl.model.model import BPModel, JujuApp

from jhack.utils.helpers.gather_endpoints import RelationBinding, PeerBinding

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.view.view import BPView

logger = bp_logger.getChild(__file__)


class BPController:
    def __init__(self, view: "BPView", model: "BPModel"):
        self._view = view
        self._model = model
        self.update()

    def update(self):
        logger.info("populating apps...")

        for imatrix in self._model.imatrices:
            nodes = []
            model = self._model.get_juju_model(imatrix.model)
            for app_name in imatrix.apps:
                try:
                    app = JujuApp(
                        app_name,
                        show_application(app_name, model=model.name),
                        model,
                    )
                except:
                    logger.error(f"failed to create app {app_name}")
                    continue

                node = self._view.add_app(app)
                nodes.append(node)

            self._view.spread(nodes)

            logger.info("populating relations...")
            edges = []

            for prov, req in itertools.product(imatrix.apps, repeat=2):
                for relation in imatrix.get_integrations(prov, req):
                    if isinstance(relation, PeerBinding):
                        # peer
                        edges.append(
                            self._view.add_peer_relation(model.name, prov, relation)
                        )

                    elif isinstance(relation, RelationBinding):
                        # regular
                        edges.append(
                            self._view.add_relation(model.name, prov, req, relation)
                        )
