# -*- coding: utf-8 -*-
"""
A module containing the representation of the NodeEditor's Scene
"""
import json
import os
import sys
from collections import OrderedDict
from typing import Callable

from jhack.blackpearl.nodeeditor.node_edge import Edge
from jhack.blackpearl.nodeeditor.node_graphics_scene import QDMGraphicsScene
from jhack.blackpearl.nodeeditor.node_node import Node
from jhack.blackpearl.nodeeditor.utils_no_qt import dumpException

DEBUG_REMOVE_WARNINGS = False


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

        # suppress triggering on_item_selected
        self._silent_selection_events = False

        self._has_been_modified = False
        self._last_selected_items = None

        # initialize all listeners
        self._has_been_modified_listeners = []
        self._item_selected_listeners = []
        self._items_deselected_listeners = []

        # here we can store callback for retrieving the class for Nodes
        self.node_class_selector = None

        self.grScene = QDMGraphicsScene(self)
        self.grScene.setGrScene(self.scene_width, self.scene_height)

        self.grScene.itemSelected.connect(self.on_item_selected)
        self.grScene.itemsDeselected.connect(self.on_items_deselected)

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

            # call all registered listeners
            for callback in self._has_been_modified_listeners:
                callback()

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

    def on_item_selected(self, silent: bool = False):
        """
        Handle Item selection and trigger event `Item Selected`

        :param silent: If ``True`` scene's on_item_selected won't be called and history stamp not stored
        :type silent: ``bool``
        """
        if self._silent_selection_events:
            return

        current_selected_items = self.get_selected_items()
        if current_selected_items != self._last_selected_items:
            self._last_selected_items = current_selected_items
            if not silent:
                # we could create some kind of UI which could be serialized,
                # therefore first run all callbacks...
                for callback in self._item_selected_listeners:
                    callback()

    def on_items_deselected(self, silent: bool = False):
        """
        Handle Items deselection and trigger event `Items Deselected`

        :param silent: If ``True`` scene's on_items_deselected won't be called and history stamp not stored
        :type silent: ``bool``
        """
        # somehow this event is being triggered when we start dragging file outside of our application
        # or we just loose focus on our app? -- which does not mean we've deselected item in the scene!
        # double check if the selection has actually changed, since
        current_selected_items = self.get_selected_items()
        if current_selected_items == self._last_selected_items:
            # print("Qt itemsDeselected Invalid Event! Ignoring")
            return

        self.reset_last_selected_state()
        if not current_selected_items:
            self._last_selected_items = []
            if not silent:
                for callback in self._items_deselected_listeners:
                    callback()

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
        return self.grScene.selectedItems()

    # our helper listener functions
    def on_modified(self, callback: Callable):
        """
        Register callback for `Has Been Modified` event

        :param callback: callback function
        """
        self._has_been_modified_listeners.append(callback)

    # custom flag to detect node or edge has been selected....
    def reset_last_selected_state(self):
        """Resets internal `selected flags` in all `Nodes` and `Edges` in the `Scene`"""
        for node in self.nodes:
            node.gr_node._last_selected_state = False
        for edge in self.edges:
            edge.grEdge._last_selected_state = False

    def get_view(self) -> "QGraphicsView":
        """Shortcut for returning `Scene` ``QGraphicsView``

        :return: ``QGraphicsView`` attached to the `Scene`
        :rtype: ``QGraphicsView``
        """
        return self.grScene.views()[0]

    def add_node(self, node: Node):
        """Add :class:`~nodeeditor.node_node.Node` to this `Scene`

        :param node: :class:`~nodeeditor.node_node.Node` to be added to this `Scene`
        :type node: :class:`~nodeeditor.node_node.Node`
        """
        self.nodes.append(node)

    def add_edge(self, edge: Edge):
        """Add :class:`~nodeeditor.node_edge.Edge` to this `Scene`

        :param edge: :class:`~nodeeditor.node_edge.Edge` to be added to this `Scene`
        :return: :class:`~nodeeditor.node_edge.Edge`
        """
        self.edges.append(edge)

    def removeNode(self, node: Node):
        """Remove :class:`~nodeeditor.node_node.Node` from this `Scene`

        :param node: :class:`~nodeeditor.node_node.Node` to be removed from this `Scene`
        :type node: :class:`~nodeeditor.node_node.Node`
        """
        if node in self.nodes:
            self.nodes.remove(node)
        else:
            if DEBUG_REMOVE_WARNINGS:
                print(
                    "!W:",
                    "Scene::removeNode",
                    "wanna remove nodeeditor",
                    node,
                    "from self.nodes but it's not in the list!",
                )

    def removeEdge(self, edge: Edge):
        """Remove :class:`~nodeeditor.node_edge.Edge` from this `Scene`

        :param edge: :class:`~nodeeditor.node_edge.Edge` to be remove from this `Scene`
        :return: :class:`~nodeeditor.node_edge.Edge`
        """
        if edge in self.edges:
            self.edges.remove(edge)
        else:
            if DEBUG_REMOVE_WARNINGS:
                print(
                    "!W:",
                    "Scene::removeEdge",
                    "wanna remove edge",
                    edge,
                    "from self.edges but it's not in the list!",
                )

    def clear(self):
        """Remove all `Nodes` from this `Scene`. This causes also to remove all `Edges`"""
        while len(self.nodes) > 0:
            self.nodes[0].remove()

        self.has_been_modified = False

    def saveToFile(self, filename: str):
        """
        Save this `Scene` to the file on disk.

        :param filename: where to save this scene
        :type filename: ``str``
        """
        with open(filename, "w") as file:
            file.write(json.dumps(self.serialize(), indent=4))
            # print("saving to", filename, "was successfull.")

            self.has_been_modified = False
            self.filename = filename

    def loadFromFile(self, filename: str):
        """
        Load `Scene` from a file on disk

        :param filename: from what file to load the `Scene`
        :type filename: ``str``
        :raises: :class:`~nodeeditor.node_scene.InvalidFile` if there was an error decoding JSON file
        """

        with open(filename, "r") as file:
            raw_data = file.read()
            try:
                if sys.version_info >= (3, 9):
                    data = json.loads(raw_data)
                else:
                    data = json.loads(raw_data, encoding="utf-8")
                self.filename = filename
                self.deserialize(data)
                self.has_been_modified = False
            except json.JSONDecodeError:
                raise InvalidFile(
                    "%s is not a valid JSON file" % os.path.basename(filename)
                )
            except Exception as e:
                dumpException(e)

    def getEdgeClass(self):
        """Return the class representing Edge. Override me if needed"""
        return Edge
