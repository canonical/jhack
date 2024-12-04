import typing
from qtpy.QtGui import QDragMoveEvent

from nodeeditor.node_graphics_node import QDMGraphicsNode
from nodeeditor.node_node import Node

if typing.TYPE_CHECKING:
    from nodeeditor.node_scene import Scene


class NodeBase(Node):
    def __init__(
        self,
        parent: typing.Any,
        scene: "Scene",
        title: str = "unknown",
    ):
        super().__init__(scene, title, [], [])
        self.parent = parent
        self.bind_child_movement = True
        self.bound_children = set()

    def bind_children(self, children: typing.Iterable[Node]):
        self.bound_children = children

    @property
    def center(self):
        return self.grNode.center


class GrNodeBase(QDMGraphicsNode):
    node: NodeBase
    bound_children: typing.Set[NodeBase]

    def onMoved(self, vector):
        if self.node.bind_child_movement:
            for child in self.node.bound_children:
                new_pos = child.pos + vector
                child.setPos(new_pos.x(), new_pos.y())
                child.grNode.onMoved(vector)
