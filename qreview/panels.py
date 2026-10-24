"""The left side: profiles, writing comments, the comment list and the selected comment."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QRect, QRectF, QSize, QPoint, QEvent, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QKeyEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyle, QStyleOptionButton, QApplication, QLayout, QCheckBox, QToolButton,
    QGroupBox, QFormLayout, QComboBox, QLineEdit, QDoubleSpinBox, QDialog, QDialogButtonBox, QColorDialog,
    QMessageBox, QFileDialog, QSizePolicy, QAbstractItemView, QListView,
)

from .model import Profile, fmt_short, fmt_precise, parse_time, read_qrecorder_roles

ID_ROLE = Qt.ItemDataRole.UserRole + 1


# ── Flow layout (chips that wrap) ─────────────────────────────────────────────

class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + self._spacing
            if nx - self._spacing > rect.right() and line_h > 0:
                x, y = rect.x(), y + line_h + self._spacing
                nx = x + hint.width() + self._spacing
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


def chip_style(color: str, active: bool) -> str:
    c = QColor(color)
    if active:
        return (f"QPushButton{{background:{c.name()}; color:{'#000' if c.lightness() > 160 else '#fff'};"
                f"border:1px solid {c.lighter(130).name()}; border-radius:11px; padding:3px 10px; font-weight:600;}}")
    return (f"QPushButton{{background:transparent; color:#e5e5ea; border:1px solid {c.name()};"
            f"border-radius:11px; padding:3px 10px;}} QPushButton:hover{{background:{c.name()}33;}}")


# ── Writing a comment ─────────────────────────────────────────────────────────

class CommentInput(QPlainTextEdit):
    submitted = pyqtSignal(str)
    started = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setPlaceholderText("Write a comment …  (Enter adds it, Shift+Enter = new line, Esc = cancel)")
        self.setTabChangesFocus(True)
        self.setFixedHeight(64)
        self.textChanged.connect(self._changed)
        self._was_empty = True

    def _changed(self):
        empty = not self.toPlainText().strip()
        if self._was_empty and not empty:
            self.started.emit()
        self._was_empty = empty

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            text = self.toPlainText().strip()
            if text:
                self.submitted.emit(text)
            return
        if e.key() == Qt.Key.Key_Escape:
            self.clear()
            self.cancelled.emit()
            self.clearFocus()
            return
        super().keyPressEvent(e)


# ── The list ──────────────────────────────────────────────────────────────────

class CommentDelegate(QStyledItemDelegate):
    toggled = pyqtSignal(str)

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.small = QFont()
        self.small.setPointSizeF(max(7.5, QFont().pointSizeF() * 0.88))
        self.bold = QFont(self.small)
        self.bold.setBold(True)

    def _layout(self, rect: QRect):
        check = QRect(rect.right() - 26, rect.top() + 6, 18, 18)
        text = QRect(rect.left() + 14, rect.top() + 26, rect.width() - 14 - 34, 10000)
        return check, text

    def sizeHint(self, option, index):
        c = self.ctl.project.comment(index.data(ID_ROLE))
        if c is None:
            return QSize(100, 30)
        view = self.parent()
        w = view.viewport().width() if view is not None and view.viewport().width() > 50 else 300
        _, tr = self._layout(QRect(0, 0, w, 100))
        fm = QFontMetrics(option.font)
        br = fm.boundingRect(QRect(0, 0, tr.width(), 10000), Qt.TextFlag.TextWordWrap.value, c.text or " ")
        return QSize(w, 26 + br.height() + 10)

    def paint(self, p: QPainter, option, index):
        c = self.ctl.project.comment(index.data(ID_ROLE))
        if c is None:
            return
        proj = self.ctl.project
        r = option.rect
        p.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        active = c.id in self.ctl.active_ids
        if selected:
            p.fillRect(r, QColor(10, 132, 255, 70))
        elif active:
            p.fillRect(r, QColor(255, 255, 255, 18))
        p.fillRect(QRect(r.left() + 4, r.top() + 5, 4, r.height() - 10), QColor(proj.color(c)))
        p.setPen(QColor(255, 255, 255, 20))
        p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())

        # Line 1: time · profile · author
        p.setFont(self.small)
        p.setPen(QColor("#ffd60a") if active else QColor("#9a9aa0"))
        x = r.left() + 14
        t = fmt_short(c.start)
        p.drawText(QRect(x, r.top() + 4, 200, 20), Qt.AlignmentFlag.AlignVCenter, t)
        x += QFontMetrics(self.small).horizontalAdvance(t) + 10
        p.setFont(self.bold)
        prof = proj.profile(c.profile_id)
        name = prof.name if prof else "?"
        p.setPen(QColor(proj.color(c)).lighter(125))
        p.drawText(QRect(x, r.top() + 4, 400, 20), Qt.AlignmentFlag.AlignVCenter, name)
        x += QFontMetrics(self.bold).horizontalAdvance(name) + 6
        p.setFont(self.small)
        p.setPen(QColor("#8e8e93"))
        extra = []
        if c.author:
            extra.append(c.author)
        extra.append(f"{c.duration:.1f} s")
        if c.has_position:
            extra.append("placed")
        p.drawText(QRect(x, r.top() + 4, max(0, r.right() - x - 34), 20), Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(self.small).elidedText(" · ".join(extra), Qt.TextElideMode.ElideRight, max(0, r.right() - x - 34)))

        # On video (checkbox)
        check, text_rect = self._layout(r)
        opt = QStyleOptionButton()
        opt.rect = check
        opt.state = QStyle.StateFlag.State_Enabled | (QStyle.StateFlag.State_On if c.on_video else QStyle.StateFlag.State_Off)
        QApplication.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, opt, p)

        # Text
        p.setFont(option.font)
        p.setPen(QColor("#f2f2f7") if proj.visible_on_video(c) or not proj.overlay_enabled else QColor("#aeaeb2"))
        p.drawText(QRect(text_rect.left(), text_rect.top(), text_rect.width(), r.bottom() - text_rect.top()),
                   Qt.TextFlag.TextWordWrap.value, c.text)
        p.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease:
            check, _ = self._layout(option.rect)
            if check.adjusted(-4, -4, 4, 4).contains(event.position().toPoint()):
                self.toggled.emit(index.data(ID_ROLE))
                return True
        return False


class CommentList(QListWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.delegate = CommentDelegate(ctl, self)
        self.setItemDelegate(self.delegate)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformItemSizes(False)
        self.setWordWrap(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(lambda it: ctl.jump_to(it.data(ID_ROLE)))
        self.itemDoubleClicked.connect(lambda it: ctl.edit_comment_text(it.data(ID_ROLE)))
        self.delegate.toggled.connect(ctl.toggle_on_video)
        self._ids: list[str] = []

    def rebuild(self):
        ids = [c.id for c in self.ctl.project.sorted_comments()]
        if ids != self._ids:
            scroll = self.verticalScrollBar().value()
            self.blockSignals(True)
            self.clear()
            for cid in ids:
                it = QListWidgetItem()
                it.setData(ID_ROLE, cid)
                self.addItem(it)
            self.blockSignals(False)
            self._ids = ids
            self.verticalScrollBar().setValue(scroll)
        self.sync_selection()
        self.doItemsLayout()
        self.viewport().update()

    def sync_selection(self):
        sel = self.ctl.selected_id
        self.blockSignals(True)
        for i in range(self.count()):
            it = self.item(i)
            on = it.data(ID_ROLE) == sel
            if it.isSelected() != on:
                it.setSelected(on)
            if on:
                self.scrollToItem(it)
        self.blockSignals(False)

    def scroll_to(self, cid: str):
        for i in range(self.count()):
            if self.item(i).data(ID_ROLE) == cid:
                self.scrollToItem(self.item(i), QAbstractItemView.ScrollHint.EnsureVisible)
                return

    def _menu(self, pos):
        it = self.itemAt(pos)
        if it:
            self.ctl.select(it.data(ID_ROLE))
            self.ctl.comment_menu(it.data(ID_ROLE), self.viewport().mapToGlobal(pos))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.doItemsLayout()


# ── Selected comment ──────────────────────────────────────────────────────────

class Inspector(QGroupBox):
    def __init__(self, ctl):
        super().__init__("Selected comment")
        self.ctl = ctl
        self._loading = False
        form = QFormLayout(self)
        form.setContentsMargins(10, 14, 10, 10)
        form.setVerticalSpacing(6)

        self.profile = QComboBox()
        self.profile.currentIndexChanged.connect(self._profile_changed)
        form.addRow("Profile", self.profile)

        row = QHBoxLayout()
        self.start = QLineEdit()
        self.start.setPlaceholderText("00:00:00.000")
        self.start.editingFinished.connect(self._start_changed)
        row.addWidget(self.start, 1)
        here = QToolButton()
        here.setText("⇤ Playhead")
        here.setToolTip("Move the comment to the playhead")
        here.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        here.clicked.connect(lambda: ctl.move_selected_to_playhead())
        row.addWidget(here)
        form.addRow("Start", row)

        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.2, 36000)
        self.duration.setDecimals(1)
        self.duration.setSingleStep(0.5)
        self.duration.setSuffix(" s")
        self.duration.setKeyboardTracking(False)
        self.duration.valueChanged.connect(self._duration_changed)
        form.addRow("Length", self.duration)

        row2 = QHBoxLayout()
        self.on_video = QCheckBox("Show on video")
        self.on_video.toggled.connect(self._on_video_changed)
        row2.addWidget(self.on_video)
        row2.addStretch()
        self.position = QLabel()
        self.position.setStyleSheet("color:#8e8e93;")
        row2.addWidget(self.position)
        self.reset_pos = QToolButton()
        self.reset_pos.setText("Auto")
        self.reset_pos.setToolTip("Back to the automatic position (bottom left)")
        self.reset_pos.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reset_pos.clicked.connect(lambda: ctl.reset_position(ctl.selected_id))
        row2.addWidget(self.reset_pos)
        form.addRow("", row2)

        self.text = QPlainTextEdit()
        self.text.setFixedHeight(70)
        self.text.installEventFilter(self)
        form.addRow("Text", self.text)

        row3 = QHBoxLayout()
        row3.addStretch()
        delete = QPushButton("Delete")
        delete.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        delete.clicked.connect(lambda: ctl.delete_comment(ctl.selected_id))
        row3.addWidget(delete)
        form.addRow("", row3)
        self.load()

    def eventFilter(self, obj, ev):
        if obj is self.text and ev.type() == QEvent.Type.FocusOut:
            self._text_changed()
        if obj is self.text and ev.type() == QEvent.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._text_changed()
                return True
        return False

    def load(self):
        c = self.ctl.project.comment(self.ctl.selected_id)
        self._loading = True
        self.setEnabled(c is not None)
        self.profile.clear()
        for p in self.ctl.project.profiles:
            self.profile.addItem(p.name, p.id)
        if c:
            i = self.profile.findData(c.profile_id)
            self.profile.setCurrentIndex(max(0, i))
            if not self.start.hasFocus():
                self.start.setText(fmt_precise(c.start))
            self.duration.setValue(c.duration)
            self.on_video.setChecked(c.on_video)
            self.position.setText("Placed by hand" if c.has_position else "Automatic position")
            self.reset_pos.setEnabled(c.has_position)
            if not self.text.hasFocus():
                self.text.setPlainText(c.text)
        else:
            self.start.clear()
            self.text.clear()
            self.position.setText("")
        self._loading = False

    def _c(self):
        return None if self._loading else self.ctl.project.comment(self.ctl.selected_id)

    def _profile_changed(self, _i):
        c = self._c()
        pid = self.profile.currentData()
        if c and pid and pid != c.profile_id:
            self.ctl.change(lambda: setattr(c, "profile_id", pid), "Change profile")

    def _start_changed(self):
        c = self._c()
        if not c:
            return
        t = parse_time(self.start.text())
        if t is None:
            self.start.setText(fmt_precise(c.start))
            return
        if abs(t - c.start) > 0.0005:
            self.ctl.change(lambda: setattr(c, "start", t), "Change start")

    def _duration_changed(self, v):
        c = self._c()
        if c and abs(v - c.duration) > 0.001:
            self.ctl.change(lambda: setattr(c, "duration", float(v)), "Change length")

    def _on_video_changed(self, on):
        c = self._c()
        if c and on != c.on_video:
            self.ctl.change(lambda: setattr(c, "on_video", on), "Show on video")

    def _text_changed(self):
        c = self._c()
        if c:
            t = self.text.toPlainText().strip()
            if t and t != c.text:
                self.ctl.change(lambda: setattr(c, "text", t), "Edit text")


# ── Profiles dialog ───────────────────────────────────────────────────────────

class ProfilesDialog(QDialog):
    """Add, rename, recolour and remove profiles (like Q-Recorder's roles)."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Profiles")
        self.resize(460, 420)
        self.project = project
        self.profiles = [Profile(p.name, p.color, p.show_on_video, p.id) for p in project.profiles]
        self.removed: dict[str, str | None] = {}   # removed id → move comments to (None = delete them)

        lay = QVBoxLayout(self)
        info = QLabel("Each profile is a track in the timeline and a colour on the video – like the roles in Q-Recorder.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#9a9aa0;")
        lay.addWidget(info)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._row)
        lay.addWidget(self.list, 1)

        edit = QHBoxLayout()
        self.name = QLineEdit()
        self.name.textEdited.connect(self._rename)
        edit.addWidget(self.name, 1)
        self.color_btn = QPushButton("Colour …")
        self.color_btn.clicked.connect(self._color)
        edit.addWidget(self.color_btn)
        self.show_cb = QCheckBox("On video")
        self.show_cb.toggled.connect(self._show)
        edit.addWidget(self.show_cb)
        lay.addLayout(edit)

        btns = QHBoxLayout()
        for text, fn in (("Add", self._add), ("Remove", self._remove), ("▲", lambda: self._move(-1)),
                         ("▼", lambda: self._move(1)), ("Import from Q-Recorder …", self._import)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        lay.addLayout(btns)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill(0)

    def _fill(self, row):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.profiles:
            it = QListWidgetItem(("" if p.show_on_video else "(hidden) ") + p.name)
            it.setForeground(QColor(p.color).lighter(120))
            self.list.addItem(it)
        self.list.blockSignals(False)
        self.list.setCurrentRow(min(row, len(self.profiles) - 1))
        self._row(self.list.currentRow())

    def _cur(self):
        r = self.list.currentRow()
        return self.profiles[r] if 0 <= r < len(self.profiles) else None

    def _row(self, r):
        p = self._cur()
        self.name.setEnabled(p is not None)
        if p:
            self.name.setText(p.name)
            self.show_cb.blockSignals(True)
            self.show_cb.setChecked(p.show_on_video)
            self.show_cb.blockSignals(False)
            self.color_btn.setStyleSheet(f"background:{p.color}; color:{'#000' if QColor(p.color).lightness() > 150 else '#fff'};")

    def _rename(self, text):
        p = self._cur()
        if p:
            p.name = text
            it = self.list.currentItem()
            it.setText(("" if p.show_on_video else "(hidden) ") + text)

    def _color(self):
        p = self._cur()
        if p:
            c = QColorDialog.getColor(QColor(p.color), self, "Profile colour")
            if c.isValid():
                p.color = c.name().upper()
                self._fill(self.list.currentRow())

    def _show(self, on):
        p = self._cur()
        if p:
            p.show_on_video = on
            self._fill(self.list.currentRow())

    def _add(self):
        palette = ["#BF5AF2", "#64D2FF", "#FF9F0A", "#30D158", "#FF375F", "#FFD60A", "#5E5CE6", "#AC8E68"]
        color = palette[len(self.profiles) % len(palette)]
        self.profiles.append(Profile(f"Profile {len(self.profiles) + 1}", color))
        self._fill(len(self.profiles) - 1)
        self.name.setFocus()
        self.name.selectAll()

    def _remove(self):
        p = self._cur()
        if not p:
            return
        if len(self.profiles) <= 1:
            QMessageBox.information(self, "Profiles", "There must be at least one profile.")
            return
        used = sum(1 for c in self.project.comments if c.profile_id == p.id)
        target = None
        if used:
            others = [o for o in self.profiles if o.id != p.id]
            box = QMessageBox(self)
            box.setWindowTitle("Remove profile")
            box.setText(f"{used} comment(s) use \"{p.name}\".")
            box.setInformativeText(f"Move them to \"{others[0].name}\", or delete them?")
            move = box.addButton(f"Move to {others[0].name}", QMessageBox.ButtonRole.AcceptRole)
            delete = box.addButton("Delete comments", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() == move:
                target = others[0].id
            elif box.clickedButton() != delete:
                return
        self.removed[p.id] = target
        self.profiles.remove(p)
        self._fill(self.list.currentRow())

    def _move(self, d):
        r = self.list.currentRow()
        n = r + d
        if 0 <= r < len(self.profiles) and 0 <= n < len(self.profiles):
            self.profiles[r], self.profiles[n] = self.profiles[n], self.profiles[r]
            self._fill(n)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Q-Recorder project or recording log", "",
                                              "Q-Recorder (*.protokol *.json);;All files (*)")
        if not path:
            return
        try:
            roles = read_qrecorder_roles(path)
        except Exception as e:
            QMessageBox.warning(self, "Import", f"Could not read the file:\n{e}")
            return
        added = 0
        names = {p.name.lower() for p in self.profiles}
        for r in roles:
            if r.name.lower() not in names:
                self.profiles.append(r)
                names.add(r.name.lower())
                added += 1
        self._fill(len(self.profiles) - 1)
        QMessageBox.information(self, "Import", f"{added} profile(s) added." if added else "No new profiles found.")
