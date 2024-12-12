# -*- coding: utf-8 -*-
"""
A module containing NodeEditor's class for representing `Node`.
"""
from typing import Type

from jhack.blackpearl.nodeeditor.node_graphics_node import QDMGraphicsNode
from jhack.blackpearl.nodeeditor.node_content_widget import QDMNodeContentWidget

DEBUG = False


class Node:
    """
    Class representing `Node` in the `Scene`.
    """

    def __init__(
        self,
        title: str = "Undefined Node",
        gr_node: Type[QDMGraphicsNode] = None,
        content: Type[QDMNodeContentWidget] = None,
    ):
        self._title = title
        self.content = content(self) if content else QDMNodeContentWidget(self)
        self.gr_node = gr_node(self) if gr_node else QDMGraphicsNode(self)

    def __str__(self):
        return "<%s:%s %s..%s>" % (
            self.title,
            self.__class__.__name__,
            hex(id(self))[2:5],
            hex(id(self))[-3:],
        )

    @property
    def title(self):
        """
        Title shown in the scene

        :getter: return current Node title
        :setter: sets Node title and passes it to Graphics Node class
        :type: ``str``
        """
        return self._title

    @title.setter
    def title(self, value):
        self._title = value
        self.gr_node.title = self._title

    def on_edge_connection_changed(self, new_edge: "Edge"):
        """
        Event handling that any connection (`Edge`) has changed. Currently not used...

        :param new_edge: reference to the changed :class:`~nodeeditor.node_edge.Edge`
        :type new_edge: :class:`~nodeeditor.node_edge.Edge`
        """
        pass

    def onInputChanged(self, socket: "Socket"):
        """Event handling when Node's input Edge has changed. We auto-mark this `Node` to be `Dirty` with all it's
        descendants

        :param socket: reference to the changed :class:`~nodeeditor.node_socket.Socket`
        :type socket: :class:`~nodeeditor.node_socket.Socket`
        """
        self.markDirty()
        self.markDescendantsDirty()

    def onDeserialized(self, data: dict):
        """Event manually called when this node was deserialized. Currently called when node is deserialized from scene
        Passing `data` containing the data which have been deserialized"""
        pass

    def onDoubleClicked(self, event):
        """Event handling double click on Graphics Node in `Scene`"""
        pass

    def isSelected(self):
        """Returns ``True`` if current `Node` is selected"""
        return self.gr_node.isSelected()
