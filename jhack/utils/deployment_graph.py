import dataclasses
from typing import List, Dict

import typer

from jhack.helpers import juju_status, get_current_model

from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("graph")


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


@dataclasses.dataclass(frozen=True)
class _Relation:
    remote_app: _App
    endpoint: str
    meta: Dict
    endpoint_to: str

    @property
    def interface(self):
        return self.meta["interface"]


class Graph:
    """Graph type."""

    def __init__(self, graph: Dict[_App, List[_Relation]]):
        self._graph = graph

    @staticmethod
    def bootstrap(app_name: str, model_name: str = None) -> "Graph":
        """Bootstrap a graph from a single starting app url.

        Example:
            >>> Graph.bootstrap("microk8s-localhost:clite.alertmanager/0")
        """
        if "/" in app_name:
            logger.warning(
                f"stripping unit ID suffix from {app_name}. Pass an app name instead."
            )
            app_name = app_name.split("/")[0]

        print(f"Bootstrapping graph from root: {model_name}.{app_name}")

        model_status_cache = {}

        def get_status(model_name_):
            if model_name_ not in model_status_cache:
                model_status_cache[model_name_] = juju_status(
                    model=model_name_, json=True
                )
            return model_status_cache[model_name_]

        def get_app(app_name_, model_name_, status=None):
            status = status or get_status(model_name_)
            app_meta = status["applications"][app_name_]
            return _App(name=app_name_, model=model_name_, meta=app_meta)

        def walk(model_name_: str, app_name_: str, graph_=None):
            status = get_status(model_name_)
            app = get_app(app_name_, model_name_)
            relations: List[_Relation] = []
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

                    if remote_app not in graph_:
                        walk(remote_model_name, remote_app_name, graph_)

                    rel = _Relation(
                        remote_app=remote_app,
                        endpoint=endpoint,
                        meta=binding,
                        endpoint_to="",  # todo
                    )
                    relations.append(rel)

            return graph_

        graph = walk(model_name or get_current_model(), app_name, {})
        return Graph(graph)

    def plot(self):
        print("GRAPH:")
        for origin, destination in self._graph.items():
            print(f"\t{origin} --> {{")
            for app in destination:
                print(f"\t\t{app}")
            print(f"\t}}")


def _map(app_name: str, model_name: str):
    graph = Graph.bootstrap(app_name=app_name, model_name=model_name)
    graph.plot()


def unravel(
    app_name: str = typer.Argument(
        ..., help="""The starting point of the graph expansion."""
    ),
    model_name: str = typer.Option(
        "-m",
        "--model",
        help="The model in which to find the app from which to start the unraveling.",
    ),
):
    _map(app_name=app_name, model_name=model_name)


if __name__ == "__main__":
    Graph.bootstrap("loki").plot()
