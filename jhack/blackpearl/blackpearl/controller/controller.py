import itertools
import re
import typing
from itertools import pairwise, product
from multiprocessing.managers import Value

from qtpy.QtGui import QAction

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.model.model import (
    BPModel,
    JujuApp,
    get_controllers,
)
from jhack.blackpearl.blackpearl.view.app_node import AppNode
from jhack.blackpearl.blackpearl.view.edges import CompoundEdge, Edge
from jhack.utils.helpers.gather_endpoints import RelationBinding, PeerBinding

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.view.view import BPView

logger = bp_logger.getChild(__file__)


class BPController:
    def __init__(self, view: "BPView", model: "BPModel"):
        self._view = view
        self._model = model
        self.add_actions()

    def bootstrap(self):
        logger.info("bootstrapping apps...")
        bp_view = self._view
        bp_model = self._model

        bp_model.bootstrap()
        for controller in bp_model.juju_controllers:
            bp_view.add_node(bp_model.add_controller(controller))
            for model in controller.models:
                bp_view.add_node(bp_model.add_model(model))
                imatrix = model.imatrix
                if not imatrix:
                    logger.warning(
                        f"skipped model {model} as no imatrix could be collected"
                    )
                    continue

                for app_name in imatrix.apps:
                    try:
                        app = JujuApp(
                            app_name,
                            bp_model.show_application(app_name, model=model.name),
                            model=model,
                        )
                    except:
                        logger.error(f"failed to create app {app_name}")
                        continue

                    bp_view.add_node(bp_model.add_app(app))

                logger.info("bootstrapping relations...")

                for prov, req in imatrix.pairs:
                    for relation in imatrix.get_integrations(
                        provider=prov, requirer=req
                    ):
                        if isinstance(relation, PeerBinding):
                            # peer
                            edge = bp_model.add_peer_relation(
                                bp_model.find_app(model, prov), relation
                            )

                        elif isinstance(relation, RelationBinding):
                            # regular
                            edge = bp_model.add_relation(
                                bp_model.find_app(model, prov),
                                bp_model.find_app(model, req),
                                relation,
                            )

                        else:
                            raise ValueError(relation)

            logger.info("bootstrapping CMRs...")
            # now we've added all models, we can add cross-model relations
            def split_model(model_name) -> typing.Tuple[str, str]:
                """Split model name expressed in controller:username/model."""
                controller_name, _, model_name = re.compile(r"[:/]").split(model_name)
                return (model_name, controller_name)

            for model in controller.models:
                for cmr in model.cmrs:
                    model1 = bp_model.find_model(*split_model(cmr.provider_model))
                    app1 = bp_model.find_app(model1.model, cmr.provider_app)
                    model2 = bp_model.find_model(*split_model(cmr.requirer_model))
                    app2 = bp_model.find_app(model2.model, cmr.requirer_app)
                    edge = bp_model.add_cmr(app1, app2, cmr)
                    self._model.edges.add(edge)

        logger.info("binding all nodes...")
        bp_model.bind_all()

        logger.info("adding edges...")
        bp_view.add_all(self._model.edges)

        logger.info("arranging nodes...")
        bp_view.spread(bp_model.controller_nodes, bp_model.object_tree)

    def add_actions(self):
        # create all actions
        self._view.view_menu.addAction(
            QAction(
                "&Spread",
                self._view,
                statusTip="Auto-arrange all nodes.",
                triggered=self.spread,
            )
        )
        self._view.view_menu.addAction(
            QAction(
                "&Refresh",
                self._view,
                statusTip="Refresh the status.",
                triggered=self.refresh,
            )
        )
        self._view.view_menu.addAction(
            QAction(
                "&Collapse relations",
                self._view,
                statusTip="Show all relations as individual edges.",
                triggered=self.collapse_relations,
                checkable=True,
            )
        )

    def spread(self):
        self._view.spread(self._model.controller_nodes, self._model.object_tree)

    def clear(self):
        """Delete all nodes and data; clear the view."""
        self._model.clear()

    def refresh(self):
        self.clear()
        self.bootstrap()

    def add_edge(self, edge: "Edge"):
        self._model.edges.add(edge)
        edge.start.add_edge(edge, self._model.edges)
        self._view.add_edge(edge)

    def collapse_relations(self, collapse: bool):
        bp_view = self._view
        if collapse:
            bundles = {}
            for app1, app2 in product(self._model.app_nodes, repeat=2):
                if (app2, app1) in bundles:
                    # skip the inverse
                    continue

                if shared := self._model.edges.all_edges_between(app1, app2):
                    bundles[(app1, app2)] = [_to.edge for _to in shared]

            for (app1, app2), components in bundles.items():
                if not len(components) >= 2:
                    # pointless to bundle!
                    continue

                edge = CompoundEdge(start=app1, end=app2, components=components)
                self.add_edge(edge)
                edge.update()

                # remove from the scene all edges we have compounded
                for component in components:
                    component.remove(bp_view.nodeeditor.scene, self._model.edges)

        else:
            for node in bp_view.nodeeditor.nodes:
                if isinstance(node, AppNode):
                    # idempotency
                    edges = tuple(
                        e for e in node.connected_edges if isinstance(e, CompoundEdge)
                    )
                    for edge in edges:
                        edge.remove(bp_view.nodeeditor.scene, self._model.edges)
                        for component in edge.components:
                            self.add_edge(component)
