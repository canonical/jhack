# -*- coding: utf-8 -*-
"""
A module containing the representation of the NodeEditor's Scene
"""
import logging
import typing

from jhack.blackpearl.blackpearl.view.app_node import AppGraphicsNode
from jhack.blackpearl.nodeeditor.node_edge import Edge
from jhack.blackpearl.nodeeditor.node_graphics_scene import QDMGraphicsScene
from jhack.blackpearl.nodeeditor.node_node import Node

if typing.TYPE_CHECKING:
    from jhack.blackpearl.nodeeditor.node_graphics_view import QDMGraphicsView

DEBUG_REMOVE_WARNINGS = False
logger = logging.getLogger(__file__)


class InvalidFile(Exception):
    pass


class Scene:
    """Class representing NodeEditor's `Scene`"""

    def __init__(self):
        """
        :Instance Attributes:

            - **nodes** - list of `Nodes` in this `Scene`
            - **edges** - list of `Edges` in this `Scene`
            - **scene_width** - width of this `Scene` in pixels
            - **scene_height** - height of this `Scene` in pixels
        """
        super().__init__()
        self.nodes = []
        self.edges = []

        # current filename assigned to this scene
        self.filename = None

        self.scene_width = 64000
        self.scene_height = 64000

        self._has_been_modified = False
        self._last_selected_items = []
        # here we can store callback for retrieving the class for Nodes
        self.node_class_selector = None

        self.gr_scene = QDMGraphicsScene(self)
        self.gr_scene.setgr_scene(self.scene_width, self.scene_height)

        self.gr_scene.itemSelected.connect(self.on_item_selected)
        self.gr_scene.itemsDeselected.connect(self.on_items_deselected)

    @property
    def has_been_modified(self):
        """
        Has this `Scene` been modified?

        :getter: ``True`` if the `Scene` has been modified
        :setter: set new state. Triggers `Has Been Modified` event
        :type: ``bool``
        """
        return self._has_been_modified

    @has_been_modified.setter
    def has_been_modified(self, value):
        if not self._has_been_modified and value:
            # set it now, because we will be reading it soon
            self._has_been_modified = value

        self._has_been_modified = value

    def get_node_by_id(self, node_id: int):
        """
        Find node in the scene according to provided `node_id`

        :param node_id: ID of the node we are looking for
        :type node_id: ``int``
        :return: Found ``Node`` or ``None``
        """
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def on_item_selected(self):
        """
        Handle Item selection and trigger event `Item Selected`

        :param silent: If ``True`` scene's on_item_selected won't be called and history stamp not stored
        :type silent: ``bool``
        """
        selected = self.view.selected_items()
        for item in selected:
            if isinstance(item, AppGraphicsNode):
                item.onSelected()

    def on_items_deselected(self):
        deselected = self.view.deselected_items()
        for item in deselected:
            if isinstance(item, AppGraphicsNode):
                item.onDeselected()

        # current_selected_items = self.get_selected_items()
        if not deselected:
            logger.warning("nothing was deselected; ignoring event...")
            return
        self.reset_last_selected_state()

    def isModified(self) -> bool:
        """Is this `Scene` dirty aka `has been modified` ?

        :return: ``True`` if `Scene` has been modified
        :rtype: ``bool``
        """
        return self.has_been_modified

    def get_selected_items(self) -> list:
        """
        Returns currently selected Graphics Items

        :return: list of ``QGraphicsItems``
        :rtype: list[QGraphicsItem]
        """
        return self.gr_scene.selectedItems()

    # custom flag to detect node or edge has been selected....
    def reset_last_selected_state(self):
        """Resets internal `selected flags` in all `Nodes` and `Edges` in the `Scene`"""
        for node in self.nodes:
            node.gr_node._last_selected_state = False
        for edge in self.edges:
            edge.gr_edge._last_selected_state = False

    @property
    def view(self) -> "QDMGraphicsView":
        """Shortcut for returning `Scene` ``QGraphicsView``

        :return: ``QGraphicsView`` attached to the `Scene`
        :rtype: ``QGraphicsView``
        """
        return self.gr_scene.views()[0]

    def add_node(self, node: Node):
        """Add :class:`~nodeeditor.node_node.Node` to this `Scene`

        :param node: :class:`~nodeeditor.node_node.Node` to be added to this `Scene`
        :type node: :class:`~nodeeditor.node_node.Node`
        """
        self.nodes.append(node)
        self.gr_scene.addItem(node.gr_node)

        # FIXME: this is uncool, but some logic in grnode needs access to the scene.
        node.scene = self

    def add_edge(self, edge: Edge):
        """Add :class:`~nodeeditor.node_edge.Edge` to this `Scene`

        :param edge: :class:`~nodeeditor.node_edge.Edge` to be added to this `Scene`
        :return: :class:`~nodeeditor.node_edge.Edge`
        """
        self.edges.append(edge)
        self.gr_scene.addItem(edge.gr_edge)
        edge.gr_edge.show()

    def remove_node(self, node: Node):
        """Remove :class:`~nodeeditor.node_node.Node` from this `Scene`

        :param node: :class:`~nodeeditor.node_node.Node` to be removed from this `Scene`
        :type node: :class:`~nodeeditor.node_node.Node`
        """
        self.nodes.remove(node)
        self.gr_scene.removeItem(node.gr_node)

    def remove_edge(self, edge: Edge):
        """Remove :class:`~nodeeditor.node_edge.Edge` from this `Scene`

        :param edge: :class:`~nodeeditor.node_edge.Edge` to be remove from this `Scene`
        :return: :class:`~nodeeditor.node_edge.Edge`
        """
        self.edges.remove(edge)
        self.gr_scene.removeItem(edge.gr_edge)

    def clear(self):
        """Remove all `Nodes` from this `Scene`. This causes also to remove all `Edges`"""
        while len(self.nodes) > 0:
            self.nodes[0].remove()

        self.has_been_modified = False
