import logging
import typing
from itertools import chain
from operator import itemgetter
from typing import Dict, List, NamedTuple

from black.trans import defaultdict


if typing.TYPE_CHECKING:
    from jhack.blackpearl.nodeeditor.node_node import Node
    from jhack.blackpearl.blackpearl.view.edges import Edge, logger


logger = logging.getLogger(__file__)


class _To(NamedTuple):
    node: "Node"
    edge: "Edge"


class EdgeMap:
    def __init__(self):
        self._graph: Dict["Node", List[_To]] = defaultdict(list)
        self._reversed: Dict["Node", List[_To]] = defaultdict(list)

    def add(self, edge: "Edge"):
        self._graph[edge.start].append(_To(edge.end, edge))
        self._reversed[edge.end].append(_To(edge.start, edge))

    def clear(self):
        self._graph.clear()
        self._reversed.clear()

    def remove(self, edge: "Edge"):
        try:
            self._graph[edge.start].remove(_To(edge.end, edge))
        except ValueError:
            logger.exception(f"cannot remove {edge} from map")
        try:
            self._reversed[edge.end].remove(_To(edge.start, edge))
        except ValueError:
            logger.exception(f"cannot remove {edge} from reverse map")

    def list_from(self, start: "Node"):
        return self._graph[start]

    def list_to(self, end: "Node"):
        return self._reversed[end]

    def iter_all(self):
        """Iterate through all edges in this map."""
        yield from map(itemgetter(1), chain(*self._graph.values()))

    def all_edges_between(self, node1: "Node", node2: "Node"):
        # use set to skip duplicates (peer edges)
        return sorted(
            set(e for e in self.list_from(node1) if e.edge.end is node2).union(
                set(e for e in self.list_from(node2) if e.edge.end is node1)
            ),
            # assume the edge's str/tooltip to contains enough info to sort this stably enough
            key=lambda to: str(to.edge),
        )
