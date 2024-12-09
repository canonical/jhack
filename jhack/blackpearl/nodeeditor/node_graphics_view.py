# -*- coding: utf-8 -*-
"""
A module containing `Graphics View` for NodeEditor
"""
from qtpy.QtCore import Signal, QPoint, Qt, QEvent
from qtpy.QtGui import (
    QPainter,
    QDragEnterEvent,
    QDropEvent,
    QMouseEvent,
    QWheelEvent,
)
from qtpy.QtWidgets import QGraphicsView, QApplication

from jhack.blackpearl.nodeeditor import _QT_API_NAME as QT_API
from jhack.blackpearl.nodeeditor.node_graphics_edge import QDMGraphicsEdge
from jhack.blackpearl.nodeeditor.utils import (
    dumpException,
    isCTRLPressed,
    isSHIFTPressed,
)

MODE_NOOP = 1  #: Mode representing ready state
MODE_EDGE_DRAG = 2  #: Mode representing when we drag edge state
MODE_EDGE_CUT = 3  #: Mode representing when we draw a cutting edge
MODE_EDGES_REROUTING = 4  #: Mode representing when we re-route existing edges
MODE_NODE_DRAG = 5  #: Mode representing when we drag a node to calculate dropping on intersecting edge

STATE_STRING = ["", "Noop", "Edge Drag", "Edge Cut", "Edge Rerouting", "Node Drag"]

#: Distance when click on socket to enable `Drag Edge`
EDGE_DRAG_START_THRESHOLD = 50

#: Enable UnrealEngine style rerouting
EDGE_REROUTING_UE = True

#: Socket snapping distance
EDGE_SNAPPING_RADIUS = 24
#: Enable socket snapping feature
EDGE_SNAPPING = True

DEBUG = False
DEBUG_MMB_SCENE_ITEMS = False
DEBUG_MMB_LAST_SELECTIONS = False
DEBUG_EDGE_INTERSECT = False
DEBUG_STATE = False


class QDMGraphicsView(QGraphicsView):
    """Class representing NodeEditor's `Graphics View`"""

    #: pyqtSignal emitted when cursor position on the `Scene` has changed
    scenePosChanged = Signal(int, int)

    def __init__(self, grScene: "QDMGraphicsScene", parent: "QWidget" = None):
        """
        :param grScene: reference to the :class:`~nodeeditor.node_graphics_scene.QDMGraphicsScene`
        :type grScene: :class:`~nodeeditor.node_graphics_scene.QDMGraphicsScene`
        :param parent: parent widget
        :type parent: ``QWidget``

        :Instance Attributes:

        - **grScene** - reference to the :class:`~nodeeditor.node_graphics_scene.QDMGraphicsScene`
        - **mode** - state of the `Graphics View`
        - **zoomInFactor**- ``float`` - zoom step scaling, default 1.25
        - **zoomClamp** - ``bool`` - do we clamp zooming or is it infinite?
        - **zoom** - current zoom step
        - **zoomStep** - ``int`` - the relative zoom step when zooming in/out
        - **zoomRange** - ``[min, max]``

        """
        super().__init__(parent)
        self.grScene = grScene

        self.initUI()

        self.setScene(self.grScene)

        self.mode = MODE_NOOP
        self.editingFlag = False
        self.rubberBandDraggingRectangle = False

        self.last_scene_mouse_position = QPoint(0, 0)
        self.zoomInFactor = 1.25
        self.zoomClamp = True
        self.zoom = 10
        self.zoomStep = 1
        self.zoomRange = [0, 10]

        # listeners
        self._drag_enter_listeners = []
        self._drop_listeners = []

    def initUI(self):
        """Set up this ``QGraphicsView``"""
        # self.setRenderHints(QPainter.Antialiasing | QPainter.HighQualityAntialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
            | QPainter.SmoothPixmapTransform
        )

        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.RubberBandDrag)

        # enable dropping
        self.setAcceptDrops(True)

    def resetMode(self):
        """Helper function to re-set the grView's State Machine state to the default"""
        self.mode = MODE_NOOP

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Trigger our registered `Drag Enter` events"""
        for callback in self._drag_enter_listeners:
            callback(event)

    def dropEvent(self, event: QDropEvent):
        """Trigger our registered `Drop` events"""
        for callback in self._drop_listeners:
            callback(event)

    def addDragEnterListener(self, callback: "function"):
        """
        Register callback for `Drag Enter` event

        :param callback: callback function
        """
        self._drag_enter_listeners.append(callback)

    def addDropListener(self, callback: "function"):
        """
        Register callback for `Drop` event

        :param callback: callback function
        """
        self._drop_listeners.append(callback)

    def mousePressEvent(self, event: QMouseEvent):
        """Dispatch Qt's mousePress event to corresponding function below"""
        if event.button() == Qt.MiddleButton:
            self.middleMouseButtonPress(event)
        elif event.button() == Qt.LeftButton:
            self.leftMouseButtonPress(event)
        elif event.button() == Qt.RightButton:
            self.rightMouseButtonPress(event)
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Dispatch Qt's mouseRelease event to corresponding function below"""
        if event.button() == Qt.MiddleButton:
            self.middleMouseButtonRelease(event)
        elif event.button() == Qt.LeftButton:
            self.leftMouseButtonRelease(event)
        elif event.button() == Qt.RightButton:
            self.rightMouseButtonRelease(event)
        else:
            super().mouseReleaseEvent(event)

    def middleMouseButtonPress(self, event: QMouseEvent):
        """When Middle mouse button was pressed"""
        # faking events for enable MMB dragging the scene
        if QT_API in ("pyqt5", "pyside2"):
            releaseEvent = QMouseEvent(
                QEvent.MouseButtonRelease,
                event.localPos(),
                event.screenPos(),
                Qt.LeftButton,
                Qt.NoButton,
                event.modifiers(),
            )
        elif QT_API in ("pyqt6", "pyside6"):
            releaseEvent = QMouseEvent(
                QEvent.MouseButtonRelease,
                event.localPos(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                event.modifiers(),
            )
        super().mouseReleaseEvent(releaseEvent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        if QT_API in ("pyqt5", "pyside2"):
            fakeEvent = QMouseEvent(
                event.type(),
                event.localPos(),
                event.screenPos(),
                Qt.LeftButton,
                event.buttons() | Qt.LeftButton,
                event.modifiers(),
            )
        elif QT_API in ("pyqt6", "pyside6"):
            fakeEvent = QMouseEvent(
                event.type(),
                event.localPos(),
                Qt.MouseButton.LeftButton,
                event.buttons() | Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
        super().mousePressEvent(fakeEvent)

    def middleMouseButtonRelease(self, event: QMouseEvent):
        """When Middle mouse button was released"""
        if QT_API in ("pyqt5", "pyside2"):
            fakeEvent = QMouseEvent(
                event.type(),
                event.localPos(),
                event.screenPos(),
                Qt.LeftButton,
                event.buttons() & ~Qt.LeftButton,
                event.modifiers(),
            )
        elif QT_API in ("pyqt6", "pyside6"):
            fakeEvent = QMouseEvent(
                event.type(),
                event.localPos(),
                Qt.MouseButton.LeftButton,
                event.buttons() & ~Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
        super().mouseReleaseEvent(fakeEvent)
        self.setDragMode(QGraphicsView.RubberBandDrag)

    def leftMouseButtonPress(self, event: QMouseEvent):
        """When Left  mouse button was pressed"""

        # get the item we clicked on
        item = self.getItemAtClick(event)

        # we store the position of last LMB click
        self.last_lmb_click_scene_pos = self.mapToScene(event.pos())

        # if DEBUG: print("LMB Click on", item, self.debug_modifiers(event))

        # logic - Shift + LMB Node
        if hasattr(item, "node") or isinstance(item, QDMGraphicsEdge) or item is None:
            if isSHIFTPressed(event):
                event.ignore()
                if QT_API in ("pyqt5", "pyside2"):
                    fakeEvent = QMouseEvent(
                        QEvent.MouseButtonPress,
                        event.localPos(),
                        event.screenPos(),
                        Qt.LeftButton,
                        event.buttons() | Qt.LeftButton,
                        event.modifiers() | Qt.ControlModifier,
                    )
                elif QT_API in ("pyqt6", "pyside6"):
                    fakeEvent = QMouseEvent(
                        QEvent.MouseButtonPress,
                        event.localPos(),
                        Qt.MouseButton.LeftButton,
                        event.buttons() | Qt.MouseButton.LeftButton,
                        event.modifiers() | Qt.KeyboardModifier.ControlModifier,
                    )
                super().mousePressEvent(fakeEvent)
                return

        if hasattr(item, "node"):
            if DEBUG_EDGE_INTERSECT:
                print("View::leftMouseButtonPress - Start dragging a node")
            if self.mode == MODE_NOOP:
                self.mode = MODE_NODE_DRAG

        if item is None:
            if isCTRLPressed(event):
                self.mode = MODE_EDGE_CUT
                if QT_API in ("pyqt5", "pyside2"):
                    fakeEvent = QMouseEvent(
                        QEvent.MouseButtonRelease,
                        event.localPos(),
                        event.screenPos(),
                        Qt.LeftButton,
                        Qt.NoButton,
                        event.modifiers(),
                    )
                elif QT_API in ("pyqt6", "pyside6"):
                    fakeEvent = QMouseEvent(
                        QEvent.MouseButtonRelease,
                        event.localPos(),
                        Qt.MouseButton.LeftButton,
                        Qt.MouseButton.NoButton,
                        event.modifiers(),
                    )
                super().mouseReleaseEvent(fakeEvent)
                QApplication.setOverrideCursor(Qt.CrossCursor)
                return
            else:
                self.rubberBandDraggingRectangle = True

        super().mousePressEvent(event)

    def leftMouseButtonRelease(self, event: QMouseEvent):
        """When Left  mouse button was released"""

        # get the item on which we release the mouse button on
        item = self.getItemAtClick(event)

        try:
            # logic - Shift + LMB release (add selection)
            if (
                hasattr(item, "node")
                or isinstance(item, QDMGraphicsEdge)
                or item is None
            ):
                if isSHIFTPressed(event):
                    event.ignore()
                    if QT_API in ("pyqt5", "pyside2"):
                        fakeEvent = QMouseEvent(
                            event.type(),
                            event.localPos(),
                            event.screenPos(),
                            Qt.LeftButton,
                            Qt.NoButton,
                            event.modifiers() | Qt.ControlModifier,
                        )
                    elif QT_API in ("pyqt6", "pyside6"):
                        fakeEvent = QMouseEvent(
                            event.type(),
                            event.localPos(),
                            Qt.MouseButton.LeftButton,
                            Qt.MouseButton.NoButton,
                            event.modifiers() | Qt.KeyboardModifier.ControlModifier,
                        )
                    super().mouseReleaseEvent(fakeEvent)
                    return

                self.mode = MODE_NOOP

            if self.mode == MODE_NODE_DRAG:
                scenepos = self.mapToScene(event.pos())
                self.mode = MODE_NOOP
                self.update()

            if self.rubberBandDraggingRectangle:
                self.rubberBandDraggingRectangle = False
                current_selected_items = self.grScene.selectedItems()

                if current_selected_items != self.grScene.scene._last_selected_items:
                    if current_selected_items == []:
                        self.grScene.itemsDeselected.emit()
                    else:
                        self.grScene.itemSelected.emit()
                    self.grScene.scene._last_selected_items = current_selected_items

                # the rubber band rectangle doesn't disappear without handling the event
                super().mouseReleaseEvent(event)
                return

            # otherwise deselect everything
            if item is None:
                self.grScene.itemsDeselected.emit()

        except:
            dumpException()

        super().mouseReleaseEvent(event)

    def rightMouseButtonPress(self, event: QMouseEvent):
        """When Right mouse button was pressed"""
        super().mousePressEvent(event)

    def rightMouseButtonRelease(self, event: QMouseEvent):
        """When Right mouse button was release"""
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Overriden Qt's ``mouseMoveEvent`` handling Scene/View logic"""
        scenepos = self.mapToScene(event.pos())

        try:
            self.update()

        except Exception as e:
            dumpException()

        self.last_scene_mouse_position = scenepos
        self.scenePosChanged.emit(int(scenepos.x()), int(scenepos.y()))

        super().mouseMoveEvent(event)

    def getItemAtClick(self, event: QEvent) -> "QGraphicsItem":
        """Return the object on which we've clicked/release mouse button

        :param event: Qt's mouse or key event
        :type event: ``QEvent``
        :return: ``QGraphicsItem`` which the mouse event happened or ``None``
        """
        pos = event.pos()
        obj = self.itemAt(pos)
        return obj

    def wheelEvent(self, event: QWheelEvent):
        """overridden Qt's ``wheelEvent``. This handles zooming"""
        # calculate our zoom Factor
        zoomOutFactor = 1 / self.zoomInFactor

        # calculate zoom
        if event.angleDelta().y() > 0:
            zoomFactor = self.zoomInFactor
            self.zoom += self.zoomStep
        else:
            zoomFactor = zoomOutFactor
            self.zoom -= self.zoomStep

        clamped = False
        if self.zoom < self.zoomRange[0]:
            self.zoom, clamped = self.zoomRange[0], True
        if self.zoom > self.zoomRange[1]:
            self.zoom, clamped = self.zoomRange[1], True

        # set scene scale
        if not clamped or self.zoomClamp is False:
            self.scale(zoomFactor, zoomFactor)
