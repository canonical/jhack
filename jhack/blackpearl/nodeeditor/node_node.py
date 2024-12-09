# -*- coding: utf-8 -*-
"""
A module containing NodeEditor's class for representing `Node`.
"""
from collections import OrderedDict
from typing import Type

from jhack.blackpearl.nodeeditor.node_graphics_node import QDMGraphicsNode
from jhack.blackpearl.nodeeditor.node_content_widget import QDMNodeContentWidget
from jhack.blackpearl.nodeeditor.node_serializable import Serializable
from jhack.blackpearl.nodeeditor.node_socket import (
    Socket,
    LEFT_BOTTOM,
    LEFT_CENTER,
    LEFT_TOP,
    RIGHT_BOTTOM,
    RIGHT_CENTER,
    RIGHT_TOP,
)
from jhack.blackpearl.nodeeditor.utils_no_qt import dumpException, pp

DEBUG = False


class Node:
    """
    Class representing `Node` in the `Scene`.
    """

    def __init__(
        self,
        scene: "Scene",
        title: str = "Undefined Node",
        gr_node: Type[QDMGraphicsNode] = None,
        content: Type[QDMNodeContentWidget] = None,
    ):
        self._title = title
        super().__init__()

        self.scene = scene

        self.content = content(self) if content else QDMNodeContentWidget(self)
        self.gr_node = gr_node(self) if gr_node else QDMGraphicsNode(self)

        self.scene.add_node(self)
        self.scene.grScene.addItem(self.gr_node)

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

    def onEdgeConnectionChanged(self, new_edge: "Edge"):
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

    def doSelect(self, new_state: bool = True):
        """Shortcut method for selecting/deselecting the `Node`

        :param new_state: ``True`` if you want to select the `Node`. ``False`` if you want to deselect the `Node`
        :type new_state: ``bool``
        """
        self.gr_node.doSelect(new_state)

    def isSelected(self):
        """Returns ``True`` if current `Node` is selected"""
        return self.gr_node.isSelected()
