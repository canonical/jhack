import typing
from enum import Enum

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.blackpearl.blackpearl.model.edge_map import EdgeMap
from jhack.blackpearl.blackpearl.view.graphics_edges import (
    GraphicsEdge,
    CMRGraphicsEdge,
    PeerRelationGraphicsEdge,
    CompoundRelationGraphicsEdge,
)
from jhack.blackpearl.nodeeditor.node_edge import Edge as node_Edge
from jhack.utils.helpers.gather_endpoints import (
    RelationBinding,
    PeerBinding,
)

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.view.node import Node
    from jhack.blackpearl.blackpearl.view.app_node import AppNode
    from jhack.blackpearl.nodeeditor.node_scene import Scene


logger = bp_logger.getChild(__file__)


class EdgeType(Enum):
    DIRECT = 1  #:
    BEZIER = 2  #:
    SQUARE = 3  #:
    IMPROVED_SHARP = 4  #:
    IMPROVED_BEZIER = 5  #:


class Edge(node_Edge):
    """
    Class for representing Edge in NodeEditor.
    """

    binding: typing.Union[RelationBinding, PeerBinding]
    gr_edge: GraphicsEdge

    def __repr__(self):
        return self.tooltip

    def __init__(self, start, end, gr_edge: GraphicsEdge):
        super().__init__(gr_edge=gr_edge)
        self.start = start
        self.end = end

        for label in gr_edge.labels:
            label.hide()  # begin hidden
            # self.scene.gr_scene.addItem(label)

        self.update()
        gr_edge.setToolTip(self.tooltip)

    @property
    def tooltip(self):
        return "n/a"

    def get_other(self, known: "Node"):
        return self.start if known == self.end else self.end

    def update(self):
        self.gr_edge.set_source(self.start.center)
        self.gr_edge.set_destination(self.end.center)
        self.gr_edge.update()

    def remove(self, scene: "Scene", edge_map: "EdgeMap"):
        self.gr_edge.hide()
        # remove self from scene
        scene.remove_edge(self)
        # remove self from edgemap
        edge_map.remove(self)

    def update_offset(self, edges: "EdgeMap"):
        # we want to know what parallel edges there are,
        # (i.e. between the same two nodes, direction doesn't matter)
        parallels = edges.all_edges_between(self.start, self.end)
        if len(parallels) == 1:
            return
        offset = [_to.edge for _to in parallels].index(self)
        if len(parallels) % 2:
            offset = -(offset - 1)
        self.gr_edge.pather.offset = offset


class RelationEdge(Edge):
    def __init__(self, binding: RelationBinding, start: "AppNode", end: "AppNode"):
        self.binding = binding
        super().__init__(start, end, gr_edge=GraphicsEdge(self))

    @property
    def tooltip(self):
        binding = self.binding
        start = self.start.title if self.start else "?"
        end = self.end.title if self.end else "?"
        return f"<{start}:{binding.provider_endpoint} -- [{binding.interface}] --> {binding.requirer_endpoint}:{end}>"


class CMREdge(Edge):
    def __init__(
        self,
        binding: RelationBinding,
        start: "AppNode",
        end: "AppNode",
    ):
        self.binding = binding
        super().__init__(start, end, gr_edge=CMRGraphicsEdge(self))

    @property
    def tooltip(self):
        binding = self.binding
        return f"<{binding.provider_endpoint} -- [{binding.interface}] --> {binding.requirer_endpoint}>"


class PeerRelationEdge(Edge):
    def __init__(
        self,
        binding: PeerBinding,
        node: "Node",
    ):
        self.binding = binding
        super().__init__(node, node, gr_edge=PeerRelationGraphicsEdge(self))

    @property
    def tooltip(self):
        return f"<{self.binding.endpoint} -O- [{self.binding.interface}]>"


class CompoundEdge(Edge):
    def __init__(
        self,
        start: "Node",
        end: "Node",
        components: typing.Iterable["Edge"],
    ):
        self.components = tuple(components)
        super().__init__(start, end, gr_edge=CompoundRelationGraphicsEdge(self))

    @property
    def tooltip(self):
        component_tooltips = "\n".join(
            component.tooltip for component in self.components
        )
        return f"<{component_tooltips}>"
