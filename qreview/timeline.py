"""The timeline: ruler, waveform, one track per profile with the comments as blocks.

Drag a block to move it (also up/down to another profile), drag its edges to change
start or length, drag the yellow in/out handles in the ruler to trim. Blocks snap to the
playhead, the trim and other comments (hold Alt to turn snapping off).
"""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetricsF, QPixmap, QPolygonF, QCursor
from PyQt6.QtWidgets import QWidget, QScrollBar, QVBoxLayout, QHBoxLayout, QToolButton, QLabel, QSizePolicy

from .model import fmt_clock, fmt_short

HEADER_W = 128
RULER_H = 26
WAVE_H = 34
LANE_H = 24
TRACK_PAD = 3
EDGE = 6
MIN_DUR = 0.2
END_PAD = 14        # pixels shown after the end of the video

BG = QColor("#1b1b1d")
HEADER_BG = QColor("#232326")
TRACK_A = QColor("#202023")
TRACK_B = QColor("#252528")
GRID = QColor(255, 255, 255, 18)
TEXT_DIM = QColor("#9a9aa0")
TRIM = QColor("#FFD60A")
PLAYHEAD = QColor("#FF453A")

STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]


class Timeline(QWidget):
    viewChanged = pyqtSignal()

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.pps = 20.0          # pixels per second
        self.offset = 0.0        # seconds at the left edge
        self.wave: QPixmap | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(RULER_H + WAVE_H + LANE_H + 10)
        self._drag = None
        self._rects = []          # [(comment_id, QRectF)]
        self._tracks = []         # [(profile, y, h)]
        self._font = QFont()
        self._font.setPixelSize(11)
        self._bold = QFont(self._font)
        self._bold.setBold(True)
        from PyQt6.QtCore import QTimer
        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(40)
        self._edge_timer.timeout.connect(self._edge_scroll)
        self._last_move = None

    # ── Geometry ──

    @property
    def project(self):
        return self.ctl.project

    def total(self) -> float:
        p = self.project
        ends = [c.end for c in p.comments]
        if p.video_duration > 0:
            return max([p.video_duration] + ends)
        return max([1.0] + ends)

    def visible_seconds(self) -> float:
        return max(0.1, (self.width() - HEADER_W) / self.pps)

    def x_of(self, t: float) -> float:
        return HEADER_W + (t - self.offset) * self.pps

    def t_of(self, x: float) -> float:
        return self.offset + (x - HEADER_W) / self.pps

    def clamp_offset(self):
        max_off = max(0.0, self.total() + END_PAD / self.pps - self.visible_seconds())
        self.offset = min(max(0.0, self.offset), max_off)

    def fit(self):
        avail = max(50, self.width() - HEADER_W - END_PAD)
        self.pps = max(0.02, avail / max(1.0, self.total()))
        self.offset = 0.0
        self.update()
        self.viewChanged.emit()

    def zoom(self, factor: float, anchor_x: float | None = None):
        if anchor_x is None:
            ph = self.x_of(self.ctl.current_time())
            anchor_x = ph if HEADER_W <= ph <= self.width() else HEADER_W + (self.width() - HEADER_W) / 2
        t = self.t_of(anchor_x)
        self.pps = min(400.0, max(0.02, self.pps * factor))
        self.offset = t - (anchor_x - HEADER_W) / self.pps
        self.clamp_offset()
        self.update()
        self.viewChanged.emit()

    def follow(self, t: float):
        """Keeps the playhead in view while playing."""
        x = self.x_of(t)
        if x > self.width() - 30 or x < HEADER_W:
            self.offset = t - 0.1 * self.visible_seconds()
            self.clamp_offset()
            self.viewChanged.emit()

    def set_waveform(self, path: str | None):
        self.wave = QPixmap(path) if path else None
        if self.wave is not None and self.wave.isNull():
            self.wave = None
        self.update()

    def _layout(self):
        """Tracks (one per profile) and the comment blocks, with lanes for overlaps."""
        p = self.project
        y = RULER_H + WAVE_H
        tracks, rects = [], []
        for prof in p.profiles:
            items = sorted([c for c in p.comments if c.profile_id == prof.id], key=lambda c: (c.start, c.id))
            lanes_end: list[float] = []
            placed = []
            for c in items:
                for i, e in enumerate(lanes_end):
                    if c.start >= e - 1e-6:
                        lanes_end[i] = c.end
                        placed.append((c, i))
                        break
                else:
                    lanes_end.append(c.end)
                    placed.append((c, len(lanes_end) - 1))
            n = max(1, len(lanes_end))
            h = n * LANE_H + 2 * TRACK_PAD
            tracks.append((prof, y, h))
            for c, lane in placed:
                x1 = self.x_of(c.start)
                x2 = max(x1 + 4, self.x_of(c.end))
                rects.append((c.id, QRectF(x1, y + TRACK_PAD + lane * LANE_H + 1, x2 - x1, LANE_H - 2)))
            y += h
        self._tracks, self._rects = tracks, rects
        need = int(y + 6)
        if self.minimumHeight() != need:
            self.setMinimumHeight(need)
        return tracks, rects

    def _track_at(self, y: float):
        for prof, ty, th in self._tracks:
            if ty <= y < ty + th:
                return prof
        if self._tracks and y >= self._tracks[-1][1]:
            return self._tracks[-1][0]
        return self._tracks[0][0] if self._tracks else None

    # ── Painting ──

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        W, H = self.width(), self.height()
        proj = self.project
        self.clamp_offset()
        tracks, rects = self._layout()
        p.fillRect(self.rect(), BG)

        # Tracks
        for i, (prof, y, h) in enumerate(tracks):
            p.fillRect(QRectF(HEADER_W, y, W - HEADER_W, h), TRACK_A if i % 2 == 0 else TRACK_B)

        # Grid + ruler
        p.fillRect(QRectF(0, 0, W, RULER_H), QColor("#2a2a2d"))
        major = next((s for s in STEPS if s * self.pps >= 90), STEPS[-1])
        minor = major / 5 if major >= 1 else major / 2
        t0 = math.floor(self.offset / minor) * minor
        t = t0
        p.setFont(self._font)
        end_t = self.t_of(W)
        while t <= end_t:
            x = self.x_of(t)
            is_major = abs(t / major - round(t / major)) < 1e-6
            if x >= HEADER_W:
                if is_major:
                    p.setPen(QPen(GRID, 1))
                    p.drawLine(QPointF(x, RULER_H), QPointF(x, H))
                    p.setPen(QPen(TEXT_DIM, 1))
                    p.drawLine(QPointF(x, RULER_H - 9), QPointF(x, RULER_H))
                    label = fmt_clock(t) if major >= 1 else fmt_short(t)
                    p.drawText(QPointF(x + 3, RULER_H - 11), label)
                else:
                    p.setPen(QPen(QColor(255, 255, 255, 50), 1))
                    p.drawLine(QPointF(x, RULER_H - 4), QPointF(x, RULER_H))
            t += minor

        # Waveform
        wave_rect = QRectF(HEADER_W, RULER_H, W - HEADER_W, WAVE_H)
        p.fillRect(wave_rect, QColor("#18181a"))
        dur = proj.video_duration
        if self.wave is not None and dur > 0:
            a, b = max(0.0, self.offset), min(dur, end_t)
            if b > a:
                sx = a / dur * self.wave.width()
                sw = (b - a) / dur * self.wave.width()
                target = QRectF(self.x_of(a), RULER_H + 2, self.x_of(b) - self.x_of(a), WAVE_H - 4)
                p.drawPixmap(target, self.wave, QRectF(sx, 0, sw, self.wave.height()))

        # Outside the video / outside the trim
        if dur > 0:
            xe = self.x_of(dur)
            if xe < W:
                # After the end of the video: clearly empty
                x0 = max(HEADER_W, xe)
                p.fillRect(QRectF(x0, 0, W - x0, H), QColor("#0b0b0c"))
                p.setPen(QPen(QColor(255, 255, 255, 60), 1))
                p.drawLine(QPointF(xe, 0), QPointF(xe, H))
                if W - x0 > 34:
                    p.setPen(TEXT_DIM)
                    p.setFont(self._font)
                    p.drawText(QRectF(x0 + 6, 0, W - x0 - 6, RULER_H), Qt.AlignmentFlag.AlignVCenter, "End")
        tin, tout = proj.trim_in, proj.effective_out()
        shade = QColor(0, 0, 0, 150)
        if tin > 0:
            x = self.x_of(tin)
            if x > HEADER_W:
                p.fillRect(QRectF(HEADER_W, RULER_H, x - HEADER_W, H - RULER_H), shade)
        if dur > 0 and tout < dur:
            x = self.x_of(tout)
            p.fillRect(QRectF(max(HEADER_W, x), RULER_H, W - max(HEADER_W, x), H - RULER_H), shade)

        # Comments
        sel = self.ctl.selected_id
        p.setFont(self._font)
        fm = QFontMetricsF(self._font)
        for cid, r in rects:
            if r.right() < HEADER_W or r.left() > W:
                continue
            c = proj.comment(cid)
            col = QColor(proj.color(c))
            on = proj.visible_on_video(c)
            fill = QColor(col)
            fill.setAlpha(215 if on else 80)
            p.setPen(QPen(col.lighter(130), 1) if not on else Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r, 4, 4)
            if not on:
                p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(r.left() + 3, r.center().y()), QPointF(r.right() - 3, r.center().y()))
            if c.has_position:
                p.setBrush(QColor(255, 255, 255, 220))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(r.right() - 6, r.top() + 6), 2.5, 2.5)
            if r.width() > 18:
                p.setPen(QColor(255, 255, 255) if on else QColor(230, 230, 235))
                text = c.text.replace("\n", " ")
                left = max(r.left(), HEADER_W) + 5
                avail = r.right() - left - 10
                if avail > 10:
                    p.drawText(QRectF(left, r.top(), avail, r.height()),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                               fm.elidedText(text, Qt.TextElideMode.ElideRight, avail))
            if cid == sel:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor("white"), 2))
                p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 4, 4)

        # Trim handles
        for t, is_in in ((tin, True), (tout, False)):
            if dur <= 0 and not is_in:
                continue
            if not is_in and dur > 0 and tout >= dur and proj.trim_out is None:
                pass   # still draw the out handle at the end
            x = self.x_of(t)
            if HEADER_W - 2 <= x <= W + 2:
                p.setPen(QPen(TRIM, 2, Qt.PenStyle.DashLine if proj.trim_locked else Qt.PenStyle.SolidLine))
                p.drawLine(QPointF(x, 2), QPointF(x, H))
                p.setBrush(TRIM)
                p.setPen(Qt.PenStyle.NoPen)
                if is_in:
                    p.drawPolygon(QPolygonF([QPointF(x, 2), QPointF(x + 9, 2), QPointF(x, 14)]))
                else:
                    p.drawPolygon(QPolygonF([QPointF(x, 2), QPointF(x - 9, 2), QPointF(x, 14)]))

        # Playhead
        x = self.x_of(self.ctl.current_time())
        if HEADER_W <= x <= W:
            p.setPen(QPen(PLAYHEAD, 1.5))
            p.drawLine(QPointF(x, RULER_H - 2), QPointF(x, H))
            p.setBrush(PLAYHEAD)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygonF([QPointF(x - 6, RULER_H - 10), QPointF(x + 6, RULER_H - 10), QPointF(x, RULER_H - 1)]))

        # Header column (drawn last, on top)
        p.fillRect(QRectF(0, 0, HEADER_W, H), HEADER_BG)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.drawLine(QPointF(HEADER_W, 0), QPointF(HEADER_W, H))
        p.setPen(TEXT_DIM)
        p.setFont(self._font)
        p.drawText(QRectF(8, 0, HEADER_W - 12, RULER_H), Qt.AlignmentFlag.AlignVCenter, fmt_short(self.ctl.current_time()))
        p.drawText(QRectF(8, RULER_H, HEADER_W - 12, WAVE_H), Qt.AlignmentFlag.AlignVCenter,
                   "Audio" if self.wave is not None else "")
        for prof, y, h in tracks:
            p.setPen(QPen(QColor(0, 0, 0, 90), 1))
            p.drawLine(QPointF(0, y), QPointF(W, y))
            p.setBrush(QColor(prof.color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(8, y + h / 2 - 5, 10, 10), 3, 3)
            p.setPen(QColor("#e5e5ea") if prof.show_on_video else TEXT_DIM)
            p.setFont(self._bold if prof.id == self.ctl.active_profile_id else self._font)
            name = QFontMetricsF(p.font()).elidedText(prof.name, Qt.TextElideMode.ElideRight, HEADER_W - 34)
            p.drawText(QRectF(24, y, HEADER_W - 28, min(h, LANE_H + 2 * TRACK_PAD)), Qt.AlignmentFlag.AlignVCenter, name)
        p.end()

    # ── Mouse ──

    def _hit(self, pos: QPointF):
        for cid, r in reversed(self._rects):
            if r.adjusted(-2, 0, 2, 0).contains(pos) and pos.x() >= HEADER_W:
                if pos.x() <= r.left() + EDGE and r.width() > 3 * EDGE:
                    return cid, "left"
                if pos.x() >= r.right() - EDGE:
                    return cid, "right"
                return cid, "move"
        return None, None

    def _trim_hit(self, pos: QPointF):
        if pos.y() > RULER_H + WAVE_H:
            return None
        proj = self.project
        if proj.trim_locked:
            return None
        if abs(pos.x() - self.x_of(proj.trim_in)) <= 7:
            return "in"
        if proj.video_duration > 0 and abs(pos.x() - self.x_of(proj.effective_out())) <= 7:
            return "out"
        return None

    def _snap(self, t: float, exclude: str | None, mods) -> float:
        if mods & Qt.KeyboardModifier.AltModifier:
            return t
        proj = self.project
        points = [0.0, self.ctl.current_time(), proj.trim_in]
        if proj.video_duration > 0:
            points += [proj.effective_out(), proj.video_duration]
        for c in proj.comments:
            if c.id != exclude:
                points += [c.start, c.end]
        tol = 8 / self.pps
        best = min(points, key=lambda v: abs(v - t))
        return best if abs(best - t) <= tol else t

    def mousePressEvent(self, e):
        pos = e.position()
        if pos.x() < HEADER_W:
            prof = self._track_at(pos.y()) if pos.y() > RULER_H + WAVE_H else None
            if prof:
                self.ctl.set_active_profile(prof.id)
            return
        if e.button() == Qt.MouseButton.RightButton:
            cid, _ = self._hit(pos)
            if cid:
                self.ctl.select(cid)
                self.ctl.comment_menu(cid, e.globalPosition().toPoint())
            elif pos.y() > RULER_H + WAVE_H:
                prof = self._track_at(pos.y())
                self.ctl.empty_track_menu(prof.id if prof else None, max(0.0, self.t_of(pos.x())),
                                          e.globalPosition().toPoint())
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        trim = self._trim_hit(pos)
        if trim:
            self._drag = {"kind": "trim", "which": trim, "snap": self.ctl.begin_change(), "moved": False}
            return
        cid, mode = self._hit(pos)
        if cid:
            c = self.project.comment(cid)
            self.ctl.select(cid)
            self._drag = {"kind": "comment", "id": cid, "mode": mode, "x0": pos.x(), "y0": pos.y(), "t0": self.t_of(pos.x()),
                          "start": c.start, "dur": c.duration, "profile": c.profile_id,
                          "snap": self.ctl.begin_change(), "moved": False}
            return
        # Ruler or empty track: scrub
        if pos.y() > RULER_H + WAVE_H:
            self.ctl.select(None)
        self._drag = {"kind": "scrub"}
        self.ctl.seek(max(0.0, self.t_of(pos.x())), fast=True)

    def _edge_scroll(self):
        """Scrolls the timeline while something is dragged to its edge, so the end can be reached."""
        if self._drag is None or self._last_move is None:
            self._edge_timer.stop()
            return
        pos, mods = self._last_move
        step = 0.0
        if pos.x() > self.width() - 24:
            step = (pos.x() - (self.width() - 24) + 4) / self.pps * 0.5
        elif pos.x() < HEADER_W + 16 and self.offset > 0:
            step = -((HEADER_W + 16 - pos.x()) + 4) / self.pps * 0.5
        if not step:
            self._edge_timer.stop()
            return
        before = self.offset
        self.offset += step
        self.clamp_offset()
        if self.offset != before:
            self.viewChanged.emit()
            self._apply_move(pos, mods)
        else:
            self._edge_timer.stop()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is not None and self._drag["kind"] != "scrub":
            self._last_move = (QPointF(pos), e.modifiers())
            if (pos.x() > self.width() - 24 or pos.x() < HEADER_W + 16) and not self._edge_timer.isActive():
                self._edge_timer.start()
        self._apply_move(pos, e.modifiers(), e)

    def _apply_move(self, pos, mods, e=None):
        d = self._drag
        if d is None:
            if pos.x() < HEADER_W:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            elif self._trim_hit(pos):
                self.setCursor(Qt.CursorShape.SplitHCursor)
            else:
                cid, mode = self._hit(pos)
                if mode in ("left", "right"):
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                elif mode == "move":
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
                if cid:
                    c = self.project.comment(cid)
                    self.setToolTip(f"{fmt_short(c.start)} – {fmt_short(c.end)}\n{self.project.prefix(c)}: {c.text}")
                else:
                    self.setToolTip("")
            return
        proj = self.project
        if d["kind"] == "scrub":
            self.ctl.seek(max(0.0, self.t_of(pos.x())), fast=True)
            return
        if d["kind"] == "trim":
            t = self._snap(max(0.0, self.t_of(pos.x())), None, mods)
            dur = proj.video_duration
            if d["which"] == "in":
                limit = proj.effective_out() - 0.1 if dur > 0 else t
                proj.trim_in = max(0.0, min(t, limit))
                self.ctl.seek(proj.trim_in, fast=True)
            else:
                t = min(t, dur) if dur > 0 else t
                t = max(t, proj.trim_in + 0.1)
                proj.trim_out = proj.out_or_end(t)
                self.ctl.seek(t, fast=True)
            d["moved"] = True
            self.ctl.live_changed()
            return
        if d["kind"] == "comment":
            c = proj.comment(d["id"])
            if c is None:
                return
            if not d["moved"] and abs(pos.x() - d["x0"]) < 3 and abs(pos.y() - d["y0"]) < 4:
                return
            d["moved"] = True
            dt = self.t_of(pos.x()) - d["t0"]   # in time, so scrolling while dragging works
            limit = proj.video_duration if proj.video_duration > 0 else None
            if d["mode"] == "move":
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                start = d["start"] + dt
                s1 = self._snap(start, c.id, mods)
                s2 = self._snap(start + d["dur"], c.id, mods) - d["dur"]
                start = s1 if abs(s1 - start) <= abs(s2 - start) else s2
                start = max(0.0, start)
                if limit:
                    start = min(start, max(0.0, limit - d["dur"]))
                c.start = start
                prof = self._track_at(pos.y()) if pos.y() > RULER_H + WAVE_H else None
                if prof and prof.id != c.profile_id:
                    c.profile_id = prof.id
            elif d["mode"] == "right":
                end = self._snap(d["start"] + d["dur"] + dt, c.id, mods)
                if limit:
                    end = min(end, limit)
                c.duration = max(MIN_DUR, end - c.start)
            else:
                end = d["start"] + d["dur"]
                start = self._snap(d["start"] + dt, c.id, mods)
                start = max(0.0, min(start, end - MIN_DUR))
                c.start, c.duration = start, end - start
            self.ctl.live_changed()

    def mouseReleaseEvent(self, e):
        self._edge_timer.stop()
        self._last_move = None
        d, self._drag = self._drag, None
        if d is None:
            return
        if d["kind"] == "trim" and d["moved"]:
            self.ctl.commit_change(d["snap"], "Trim")
        elif d["kind"] == "comment" and d["moved"]:
            self.ctl.commit_change(d["snap"], "Move comment")
        elif d["kind"] == "scrub":
            self.ctl.seek(max(0.0, self.t_of(e.position().x())))
        self.mouseMoveEvent(e)

    def mouseDoubleClickEvent(self, e):
        cid, _ = self._hit(e.position())
        if cid:
            self.ctl.edit_comment_text(cid)
        elif e.position().y() > RULER_H + WAVE_H and e.position().x() > HEADER_W:
            prof = self._track_at(e.position().y())
            self.ctl.add_comment_dialog(prof.id if prof else None, max(0.0, self.t_of(e.position().x())))

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        dx = e.angleDelta().x()
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.2 if dy > 0 else 1 / 1.2, e.position().x())
        elif e.modifiers() & Qt.KeyboardModifier.ShiftModifier and dx == 0:
            e.ignore()   # vertical scrolling of the tracks (scroll area)
            return
        else:
            delta = dx if abs(dx) > abs(dy) else dy
            self.offset -= delta / 120 * 60 / self.pps
            self.clamp_offset()
            self.update()
            self.viewChanged.emit()
        e.accept()

    def resizeEvent(self, e):
        self.clamp_offset()
        self.viewChanged.emit()
        super().resizeEvent(e)


class TimelinePanel(QWidget):
    """Timeline with zoom buttons and a horizontal scroll bar."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QScrollArea
        self.timeline = Timeline(ctl)
        self.area = QScrollArea()
        self.area.setWidget(self.timeline)
        self.area.setWidgetResizable(True)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.bar = QScrollBar(Qt.Orientation.Horizontal)
        self.bar.valueChanged.connect(self._bar_moved)
        self.timeline.viewChanged.connect(self._sync_bar)

        tools = QHBoxLayout()
        tools.setContentsMargins(8, 2, 8, 2)
        title = QLabel("Timeline")
        title.setStyleSheet("color:#9a9aa0; font-weight:600;")
        tools.addWidget(title)
        hint = QLabel("Drag comments to move · edges to change length · yellow handles to trim · Alt = no snapping")
        hint.setStyleSheet("color:#6e6e73; font-size:11px;")
        tools.addWidget(hint)
        tools.addStretch()
        for text, tip, fn in (("−", "Zoom out (Ctrl+wheel)", lambda: self.timeline.zoom(1 / 1.5)),
                              ("+", "Zoom in (Ctrl+wheel)", lambda: self.timeline.zoom(1.5)),
                              ("Fit", "Show the whole video", self.timeline.fit)):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            tools.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(tools)
        lay.addWidget(self.area, 1)
        lay.addWidget(self.bar)
        self._syncing = False

    def _sync_bar(self):
        t = self.timeline
        self._syncing = True
        vis = t.visible_seconds()
        maximum = max(0.0, t.total() + END_PAD / t.pps - vis)
        self.bar.setRange(0, int(maximum * 100))
        self.bar.setPageStep(max(1, int(vis * 100)))
        self.bar.setSingleStep(max(1, int(vis * 10)))
        self.bar.setValue(int(t.offset * 100))
        self._syncing = False
        t.update()

    def _bar_moved(self, v):
        if self._syncing:
            return
        self.timeline.offset = v / 100
        self.timeline.update()
