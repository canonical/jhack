import typing

from PyQt6.QtCore import QPointF
from qtpy.QtGui import QDragMoveEvent

from jhack.blackpearl.nodeeditor.node_content_widget import QDMNodeContentWidget
from jhack.blackpearl.nodeeditor.node_graphics_node import QDMGraphicsNode
from jhack.blackpearl.nodeeditor.node_node import Node

if typing.TYPE_CHECKING:
    from jhack.blackpearl.nodeeditor.node_scene import Scene
from jhack.blackpearl.blackpearl.view.edges import Edge


class NodeBase(Node):
    def __init__(
        self,
        parent: typing.Any,
        scene: "Scene",
        title: str = "unknown",
        gr_node: typing.Type[QDMGraphicsNode] = None,
        content: typing.Type[QDMNodeContentWidget] = None,
    ):
        super().__init__(scene, title, gr_node=gr_node, content=content)
        self.parent = parent
        self.bind_child_movement = True
        self.bound_children: typing.Set[NodeBase] = set()
        self.edges: typing.List["Edge"] = []

    def bind_children(self, children: typing.Iterable[Node]):
        self.bound_children = children

    @property
    def center(self):
        return self.gr_node.center

    @property
    def pos(self):
        return self.gr_node.pos()

    def add_edge(self, edge: typing.Union["Edge"]):
        # we want to know how many parallel edges there are,
        # (i.e. between the same two nodes, direction doesn't matter)
        nodes = {edge.start, edge.end}
        n_parallel_edges = len(
            tuple(e for e in self.edges if e.start in nodes and e.end in nodes)
        )

        offset = n_parallel_edges
        if n_parallel_edges % 2:
            offset = -(offset - 1)
        edge.grEdge.pather.offset = offset

        self.edges.append(edge)

    def set_pos(self, pos: QPointF, centered: bool = False):
        """Put the object in this position in parent coordinates."""
        if centered:
            pos -= QPointF(self.gr_node.width / 2, self.gr_node.height / 2)
        self.gr_node.setPos(pos)
        self.update_connected_edges()

    def update_connected_edges(self):
        """Recalculate (Refresh) positions of all connected `Edges`. Used for updating Graphics Edges"""
        for edge in self.edges:
            edge.update()


class GrNodeBase(QDMGraphicsNode):
    node: NodeBase

    @property
    def center(self):
        # center is in local coordinates
        return self.mapToScene(self.boundingRect().center())

    def onMoved(self, vector):
        if self.node.bind_child_movement:
            for child in self.node.bound_children:
                new_pos = child.pos + vector
                child.set_pos(new_pos)
                child.gr_node.onMoved(vector)
