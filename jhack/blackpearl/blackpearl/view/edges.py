from collections import OrderedDict

import typing
from enum import Enum

from jhack.blackpearl.blackpearl.view.graphics_edges import (
    GraphicsEdge,
    CMRGraphicsEdge,
    PeerRelationGraphicsEdge,
)
from jhack.blackpearl.nodeeditor.node_scene import Scene
from jhack.blackpearl.nodeeditor.node_serializable import Serializable

from jhack.blackpearl.blackpearl.logger import bp_logger
from jhack.utils.helpers.gather_endpoints import (
    RelationBinding,
    PeerBinding,
)

if typing.TYPE_CHECKING:
    from jhack.blackpearl.blackpearl.view.node import Node
    from jhack.blackpearl.blackpearl.view.app_node import AppNode

logger = bp_logger.getChild(__file__)


class EdgeType(Enum):
    DIRECT = 1  #:
    BEZIER = 2  #:
    SQUARE = 3  #:
    IMPROVED_SHARP = 4  #:
    IMPROVED_BEZIER = 5  #:


class Edge(Serializable):
    """
    Class for representing Edge in NodeEditor.
    """

    binding: typing.Union[RelationBinding, PeerBinding]

    def __repr__(self):
        return self.tooltip

    def __init__(self, scene: "Scene", gr_edge: GraphicsEdge):
        super().__init__()
        self.scene = scene

        # create Graphics Edge instance
        self.grEdge = GraphicsEdge(self)
        self.scene.add_edge(self)
        self.scene.grScene.addItem(self.grEdge)

        for label in self.grEdge.labels:
            label.hide()  # begin hidden
            self.scene.grScene.addItem(label)

        self.update()

    @property
    def tooltip(self):
        return "n/a"

    def get_other(self, known: "Node"):
        return self.start if known == self.end else self.end

    def update(self):
        self.grEdge.set_source(self.start.center)
        self.grEdge.set_destination(self.end.center)
        self.grEdge.update()

    def remove(self, silent=False):
        ends = [self.start, self.end]
        self.start = None
        self.end = None

        self.grEdge.hide()
        self.scene.grScene.removeItem(self.grEdge)
        self.scene.grScene.update()

        try:
            self.scene.removeEdge(self)
        except ValueError:
            pass

        for end in ends:
            if silent:
                continue
            try:
                end.onEdgeConnectionChanged(self)
            except Exception as e:
                logger.exception(f"failed to notify node {end} that {self} is going")

    def serialize(self) -> OrderedDict:
        return OrderedDict(
            [
                ("id", self.id),
                ("start", self.start.id if self.start is not None else None),
                ("end", self.end.id if self.end is not None else None),
            ]
        )

    def deserialize(
        self, data: dict, hashmap: dict = {}, restore_id: bool = True, *args, **kwargs
    ) -> bool:
        if restore_id:
            self.id = data["id"]
        self.start = hashmap[data["start"]]
        self.end = hashmap[data["end"]]
        return True


class RelationEdge(Edge):
    def __init__(
        self, scene: "Scene", binding: RelationBinding, start: "AppNode", end: "AppNode"
    ):
        self.binding = binding
        self.start = start
        self.end = end
        super().__init__(scene, gr_edge=GraphicsEdge(self))

    @property
    def tooltip(self):
        binding = self.binding
        return f"<{binding.provider_endpoint} -- [{binding.interface}] --> {binding.requirer_endpoint}>"


class CMREdge(Edge):
    def __init__(
        self,
        scene: "Scene",
        binding: RelationBinding,
        start: "AppNode",
        end: "AppNode",
    ):
        self.binding = binding
        self.start = start
        self.end = end
        super().__init__(scene, gr_edge=CMRGraphicsEdge(self))

    @property
    def tooltip(self):
        binding = self.binding
        return f"<{binding.provider_endpoint} -- [{binding.interface}] --> {binding.requirer_endpoint}>"


class PeerRelationEdge(Edge):
    def __init__(
        self,
        scene: "Scene",
        binding: PeerBinding,
        node: "Node",
    ):
        self.binding = binding
        self.start = node
        self.end = node
        super().__init__(scene, gr_edge=PeerRelationGraphicsEdge(self))

    @property
    def tooltip(self):
        return f"<{self.binding.endpoint} -O- [{self.binding.interface}]>"
