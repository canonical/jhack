import itertools
import typing
from multiprocessing.managers import Value

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.model.model import (
    BPModel,
    JujuApp,
)
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
        view = self._view
        for controller in self._model.controllers:
            view.add_controller(controller)

            for model in controller.models:
                view.add_model(model)

                imatrix = model.imatrix
                if not imatrix:
                    logger.warning(
                        f"skipped model {model} as no imatrix could be collected"
                    )
                    continue

                nodes = []
                for app_name in imatrix.apps:
                    try:
                        app = JujuApp(
                            app_name,
                            self._model.show_application(app_name, model=model.name),
                            model=model,
                        )
                    except:
                        logger.error(f"failed to create app {app_name}")
                        continue

                    node = view.add_app(app)
                    nodes.append(node)

                logger.info("populating relations...")
                edges = []

                for prov, req in itertools.product(imatrix.apps, repeat=2):
                    for relation in imatrix.get_integrations(prov, req):
                        if isinstance(relation, PeerBinding):
                            # peer
                            edges.append(
                                view.add_peer_relation(
                                    view.find_app(model, prov), relation
                                )
                            )

                        elif isinstance(relation, RelationBinding):
                            # regular
                            edges.append(
                                view.add_relation(
                                    view.find_app(model, prov),
                                    view.find_app(model, req),
                                    relation,
                                )
                            )
                        else:
                            raise ValueError(relation)

            # now we've added all models, we can add cross-model relations
            for model in controller.models:
                model.collect_cmrs()
                for cmr in model.cmrs:
                    # fixme: could be provider or requirer
                    app1 = self._view.find_app(model, cmr.provider_app)
                    model2 = self._view.find_model(cmr.requirer_model, controller)
                    app2 = self._view.find_app(model2.model, cmr.requirer_app)
                    self._view.add_cmr(app1, app2, cmr)

        view.bind_all()
        view.spread()
