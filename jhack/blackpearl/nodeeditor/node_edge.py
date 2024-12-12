# -*- coding: utf-8 -*-
"""
A module containing NodeEditor's class for representing Edge and Edge Type Constants.
"""
from jhack.blackpearl.nodeeditor.node_graphics_edge import QDMGraphicsEdge


EDGE_TYPE_DIRECT = 1  #:
EDGE_TYPE_BEZIER = 2  #:
EDGE_TYPE_SQUARE = 3  #:
EDGE_TYPE_IMPROVED_SHARP = 4  #:
EDGE_TYPE_IMPROVED_BEZIER = 5  #:
EDGE_TYPE_DEFAULT = EDGE_TYPE_IMPROVED_BEZIER

DEBUG = False


class Edge:
    """
    Class for representing Edge in NodeEditor.
    """

    def __init__(self, gr_edge: QDMGraphicsEdge):
        self.gr_edge = gr_edge
