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
from logging import getLogger

logger = getLogger(__file__)


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

    def __init__(self, gr_scene: "QDMGraphicsScene", parent: "QWidget" = None):
        """
        :param gr_scene: reference to the :class:`~nodeeditor.node_graphics_scene.QDMGraphicsScene`
        :type gr_scene: :class:`~nodeeditor.node_graphics_scene.QDMGraphicsScene`
        :param parent: parent widget
        :type parent: ``QWidget``

        :Instance Attributes:

        - **gr_scene** - reference to the :class:`~nodeeditor.node_graphics_scene.QDMGraphicsScene`
        - **mode** - state of the `Graphics View`
        - **zoomInFactor**- ``float`` - zoom step scaling, default 1.25
        - **zoomClamp** - ``bool`` - do we clamp zooming or is it infinite?
        - **zoom** - current zoom step
        - **zoomStep** - ``int`` - the relative zoom step when zooming in/out
        - **zoomRange** - ``[min, max]``

        """
        super().__init__(parent)
        self.gr_scene = gr_scene

        self.initUI()

        self.setScene(self.gr_scene)

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
        self._previous_selection = set()

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
        # fake_release_event = QMouseEvent(
        #     QEvent.Type.MouseButtonRelease,
        #     event.position(),
        #     Qt.MouseButton.LeftButton,
        #     Qt.MouseButton.NoButton,
        #     event.modifiers(),
        # )
        # super().mouseReleaseEvent(fake_release_event)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        fake_event = QMouseEvent(
            event.type(),
            event.position(),
            Qt.MouseButton.LeftButton,
            event.buttons() | Qt.MouseButton.LeftButton,
            event.modifiers(),
        )
        super().mousePressEvent(fake_event)

    def middleMouseButtonRelease(self, event: QMouseEvent):
        """When Middle mouse button was released"""
        fakeEvent = QMouseEvent(
            event.type(),
            event.position(),
            Qt.MouseButton.LeftButton,
            event.buttons() & ~Qt.MouseButton.LeftButton,
            event.modifiers(),
        )
        super().mouseReleaseEvent(fakeEvent)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def leftMouseButtonPress(self, event: QMouseEvent):
        """When Left  mouse button was pressed"""

        # get the item we clicked on
        item = self.getItemAtClick(event)

        # we store the position of last LMB click
        self.last_lmb_click_scene_pos = self.mapToScene(event.pos())

        if hasattr(item, "node"):
            if self.mode == MODE_NOOP:
                self.mode = MODE_NODE_DRAG

        if item is None:
            if isCTRLPressed(event):
                # super().mouseReleaseEvent(event)
                QApplication.setOverrideCursor(Qt.CrossCursor)
                return
            else:
                self.rubberBandDraggingRectangle = True

        super().mousePressEvent(event)

    def deselected_items(self):
        current = set(self.gr_scene.selectedItems())
        previous = self._previous_selection
        return previous.difference(current)

    def selected_items(self):
        current = set(self.gr_scene.selectedItems())
        previous = self._previous_selection
        return current.difference(previous)

    def update_selection_state(self):
        current = set(self.gr_scene.selectedItems())

        if self.deselected_items():
            self.gr_scene.itemsDeselected.emit()
        if self.selected_items():
            self.gr_scene.itemSelected.emit()

        self._previous_selection = current

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
                    super().mouseReleaseEvent(event)
                    return

                self.mode = MODE_NOOP

            if self.mode == MODE_NODE_DRAG:
                scenepos = self.mapToScene(event.pos())
                self.mode = MODE_NOOP
                self.update()

            if self.rubberBandDraggingRectangle:
                self.rubberBandDraggingRectangle = False
                # the rubber band rectangle doesn't disappear without handling the event
                super().mouseReleaseEvent(event)
                return

        except:
            logger.exception("failed handling LMB release")

        super().mouseReleaseEvent(event)
        self.update_selection_state()

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
        obj = self.itemAt(self.mapFromParent(pos))
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
