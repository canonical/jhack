import typing
from itertools import chain
from typing import Iterable

from qtpy.QtCore import QPointF

from jhack.blackpearl.blackpearl.model.edge_map import EdgeMap
from jhack.blackpearl.nodeeditor.node_content_widget import QDMNodeContentWidget
from jhack.blackpearl.nodeeditor.node_graphics_node import QDMGraphicsNode
from jhack.blackpearl.nodeeditor.node_node import Node
from jhack.blackpearl.blackpearl.view.edges import Edge


class NodeBase(Node):
    def __repr__(self):
        return f"<{type(self).__name__} {self.title}>"

    def __init__(
        self,
        parent: typing.Any,
        edges: EdgeMap,
        title: str = "unknown",
        gr_node: typing.Type[QDMGraphicsNode] = None,
        content: typing.Type[QDMNodeContentWidget] = None,
    ):
        super().__init__(title, gr_node=gr_node, content=content)
        self.parent = parent
        self.edges = edges
        self.bind_child_movement = True
        self.bound_children: typing.Set[NodeBase] = set()

    @property
    def edges_from(self):
        """List all edges from this node."""
        return [e.edge for e in self.edges.list_from(self)]

    @property
    def edges_to(self):
        """List all edges to this node."""
        return [e.edge for e in self.edges.list_to(self)]

    @property
    def connected_edges(self) -> typing.Set[Edge]:
        """List all edges from or to this node."""
        return set(
            to.edge
            for to in chain(self.edges.list_from(self), self.edges.list_to(self))
        )

    def bind_children(self, children: typing.Iterable[Node]):
        self.bound_children = children

    @property
    def center(self):
        return self.gr_node.center

    @property
    def pos(self):
        return self.gr_node.pos()

    def add_edge(self, edge: "Edge", edges: "EdgeMap"):
        edge.update_offset(edges)

    def set_pos(self, pos: QPointF, centered: bool = False):
        """Put the object in this position in parent coordinates."""
        if centered:
            pos -= QPointF(self.gr_node.width / 2, self.gr_node.height / 2)
        self.gr_node.setPos(pos)
        self.update_edges()

    def update_edges(self):
        """Recalculate (Refresh) positions of all connected Edges."""
        for edge in self.connected_edges:
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
