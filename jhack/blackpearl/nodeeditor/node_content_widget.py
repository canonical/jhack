# -*- coding: utf-8 -*-
"""A module containing the base class for the Node's content graphical representation. It also contains an example of
an overridden Text Widget, which can pass a notification to it's parent about being modified."""
from collections import OrderedDict
from jhack.blackpearl.nodeeditor.node_serializable import Serializable
from qtpy.QtWidgets import QWidget, QLabel, QVBoxLayout, QTextEdit


class QDMNodeContentWidget(QWidget):
    """Base class for representation of the Node's graphics content. This class also provides layout
    for other widgets inside of a :py:class:`~nodeeditor.node_node.Node`"""

    def __init__(self, node: "Node", parent: QWidget = None):
        self.node = node
        super().__init__(parent)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        self.layout.addWidget(self.widget)

    @property
    def widget(self):
        return QLabel("todo: widget")
