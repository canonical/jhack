# -*- coding: utf-8 -*-
"""
A module containing the Main Window class
"""
from qtpy.QtWidgets import (
    QMainWindow,
)


class NodeEditorWindow(QMainWindow):
    def __init__(self):
        """
        :Instance Attributes:

        - **name_company** - name of the company, used for permanent profile settings
        - **name_product** - name of this App, used for permanent profile settings
        """
        super().__init__()
