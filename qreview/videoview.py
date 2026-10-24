"""The video with the comment bubbles drawn on top. Bubbles can be dragged to place them."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF, QSizeF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem, QFrame
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem

from . import overlay


class OverlayItem(QGraphicsItem):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.rect = QRectF(0, 0, 16, 9)
        self.boxes: dict[str, QRectF] = {}   # in scene coordinates
        self.setZValue(10)

    def set_rect(self, r: QRectF):
        self.prepareGeometryChange()
        self.rect = QRectF(r)
        self.update()

    def boundingRect(self):
        return self.rect

    def paint(self, painter: QPainter, option, widget=None):
        proj = self.ctl.project
        self.boxes = {}
        if not proj.video_path:
            return
        r = self.rect
        if proj.is_trimmed():
            t = self.ctl.current_time()
            if t < proj.trim_in - 0.01 or (proj.video_duration > 0 and t > proj.effective_out() + 0.01):
                painter.fillRect(r, QColor(0, 0, 0, 110))
                f = QFont()
                f.setPixelSize(max(10, int(r.height() * 0.035)))
                painter.setFont(f)
                painter.setPen(QColor(255, 214, 10))
                painter.drawText(r.adjusted(0, 10, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                                 "Outside the trim – not exported")
        if not proj.overlay_enabled:
            return
        comments = proj.comments_at(self.ctl.current_time())
        if not comments:
            return
        painter.save()
        painter.translate(r.topLeft())
        painter.setClipRect(QRectF(0, 0, r.width(), r.height()))
        boxes = overlay.draw(painter, proj, comments, r.width(), r.height(), self.ctl.selected_id)
        painter.restore()
        self.boxes = {cid: b.translated(r.topLeft()) for cid, b in boxes.items()}


class VideoView(QGraphicsView):
    clicked = pyqtSignal()

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.video_item = QGraphicsVideoItem()
        self.scene_.addItem(self.video_item)
        self.overlay_item = OverlayItem(ctl)
        self.scene_.addItem(self.overlay_item)
        self.setBackgroundBrush(QColor("black"))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumSize(320, 180)
        self.video_item.nativeSizeChanged.connect(lambda _s: self.relayout())
        self._drag = None

    def video_rect(self) -> QRectF:
        vw, vh = self.viewport().width(), self.viewport().height()
        ns = self.video_item.nativeSize()
        if ns.isValid() and ns.width() > 0 and ns.height() > 0:
            aw, ah = ns.width(), ns.height()
        else:
            aw, ah = self.ctl.project.video_size
        if aw <= 0 or ah <= 0:
            aw, ah = 16, 9
        scale = min(vw / aw, vh / ah)
        w, h = aw * scale, ah * scale
        return QRectF((vw - w) / 2, (vh - h) / 2, w, h)

    def relayout(self):
        vw, vh = self.viewport().width(), self.viewport().height()
        self.scene_.setSceneRect(0, 0, vw, vh)
        r = self.video_rect()
        self.video_item.setPos(r.topLeft())
        self.video_item.setSize(QSizeF(r.width(), r.height()))
        self.overlay_item.set_rect(r)
        self.centerOn(vw / 2, vh / 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def refresh(self):
        self.overlay_item.update()

    # ── Mouse: drag bubbles ──

    def _hit(self, scene_pos: QPointF):
        for cid, box in reversed(list(self.overlay_item.boxes.items())):
            if box.contains(scene_pos):
                return cid, box
        return None, None

    def mousePressEvent(self, e):
        sp = self.mapToScene(e.position().toPoint())
        cid, box = self._hit(sp)
        if e.button() == Qt.MouseButton.RightButton:
            if cid:
                self.ctl.select(cid)
                self.ctl.comment_menu(cid, e.globalPosition().toPoint())
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if cid:
            self.ctl.select(cid)
            self._drag = {"id": cid, "p0": sp, "box": QRectF(box), "snap": self.ctl.begin_change(), "moved": False}
        else:
            self._drag = {"id": None}

    def mouseMoveEvent(self, e):
        sp = self.mapToScene(e.position().toPoint())
        d = self._drag
        if not d:
            cid, _ = self._hit(sp)
            self.setCursor(Qt.CursorShape.OpenHandCursor if cid else Qt.CursorShape.ArrowCursor)
            self.setToolTip("Drag to place · double-click to edit · right-click for more" if cid else "")
            return
        if not d["id"]:
            return
        delta = sp - d["p0"]
        if not d["moved"] and abs(delta.x()) + abs(delta.y()) < 3:
            return
        d["moved"] = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        c = self.ctl.project.comment(d["id"])
        if c is None:
            return
        r = self.overlay_item.rect
        box = d["box"]
        left = min(max(r.left(), box.left() + delta.x()), r.right() - box.width())
        top = min(max(r.top(), box.top() + delta.y()), r.bottom() - box.height())
        c.x = round((left - r.left()) / r.width(), 4)
        c.y = round((top - r.top()) / r.height(), 4)
        self.ctl.live_changed()

    def mouseReleaseEvent(self, e):
        d, self._drag = self._drag, None
        if not d:
            return
        if d["id"] and d["moved"]:
            self.ctl.commit_change(d["snap"], "Place comment")
        elif not d["id"]:
            self.clicked.emit()
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, e):
        sp = self.mapToScene(e.position().toPoint())
        cid, _ = self._hit(sp)
        if cid:
            self._drag = None
            self.ctl.edit_comment_text(cid)
        else:
            self.clicked.emit()   # second click of a double click toggles back

    def wheelEvent(self, e):
        e.ignore()
