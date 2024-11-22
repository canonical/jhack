import dataclasses
import re
from code import interact
from typing import List, Dict, Optional, Tuple, Set

import typer

from jhack.helpers import juju_status, get_current_model, cached_juju_status

from jhack.logger import logger as jhack_logger

from jhack.utils.show_relation import (
    RelationEndpointURL,
    Relation,
    gather_relation_databags,
    AppRelationData,
    get_relation_by_endpoint,
    get_unit_info,
)

logger = jhack_logger.getChild("graph")

identifier = "[a-zA-Z-_0-9]"
RELATIONS_STATUS_RE = re.compile(
    f"(?P<provider_name>{identifier}+):(?P<provider_endpoint>{identifier}+)\s+"
    f"(?P<requirer_name>{identifier}+):(?P<requirer_endpoint>{identifier}+)\s+"
    f"(?P<interface>{identifier}+)\s+(?P<type>{identifier}+)"
    f"[\s+(?P<message>.+)]?"
)


@dataclasses.dataclass(frozen=True)
class _App:
    name: str
    model: str

    # raw juju status | jq | .applications[name]
    meta: Dict

    @property
    def scale(self):
        return len(self.meta["units"])

    def __hash__(self):
        return hash((self.model, self.name))

    @property
    def charm_name(self):
        return self.meta["charm-name"]


class Graph:
    """Graph type."""

    def __init__(self, graph: Dict[_App, List[Relation]], model: str):
        self._include_default_juju_keys = True
        self._graph = graph
        self._model = model
        self._relation_data: Dict[Relation, Tuple[AppRelationData, ...]] = {}

    def get_relation_data(self, relation: Relation):
        if relation.id is None:
            raise ValueError(relation)

        if not self._relation_data.get(relation):
            self._relation_data[relation] = gather_relation_databags(
                RelationEndpointURL(
                    f"{relation.requirer}:{relation.requirer_endpoint}"
                ),
                RelationEndpointURL(
                    f"{relation.provider}:{relation.provider_endpoint}"
                ),
                relation,
                model=self._model,
                include_default_juju_keys=self._include_default_juju_keys,
            )

        return self._relation_data[relation]

    @staticmethod
    def bootstrap(app_name: Optional[str] = None, model_name: str = None) -> "Graph":
        """Bootstrap a graph.

        From a single starting app url, or all of them otherwise.

        Example:
            >>> Graph.bootstrap("alertmanager/0", "microk8s-localhost:clite")
            >>> Graph.bootstrap(model_name="microk8s-localhost:clite")
        """
        if app_name:
            if "/" in app_name:
                logger.warning(
                    f"stripping unit ID suffix from {app_name}. Pass an app name instead."
                )
                app_name = app_name.split("/")[0]

            print(f"Bootstrapping graph from root: {model_name}.{app_name}")
        else:
            print(f"Bootstrapping graph in model {model_name}")

        model_status_cache = {}

        def get_status(model_name_, json: bool):
            if (model_name_, json) not in model_status_cache:
                model_status_cache[(model_name_, json)] = juju_status(
                    model=model_name_, json=json
                )
            return model_status_cache[(model_name_, json)]

        def get_app(app_name_, model_name_, status=None):
            status = status or get_status(model_name_, json=True)
            app_meta = status["applications"][app_name_]
            return _App(name=app_name_, model=model_name_, meta=app_meta)

        visited_applications: Set[str] = set()
        visited_relations: Set[Relation] = set()

        def walk(model_name_: str, app_name_: str, graph_=None):
            if app_name_ in visited_applications:
                return graph_

            visited_applications.add(app_name_)

            model_status_raw = get_status(model_name_, json=False)
            model_relations = RELATIONS_STATUS_RE.findall(model_status_raw)

            app = get_app(app_name_, model_name_)
            relations: List[Relation] = []
            graph_[app] = relations

            offers_meta = status.get("application-endpoints", ())

            for endpoint, bindings in app.meta["relations"].items():
                for binding in bindings:
                    remote_app_name = binding["related-application"]

                    if remote_app_name in offers_meta:
                        # CMR
                        remote_app_meta = offers_meta[remote_app_name]
                        # url is in the form 'localhost-localhost:admin/gagent1.gagent'
                        remote_model_name = remote_app_meta["url"].split(".")[0]
                        remote_app = get_app(remote_app_name, remote_model_name)
                    else:
                        remote_model_name = model_name_
                        remote_app = get_app(remote_app_name, model_name_)
                        remote_app_meta = remote_app.meta

                    if remote_app not in graph_:
                        walk(remote_model_name, remote_app_name, graph_)

                    remote_endpoint = _find_remote_endpoint(
                        remote_app_meta, app_name_, binding["interface"]
                    )

                    if remote_model_name == model_name_:
                        # todo subordinate check
                        if remote_app_name == app_name_:
                            relation_type = "peer"
                        else:
                            relation_type = "regular"
                    else:
                        relation_type = "cross_model"

                    # todo compare provider, provider-endpoint, requirer.... with the raw relation data

                    rel_footprint = (
                        app_name_,
                        endpoint,
                        remote_app_name,
                        remote_endpoint,
                        binding["interface"],
                    )
                    if rel_footprint not in model_relations:
                        continue

                    rel = Relation(
                        provider=app_name_,
                        provider_endpoint=endpoint,
                        requirer=remote_app_name,
                        requirer_endpoint=remote_endpoint,  # todo
                        interface=binding["interface"],
                        raw_type=relation_type,
                        id=_find_relation_id(
                            app_name_,
                            model_name_,
                            endpoint,
                            remote_endpoint,
                            remote_app_name,
                        ),
                    )

                    if rel in visited_relations:
                        continue

                    relations.append(rel)
                    visited_relations.add(rel)

            return graph_

        model_ = model_name or get_current_model()

        if not app_name:
            graph = {}
            cached_status = cached_juju_status(model=model_, json=True)
            for app_name in cached_status["applications"]:
                graph = walk(model_, app_name, graph)

        else:
            graph = walk(model_, app_name, {})

        return Graph(graph, model=model_)

    def plot(self):
        print("GRAPH:")
        for origin, relations in self._graph.items():
            print(f"\t{origin.name} ({origin.charm_name}) :: {{")
            for relation in relations:
                print(
                    f"\t\t({relation.provider}) {relation.provider_endpoint} >> "
                    f"{relation.requirer_endpoint} ({relation.requirer})"
                )
                if reldata := self.get_relation_data(relation):
                    print(
                        f"\t\t\tRelation found: "
                        f"{reldata[0].url} --> "
                        f"{reldata[1].url if len(reldata) == 2 else '<itself>'} "
                        f"({relation.id})"
                    )
            print(f"\t}}")


def _map(app_name: str, model_name: str):
    graph = Graph.bootstrap(app_name=app_name, model_name=model_name)
    graph.plot()


def unravel(
    app_name: Optional[str] = typer.Argument(
        None, help="""The starting point of the graph expansion."""
    ),
    model_name: str = typer.Option(
        None,
        "-m",
        "--model",
        help="The model in which to find the app from which to start the unraveling.",
    ),
):
    _map(app_name=app_name, model_name=model_name)


if __name__ == "__main__":
    # jhack unravel traefik/0
    Graph.bootstrap("tempo/0").plot()
