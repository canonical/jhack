# -*- encoding: utf-8 -*-
"""
Module with some helper functions
"""
from jhack.blackpearl.nodeeditor import _QT_API_NAME as QT_API
from qtpy.QtCore import QFile
from qtpy.QtWidgets import QApplication

from jhack.blackpearl.nodeeditor.utils_no_qt import pp, dumpException


def loadStylesheet(filename: str):
    """
    Loads an qss stylesheet to the current QApplication instance

    :param filename: Filename of qss stylesheet
    :type filename: str
    """
    print("STYLE loading:", filename)
    file = QFile(filename)
    file.open(QFile.ReadOnly | QFile.Text)
    stylesheet = file.readAll()
    QApplication.instance().setStyleSheet(str(stylesheet, encoding="utf-8"))


def loadStylesheets(*args):
    """
    Loads multiple qss stylesheets. Concatenates them together and applies the final stylesheet to the current QApplication instance

    :param args: variable number of filenames of qss stylesheets
    :type args: str, str,...
    """
    res = ""
    for arg in args:
        file = QFile(arg)
        file.open(QFile.ReadOnly | QFile.Text)
        stylesheet = file.readAll()
        res += "\n" + str(stylesheet, encoding="utf-8")
    QApplication.instance().setStyleSheet(res)


def isCTRLPressed(event):
    from qtpy.QtCore import Qt

    if QT_API in ("pyqt5", "pyside2"):
        return event.modifiers() & Qt.CTRL
    if QT_API in ("pyqt6", "pyside6"):
        return event.modifiers() & Qt.KeyboardModifier.ControlModifier


def isSHIFTPressed(event):
    from qtpy.QtCore import Qt

    if QT_API in ("pyqt5", "pyside2"):
        return event.modifiers() & Qt.SHIFT
    if QT_API in ("pyqt6", "pyside6"):
        return event.modifiers() & Qt.KeyboardModifier.ShiftModifier


def isALTPressed(event):
    from qtpy.QtCore import Qt

    if QT_API in ("pyqt5", "pyside2"):
        return event.modifiers() & Qt.ALT
    if QT_API in ("pyqt6", "pyside6"):
        return event.modifiers() & Qt.KeyboardModifier.AltModifier
