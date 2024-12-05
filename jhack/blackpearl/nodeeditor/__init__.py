# -*- coding: utf-8 -*-

__name__ = 'NodeEditor'
__author__ = 'Pavel Křupala'
__version__ = '0.9.15'


_QT_API_NAME, _QT_API_VERSION = None, None

if _QT_API_NAME is None:
    try:
        from PyQt5.QtCore import PYQT_VERSION_STR
        _QT_API_NAME, _QT_API_VERSION = "pyqt5", PYQT_VERSION_STR
    except ImportError:
        pass

if _QT_API_NAME is None:
    try:
        from PySide2 import __version__
        _QT_API_NAME, _QT_API_VERSION = "pyside2", __version__
    except ImportError:
        pass

if _QT_API_NAME is None:
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR
        _QT_API_NAME, _QT_API_VERSION = "pyqt6", PYQT_VERSION_STR
    except ImportError:
        pass

if _QT_API_NAME is None:
    try:
        from PySide6 import __version__
        _QT_API_NAME, _QT_API_VERSION = "pyside6", __version__
    except ImportError:
        pass

# don't be too strict yet...
# if _QT_API_NAME is None:
#     raise ImportError("Please install PyQt5/PySide2 or PyQt6/PySide6")
