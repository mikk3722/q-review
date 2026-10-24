"""Main window: ties the player, the comment panel, the timeline and the files together."""
from __future__ import annotations

import os
import threading

from PyQt6.QtCore import Qt, QUrl, QTimer, QSettings, pyqtSignal, QEvent, QProcess
from PyQt6.QtGui import QAction, QKeySequence, QColor, QActionGroup, QIcon, QPixmap, QPainter
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QPushButton, QToolButton, QComboBox,
    QSlider, QCheckBox, QFileDialog, QMessageBox, QMenu, QStackedWidget, QInputDialog, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QDialog, QFormLayout, QDoubleSpinBox, QSpinBox,
    QDialogButtonBox, QProgressDialog, QListWidget, QListWidgetItem, QFrame, QSizePolicy,
)

from . import __version__, __build__, media
from .model import (Project, Comment, APP_NAME, FILE_EXT, fmt_precise, fmt_short, import_qrecorder,
                    is_qrecorder_log)
from .videoview import VideoView
from .timeline import TimelinePanel
from .panels import CommentInput, CommentList, ProfilesDialog, FlowLayout, chip_style
from .export_dialog import ExportDialog

# Everything FFmpeg reads that is reasonably common. Files with other endings are also tried (probed) when opened.
VIDEO_EXTS = {
    ".mp4", ".m4v", ".mov", ".qt", ".mkv", ".webm", ".avi", ".wmv", ".asf", ".flv", ".f4v",
    ".mpg", ".mpeg", ".mpe", ".m2v", ".vob", ".ts", ".mts", ".m2ts", ".m2t", ".tod", ".mod",
    ".mxf", ".dv", ".3gp", ".3g2", ".ogv", ".divx", ".xvid", ".rm", ".rmvb", ".nut", ".y4m",
    ".hevc", ".h264", ".264", ".h265", ".265", ".braw",
}
VIDEO_FILTER = ("Video (" + " ".join("*" + e for e in sorted(VIDEO_EXTS)) + " "
                + " ".join("*" + e.upper() for e in sorted(VIDEO_EXTS)) + ");;All files (*)")
PROJECT_EXTS = {FILE_EXT, ".json", ".protokol"}


def menu_item(menu, text, fn):
    a = menu.addAction(text)
    a.triggered.connect(lambda _=False: fn())
    return a


def icon_dot(color: str) -> QIcon:
    pm = QPixmap(12, 12)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(1, 1, 10, 10, 3, 3)
    p.end()
    return QIcon(pm)


class OverlayDialog(QDialog):
    """Look of the bubbles on the video."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Comments on video")
        st = win.project.style
        self.snap = win.begin_change()
        f = QFormLayout(self)
        self.size = QSpinBox()
        self.size.setRange(40, 250)
        self.size.setSuffix(" %")
        self.size.setValue(int(round(st.font_scale * 100)))
        f.addRow("Text size", self.size)
        self.stack = QSpinBox()
        self.stack.setRange(1, 12)
        self.stack.setValue(st.max_stacked)
        f.addRow("Bubbles at once (automatic position)", self.stack)
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setValue(int(round(st.opacity * 100)))
        f.addRow("Background", self.opacity)
        self.name = QCheckBox("Show the profile name above the text")
        self.name.setChecked(st.show_name)
        f.addRow("", self.name)
        self.dur = QDoubleSpinBox()
        self.dur.setRange(0.5, 120)
        self.dur.setSuffix(" s")
        self.dur.setValue(win.project.default_duration)
        f.addRow("Length of new comments", self.dur)
        for w in (self.size, self.stack, self.opacity):
            w.valueChanged.connect(self._apply)
        self.name.toggled.connect(self._apply)
        self.dur.valueChanged.connect(self._apply)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _apply(self, *_):
        st = self.win.project.style
        st.font_scale = self.size.value() / 100
        st.max_stacked = self.stack.value()
        st.opacity = self.opacity.value() / 100
        st.show_name = self.name.isChecked()
        self.win.project.default_duration = self.dur.value()
        self.win.live_changed()

    def accept(self):
        self.win.commit_change(self.snap, "Overlay settings")
        super().accept()

    def reject(self):
        self.win.project.restore(self.snap)
        self.win.refresh_all()
        super().reject()


class MainWindow(QMainWindow):
    mediaInfo = pyqtSignal(str, object)       # path, VideoInfo
    waveformReady = pyqtSignal(str, object)   # path, png path or None

    def __init__(self):
        super().__init__()
        self.settings = QSettings()
        self.project = Project()
        self.selected_id: str | None = None
        self.active_profile_id: str | None = self.project.profiles[0].id
        self.active_ids: set[str] = set()
        self.undo_stack: list[tuple[str, dict]] = []
        self.redo_stack: list[tuple[str, dict]] = []
        self.dirty = False
        self._time = 0.0
        self._input_time: float | None = None
        self._resume_after_input = False
        self._fit_pending = False
        self._replace_check: tuple[float, int] | None = None
        self._stop_at: float | None = None
        self.quiet = False   # self-test: no dialogs

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1400, 860)

        # Player
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(float(self.settings.value("volume", 0.8)))
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.errorOccurred.connect(self._media_error)
        self.player.positionChanged.connect(self._position_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

        self.mediaInfo.connect(self._media_info)
        self.waveformReady.connect(self._waveform_ready)

        self._build_ui()
        self._build_menus()
        self.player.setVideoOutput(self.video.video_item)
        QApplication.instance().installEventFilter(self)

        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self.refresh_all()
        self._update_title()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Left: comments
        left = QWidget()
        left.setMinimumWidth(300)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(10, 10, 6, 10)
        lv.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel("Profile")
        t.setStyleSheet("color:#9a9aa0; font-weight:600;")
        head.addWidget(t)
        head.addStretch()
        manage = QToolButton()
        manage.setText("Edit profiles …")
        manage.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        manage.clicked.connect(self.edit_profiles)
        head.addWidget(manage)
        lv.addLayout(head)
        self.chips_box = QWidget()
        self.chips = FlowLayout(self.chips_box)
        lv.addWidget(self.chips_box)

        list_head = QHBoxLayout()
        self.count_label = QLabel("Comments")
        self.count_label.setStyleSheet("color:#9a9aa0; font-weight:600;")
        list_head.addWidget(self.count_label)
        list_head.addStretch()
        self.follow = QCheckBox("Follow playback")
        self.follow.setChecked(True)
        self.follow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        list_head.addWidget(self.follow)
        lv.addLayout(list_head)
        self.list = CommentList(self)
        lv.addWidget(self.list, 1)
        # The writing card: stands out in the colour of the active profile
        self.composer = QFrame()
        self.composer.setObjectName("composer")
        cl = QVBoxLayout(self.composer)
        cl.setContentsMargins(12, 10, 12, 8)
        cl.setSpacing(6)
        top = QHBoxLayout()
        self.composer_title = QLabel()
        self.composer_title.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.composer_title)
        top.addStretch()
        self.input_time = QLabel()
        self.input_time.setStyleSheet("color:#ffd60a; font-family: Menlo, Consolas, monospace; font-size:15px; font-weight:600;")
        self.input_time.setToolTip("The comment is placed here. The time is held from when you start writing.")
        top.addWidget(self.input_time)
        cl.addLayout(top)
        self.input = CommentInput()
        self.input.submitted.connect(self._submit_comment)
        self.input.started.connect(self._input_started)
        self.input.cancelled.connect(self._input_cancelled)
        self.input.emptied.connect(self._input_cancelled)   # deleted it all again = same as Esc
        self.input.focusChanged.connect(lambda _f: self._style_composer())
        cl.addWidget(self.input)
        row = QHBoxLayout()
        hint = QLabel("Enter adds · Shift+Enter new line · Esc cancels")
        hint.setStyleSheet("color:#8e8e93; font-size:11px;")
        row.addWidget(hint)
        row.addStretch()
        self.pause_typing = QCheckBox("Pause while writing")
        self.pause_typing.setChecked(self.settings.value("pauseWhileTyping", True, bool))
        self.pause_typing.toggled.connect(lambda on: self.settings.setValue("pauseWhileTyping", on))
        self.pause_typing.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row.addWidget(self.pause_typing)
        cl.addLayout(row)
        lv.addWidget(self.composer)


        # Centre: video + transport
        self.video = VideoView(self)
        self.video.clicked.connect(self.toggle_play)
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._welcome())
        self.stack.addWidget(self.video)
        cv.addWidget(self.stack, 1)
        cv.addWidget(self._transport())

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(left)
        top.addWidget(center)
        top.setStretchFactor(0, 0)
        top.setStretchFactor(1, 1)
        top.setSizes([380, 1020])

        self.timeline_panel = TimelinePanel(self)
        self.timeline = self.timeline_panel.timeline
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(self.timeline_panel)
        main.setStretchFactor(0, 1)
        main.setStretchFactor(1, 0)
        main.setSizes([600, 230])
        self.setCentralWidget(main)
        self.statusBar().setSizeGripEnabled(True)

    def _welcome(self) -> QWidget:
        w = QWidget()
        w.setObjectName("welcome")
        v = QVBoxLayout(w)
        v.addStretch()
        title = QLabel(APP_NAME)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:30px; font-weight:700; color:#f2f2f7;")
        v.addWidget(title)
        ver = QLabel(f"Version {__version__}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet("color:#6e6e73;")
        v.addWidget(ver)
        sub = QLabel("Drop a video, a project or a Q-Recorder recording here")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color:#9a9aa0; font-size:14px;")
        v.addWidget(sub)
        v.addSpacing(18)
        row = QHBoxLayout()
        row.addStretch()
        for text, fn in (("Open video …", self.open_video_dialog), ("Open project …", self.open_dialog),
                         ("Open Q-Recorder recording …", self.open_qrecorder_dialog)):
            b = QPushButton(text)
            b.setMinimumHeight(34)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        v.addSpacing(14)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumWidth(560)
        self.recent_list.setMaximumHeight(170)
        self.recent_list.itemClicked.connect(lambda it: self._open_recent(it.data(Qt.ItemDataRole.UserRole)))
        rl = QHBoxLayout()
        rl.addStretch()
        rl.addWidget(self.recent_list)
        rl.addStretch()
        self.recent_title = QLabel("Recent")
        self.recent_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recent_title.setStyleSheet("color:#9a9aa0;")
        v.addWidget(self.recent_title)
        v.addLayout(rl)
        v.addStretch()
        return w

    def _transport(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("transport")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(4)

        def btn(text, tip, fn, w=34):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setMinimumWidth(w)
            b.clicked.connect(fn)
            h.addWidget(b)
            return b

        btn("◁|", "Nudge one frame back (,)", lambda: self.step_frame(-1))
        self.play_btn = btn("▶", "Play / pause (Space)", self.toggle_play, 46)
        btn("|▷", "Nudge one frame forward (.)", lambda: self.step_frame(1))
        h.addSpacing(10)
        self.time_label = QLabel("00:00:00.000 / 00:00:00.000")
        self.time_label.setStyleSheet("font-family: Consolas, Menlo, monospace; font-size:13px; color:#f2f2f7;")
        h.addWidget(self.time_label)
        h.addSpacing(12)
        self.in_btn = btn("[ In", "Set the in-point at the playhead (I)", self.set_in, 44)
        self.out_btn = btn("Out ]", "Set the out-point at the playhead (O)", self.set_out, 48)
        self.clear_btn = btn("✕", "Clear the trim", self.clear_trim, 26)
        self.lock_btn = btn("Lock", "Lock the in- and out-point so they can't be moved by accident (L)", self.toggle_trim_lock, 56)
        self.lock_btn.setCheckable(True)
        h.addStretch()
        self.overlay_cb = QCheckBox("Comments on video")
        self.overlay_cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.overlay_cb.toggled.connect(self._overlay_toggled)
        h.addWidget(self.overlay_cb)
        style = QToolButton()
        style.setText("Look …")
        style.setToolTip("Size and look of the comments on the video")
        style.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        style.clicked.connect(lambda: OverlayDialog(self).exec())
        h.addWidget(style)
        h.addSpacing(10)
        self.rate = QComboBox()
        for r in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            self.rate.addItem(f"{r:g}×", r)
        self.rate.setCurrentIndex(3)
        self.rate.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.rate.currentIndexChanged.connect(lambda _: self.player.setPlaybackRate(self.rate.currentData()))
        self.rate.setToolTip("Playback speed")
        h.addWidget(self.rate)
        vol = QSlider(Qt.Orientation.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(int(self.audio.volume() * 100))
        vol.setFixedWidth(90)
        vol.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        vol.setToolTip("Volume")
        vol.valueChanged.connect(self._volume)
        h.addWidget(QLabel("🔊"))
        h.addWidget(vol)
        export = QPushButton("Export …")
        export.setObjectName("primary")
        export.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        export.clicked.connect(self.export)
        h.addSpacing(8)
        h.addWidget(export)
        return bar

    def _build_menus(self):
        mb = self.menuBar()

        def act(menu, text, fn, shortcut=None, checkable=False):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setCheckable(checkable)
            a.triggered.connect(fn)
            menu.addAction(a)
            return a

        f = mb.addMenu("&File")
        act(f, "New project", self.new_project, "Ctrl+N")
        act(f, "Open …", self.open_dialog, "Ctrl+O")
        self.recent_menu = f.addMenu("Open recent")
        act(f, "Open Q-Recorder recording …", self.open_qrecorder_dialog, "Ctrl+Shift+O")
        f.addSeparator()
        act(f, "Save", self.save, "Ctrl+S")
        act(f, "Save as …", self.save_as, "Ctrl+Shift+S")
        act(f, "Save as folder with video …", self.save_as_folder)
        f.addSeparator()
        act(f, "Open video …", self.open_video_dialog)
        act(f, "Replace video …", self.replace_video_dialog, "Ctrl+R")
        f.addSeparator()
        act(f, "Export …", self.export, "Ctrl+E")
        f.addSeparator()
        act(f, "Quit", self.close, "Ctrl+Q")

        e = mb.addMenu("&Edit")
        self.undo_act = act(e, "Undo", self.undo, QKeySequence.StandardKey.Undo)
        self.redo_act = act(e, "Redo", self.redo, "Ctrl+Y")
        self.redo_act.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        e.addSeparator()
        act(e, "New comment", lambda: self.input.setFocus(), "Ctrl+Return")
        act(e, "Edit text of selected comment", lambda: self.edit_comment_text(self.selected_id), "F2")
        act(e, "Delete selected comment", lambda: self.delete_comment(self.selected_id))
        act(e, "Move selected comment to playhead", self.move_selected_to_playhead, "Ctrl+M")
        e.addSeparator()
        act(e, "Shift all comments …", self.shift_all)
        act(e, "Edit profiles …", self.edit_profiles, "Ctrl+P")
        self.profile_menu = e.addMenu("Active profile")

        v = mb.addMenu("&View")
        self.overlay_act = act(v, "Comments on video", lambda on: self._overlay_toggled(on), "Ctrl+T", checkable=True)
        act(v, "Look of comments on video …", lambda: OverlayDialog(self).exec())
        v.addSeparator()
        act(v, "Zoom timeline in", lambda: self.timeline.zoom(1.5), "Ctrl++")
        act(v, "Zoom timeline out", lambda: self.timeline.zoom(1 / 1.5), "Ctrl+-")
        act(v, "Show whole video in timeline", self.timeline.fit, "Ctrl+0")

        p = mb.addMenu("&Playback")
        act(p, "Play / pause  (Space)", self.toggle_play)
        act(p, "Set in-point  (I)", self.set_in)
        act(p, "Set out-point  (O)", self.set_out)
        act(p, "Clear trim", self.clear_trim)
        act(p, "Lock / unlock in and out  (L)", self.toggle_trim_lock)

        hm = mb.addMenu("&Help")
        act(hm, "Keyboard shortcuts", self.show_shortcuts)
        act(hm, f"About {APP_NAME}", self.about)
        self._update_recent_menu()

    # ── Controller API (used by the timeline, video view and panels) ──────────

    def current_time(self) -> float:
        return self._time

    def seek(self, t: float, fast: bool = False):
        d = self.project.video_duration
        t = max(0.0, min(t, d) if d > 0 else t)
        self._time = t
        self._stop_at = None
        if self.project.video_path:
            self.player.setPosition(int(round(t * 1000)))
        self._refresh_time()

    def skip(self, s: float):
        self.seek(self._time + s)

    def step_frame(self, n: int):
        self.pause()
        self.seek(self._time + n / max(1.0, self.project.video_fps))

    def select(self, cid: str | None):
        if cid == self.selected_id:
            return
        self.selected_id = cid
        self.list.sync_selection()
        self.timeline.update()
        self.video.refresh()

    def set_active_profile(self, pid: str):
        self.active_profile_id = pid
        self._rebuild_chips()
        self._style_composer()
        self.timeline.update()

    def begin_change(self) -> dict:
        return self.project.snapshot()

    def commit_change(self, snap: dict, label: str):
        if snap != self.project.snapshot():
            self.undo_stack.append((label, snap))
            del self.undo_stack[:-300]
            self.redo_stack.clear()
            self._set_dirty(True)
        self.refresh_all()

    def change(self, fn, label: str):
        snap = self.begin_change()
        fn()
        self.commit_change(snap, label)

    def live_changed(self):
        """While dragging: redraw without adding to undo."""
        self.timeline.update()
        self.video.refresh()
        self.list.viewport().update()
        self._refresh_time()

    def jump_to(self, cid: str):
        c = self.project.comment(cid)
        if not c:
            return
        self.select(cid)
        self.seek(c.start)

    def toggle_on_video(self, cid: str):
        c = self.project.comment(cid)
        if c:
            self.change(lambda: setattr(c, "on_video", not c.on_video), "Show on video")

    def reset_position(self, cid: str | None):
        c = self.project.comment(cid)
        if c and c.has_position:
            def fn():
                c.x = c.y = None
            self.change(fn, "Automatic position")

    def move_selected_to_playhead(self):
        c = self.project.comment(self.selected_id)
        if c:
            self.change(lambda: setattr(c, "start", self._time), "Move to playhead")

    def delete_comment(self, cid: str | None):
        c = self.project.comment(cid)
        if not c:
            return
        self.change(lambda: self.project.comments.remove(c), "Delete comment")
        if self.selected_id == cid:
            self.select(None)

    def edit_comment_text(self, cid: str | None):
        c = self.project.comment(cid)
        if not c:
            return
        self.select(cid)
        was = self.pause()
        text, ok = QInputDialog.getMultiLineText(self, "Edit comment", f"{fmt_short(c.start)} · {self.project.prefix(c)}", c.text)
        if ok and text.strip() and text.strip() != c.text:
            self.change(lambda: setattr(c, "text", text.strip()), "Edit text")
        if was:
            self.play()

    def add_comment_dialog(self, pid: str | None, t: float):
        if not self.project.video_path:
            return
        was = self.pause()
        prof = self.project.profile(pid) or self.project.profile(self.active_profile_id)
        text, ok = QInputDialog.getMultiLineText(self, "New comment", f"{fmt_short(t)} · {prof.name if prof else ''}", "")
        if ok and text.strip():
            self.add_comment(text.strip(), t, prof.id if prof else None)
        if was:
            self.play()

    def add_comment(self, text: str, t: float, pid: str | None = None) -> Comment:
        prof = self.project.profile(pid or self.active_profile_id) or self.project.profiles[0]
        c = Comment(profile_id=prof.id, text=text, start=max(0.0, t), duration=self.project.default_duration,
                    on_video=prof.show_on_video)
        self.change(lambda: self.project.comments.append(c), "Add comment")
        self.select(c.id)
        return c

    def comment_menu(self, cid: str, pos):
        c = self.project.comment(cid)
        if not c:
            return
        m = QMenu(self)
        menu_item(m, "Edit text …", lambda: self.edit_comment_text(cid))
        menu_item(m, "Go to comment", lambda: self.jump_to(cid))
        menu_item(m, "Move to playhead", lambda: (self.select(cid), self.move_selected_to_playhead()))
        pm = m.addMenu("Profile")
        for p in self.project.profiles:
            a = pm.addAction(icon_dot(p.color), p.name)
            a.setCheckable(True)
            a.setChecked(p.id == c.profile_id)
            a.triggered.connect(lambda _=False, pid=p.id: self.change(lambda: setattr(c, "profile_id", pid), "Change profile"))
        a = m.addAction("Show on video")
        a.setCheckable(True)
        a.setChecked(c.on_video)
        a.triggered.connect(lambda: self.toggle_on_video(cid))
        r = menu_item(m, "Automatic position (bottom left)", lambda: self.reset_position(cid))
        r.setEnabled(c.has_position)
        menu_item(m, "Length …", lambda: self._ask_length(cid))
        menu_item(m, "Duplicate", lambda: self._duplicate(cid))
        m.addSeparator()
        menu_item(m, "Delete", lambda: self.delete_comment(cid))
        m.exec(pos)

    def empty_track_menu(self, pid: str | None, t: float, pos):
        if not self.project.video_path:
            return
        m = QMenu(self)
        prof = self.project.profile(pid)
        menu_item(m, f"New comment here ({prof.name if prof else ''}) …", lambda: self.add_comment_dialog(pid, t))
        a1 = menu_item(m, "Set in-point here", lambda: self._set_trim(t, None))
        a2 = menu_item(m, "Set out-point here", lambda: self._set_trim(None, t))
        a3 = menu_item(m, "Out-point at the end of the video", lambda: self._set_trim(None, self.project.video_duration))
        for a in (a1, a2, a3):
            a.setEnabled(not self.project.trim_locked)
        m.exec(pos)

    def _ask_length(self, cid):
        c = self.project.comment(cid)
        if c:
            v, ok = QInputDialog.getDouble(self, "Length", "How long the comment is shown (seconds):", c.duration, 0.2, 36000, 1)
            if ok:
                self.change(lambda: setattr(c, "duration", v), "Change length")

    def _duplicate(self, cid):
        c = self.project.comment(cid)
        if c:
            n = Comment(profile_id=c.profile_id, text=c.text, start=c.end, duration=c.duration,
                        on_video=c.on_video, x=c.x, y=c.y, author=c.author)
            self.change(lambda: self.project.comments.append(n), "Duplicate")
            self.select(n.id)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_all(self):
        p = self.project
        if self.project.profile(self.active_profile_id) is None:
            self.active_profile_id = p.profiles[0].id if p.profiles else None
        if self.selected_id and p.comment(self.selected_id) is None:
            self.selected_id = None
        self._rebuild_chips()
        self._style_composer()
        self.list.rebuild()
        n = len(p.comments)
        self.count_label.setText(f"Comments ({n})")
        self.overlay_cb.blockSignals(True)
        self.overlay_cb.setChecked(p.overlay_enabled)
        self.overlay_cb.blockSignals(False)
        self.overlay_act.blockSignals(True)
        self.overlay_act.setChecked(p.overlay_enabled)
        self.overlay_act.blockSignals(False)
        locked = p.trim_locked
        self.lock_btn.blockSignals(True)
        self.lock_btn.setChecked(locked)
        self.lock_btn.blockSignals(False)
        self.lock_btn.setText("🔒 Locked" if locked else "Lock")
        for b in (self.in_btn, self.out_btn, self.clear_btn):
            b.setEnabled(not locked)
        self.undo_act.setText(f"Undo {self.undo_stack[-1][0]}" if self.undo_stack else "Undo")
        self.undo_act.setEnabled(bool(self.undo_stack))
        self.redo_act.setText(f"Redo {self.redo_stack[-1][0]}" if self.redo_stack else "Redo")
        self.redo_act.setEnabled(bool(self.redo_stack))
        self.stack.setCurrentIndex(1 if p.video_path else 0)
        self.timeline.update()
        self.timeline_panel._sync_bar()
        self.video.refresh()
        self._refresh_time()
        self._update_recent_list()

    def _rebuild_chips(self):
        key = (tuple((p.id, p.name, p.color, p.show_on_video) for p in self.project.profiles), self.active_profile_id)
        if key == getattr(self, "_chips_key", None):
            return
        self._chips_key = key
        while self.chips.count():
            it = self.chips.takeAt(0)
            w = it.widget() if it else None
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.profile_menu.clear()
        if getattr(self, "_profile_group", None) is not None:
            self._profile_group.deleteLater()
        group = self._profile_group = QActionGroup(self)
        for i, p in enumerate(self.project.profiles):
            b = QPushButton(p.name)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(chip_style(p.color, p.id == self.active_profile_id))
            tip = f"New comments are written as {p.name}"
            if i < 9:
                tip += f"  (Ctrl+{i + 1})"
            if not p.show_on_video:
                tip += "\nThis profile is not shown on the video."
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, pid=p.id: self.set_active_profile(pid))
            self.chips.addWidget(b)
            a = QAction(icon_dot(p.color), p.name, self.profile_menu)
            a.setCheckable(True)
            a.setChecked(p.id == self.active_profile_id)
            if i < 9:
                a.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            a.triggered.connect(lambda _=False, pid=p.id: self.set_active_profile(pid))
            group.addAction(a)
            self.profile_menu.addAction(a)
        self.chips_box.updateGeometry()
        self.chips_box.setMinimumHeight(self.chips.heightForWidth(max(200, self.chips_box.width())))

    def _refresh_time(self):
        p = self.project
        d = p.video_duration
        self.time_label.setText(f"{fmt_precise(self._time)} / {fmt_precise(d)}")
        if self._input_time is None:
            self.input_time.setText(fmt_short(self._time))
        active = {c.id for c in p.comments_at(self._time, only_video=False)}
        if active != self.active_ids:
            new = active - self.active_ids
            self.active_ids = active
            self.list.viewport().update()
            if new and self.follow.isChecked() and self.is_playing():
                first = min((p.comment(i) for i in new), key=lambda c: c.start)
                self.list.scroll_to(first.id)
        self.timeline.update()
        self.video.refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, lambda: self.chips_box.setMinimumHeight(
            self.chips.heightForWidth(max(200, self.chips_box.width()))))

    # ── Player ────────────────────────────────────────────────────────────────

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def play(self):
        if not self.project.video_path:
            return
        p = self.project
        out = p.effective_out() if p.video_duration > 0 else None
        if out is not None and (self._time >= out - 0.05 or self._time < p.trim_in - 0.05) and p.is_trimmed():
            self.seek(p.trim_in)
        elif p.video_duration > 0 and self._time >= p.video_duration - 0.05:
            self.seek(0)
        self._stop_at = out if (p.is_trimmed() and out is not None and self._time < out) else None
        self.player.play()

    def pause(self) -> bool:
        """Pauses; returns True if it was playing."""
        was = self.is_playing()
        if was:
            self.player.pause()
        return was

    def toggle_play(self):
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def _state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("❚❚" if playing else "▶")
        if playing:
            self.timer.start()
        else:
            self.timer.stop()
            self._time = self.player.position() / 1000
            self._refresh_time()

    def _tick(self):
        self._time = self.player.position() / 1000
        if self._stop_at is not None and self._time >= self._stop_at:
            self.player.pause()
            self.seek(self._stop_at)
        self.timeline.follow(self._time)
        self._refresh_time()

    def _position_changed(self, ms):
        if not self.is_playing() and abs(ms / 1000 - self._time) > 0.5:
            # Only when the player moved on its own (e.g. reached the end)
            if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self._time = ms / 1000
                self._refresh_time()

    def _duration_changed(self, ms):
        if ms <= 0:
            return
        d = ms / 1000
        if self.project.video_duration <= 0 or abs(self.project.video_duration - d) > 0.5:
            self.project.video_duration = d
        if self.project.trim_out is not None and self.project.trim_out >= d - 0.001:
            self.project.trim_out = None
        if self.project.trim_in >= d:
            self.project.trim_in = 0.0
        if self._fit_pending:
            self._fit_pending = False
            QTimer.singleShot(0, self.timeline.fit)
        if self._replace_check:
            old_d, _ = self._replace_check
            self._replace_check = None
            outside = [c for c in self.project.comments if c.start >= d]
            if outside and not self.quiet:
                QMessageBox.information(
                    self, "Replace video",
                    f"The new video is {fmt_short(d)} long (the old one was {fmt_short(old_d)}).\n\n"
                    f"{len(outside)} comment(s) are after the end of the new video. They are kept, but are not "
                    f"exported. Use Edit → Shift all comments if the new video starts at a different point.")
        self.refresh_all()

    def _media_error(self, error, text):
        if error == QMediaPlayer.Error.NoError or not self.project.video_path:
            return
        if self.quiet:
            print(f"Media error: {error} {text}", flush=True)
            return
        self._offer_convert(text)

    def _offer_convert(self, reason: str):
        """When the player can't show a video, offer to make an H.264 copy that always plays."""
        path = self.project.video_path
        if not path or getattr(self, "_convert_offered", None) == path:
            return
        self._convert_offered = path
        box = QMessageBox(self)
        box.setWindowTitle("Video")
        box.setText(f"The video cannot be played here:\n{os.path.basename(path)}")
        box.setInformativeText(f"{reason}\n\nQ-Review can make a playable copy (H.264 MP4) next to the original. "
                               f"The comments stay where they are, and the export works from the copy.")
        conv = box.addButton("Make playable copy", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() == conv:
            self.convert_video(path)

    def convert_video(self, path: str):
        ff = media.ffmpeg_path()
        if not ff:
            QMessageBox.warning(self, "Video", "FFmpeg was not found.")
            return
        base = os.path.splitext(path)[0] + " (playable)"
        out, n = base + ".mp4", 2
        while os.path.exists(out):
            out, n = f"{base} {n}.mp4", n + 1
        info = media.probe(path)
        dlg = QProgressDialog("Making a playable copy …", "Cancel", 0, 1000, self)
        dlg.setWindowTitle("Video")
        dlg.setMinimumDuration(0)
        proc = QProcess(self)
        args = ["-hide_banner", "-y", "-nostdin", "-progress", "pipe:1", "-nostats", "-loglevel", "error", "-i", path,
                "-map", "0:v:0", "-map", "0:a?"]
        if info.interlaced:
            args += ["-vf", "bwdif=mode=send_frame:parity=auto:deint=all"]
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]

        def progress():
            for line in bytes(proc.readAllStandardOutput()).decode("utf-8", "replace").splitlines():
                if line.startswith("out_time_us=") and info.duration > 0:
                    try:
                        dlg.setValue(int(min(1.0, int(line[12:]) / 1e6 / info.duration) * 1000))
                    except ValueError:
                        pass

        def finished(code, _s):
            dlg.reset()
            if code == 0 and os.path.exists(out):
                self._load_video(out, replace=True)
                self._set_dirty(True)
                self.statusBar().showMessage(f"Using the playable copy: {os.path.basename(out)}", 8000)
            elif not dlg.wasCanceled():
                QMessageBox.warning(self, "Video", "The copy could not be made.")

        proc.readyReadStandardOutput.connect(progress)
        proc.finished.connect(finished)
        dlg.canceled.connect(proc.kill)
        proc.start(ff, args)

    def _volume(self, v):
        self.audio.setVolume(v / 100)
        self.settings.setValue("volume", v / 100)

    # ── Writing comments ──────────────────────────────────────────────────────

    def _input_started(self):
        self._input_time = self._time
        self.input_time.setText(f"🔒 {fmt_short(self._time)}")
        self._style_composer()
        if self.pause_typing.isChecked():
            self._resume_after_input = self.pause()

    def _submit_comment(self, text: str):
        if not self.project.video_path:
            QMessageBox.information(self, APP_NAME, "Open a video first.")
            return
        t = self._input_time if self._input_time is not None else self._time
        self.add_comment(text, t)
        self.input.blockSignals(True)
        self.input.clear()
        self.input.blockSignals(False)
        self.input._was_empty = True
        self._input_done()

    def _input_cancelled(self):
        self._input_done()

    def _style_composer(self):
        prof = self.project.profile(self.active_profile_id)
        color = QColor(prof.color if prof else "#0a84ff")
        name = prof.name if prof else ""
        active = self.input.hasFocus() or self._input_time is not None
        border = color.name() if active else color.darker(150).name()
        bg = "#2b2b30" if active else "#252529"
        glow = f"{color.red()},{color.green()},{color.blue()}"
        self.composer.setStyleSheet(
            f"QFrame#composer {{ background:{bg}; border:2px solid {border}; border-radius:10px; }}"
            f"QFrame#composer QLabel, QFrame#composer QCheckBox {{ background:transparent; border:none; }}"
            f"QPlainTextEdit#composerInput {{ background:rgba({glow},{0.10 if active else 0.05}); border:1px solid "
            f"rgba({glow},{0.55 if active else 0.25}); border-radius:7px; padding:4px; color:#ffffff; }}")
        self.composer_title.setText(
            f"<span style='color:{color.name()}; font-size:15px;'>●</span>"
            f"&nbsp;<b style='color:#f2f2f7; font-size:14px;'>New comment</b>"
            f"<span style='color:#9a9aa0; font-size:13px;'>&nbsp;·&nbsp;{name}</span>")

    def _input_done(self):
        self._input_time = None
        QTimer.singleShot(0, self._style_composer)
        if self._resume_after_input:
            self._resume_after_input = False
            self.play()
        self._refresh_time()

    # ── Trim ──────────────────────────────────────────────────────────────────

    def _trim_locked_note(self) -> bool:
        if self.project.trim_locked:
            self.statusBar().showMessage("In and out are locked – click Lock to change them.", 4000)
            return True
        return False

    def toggle_trim_lock(self):
        on = not self.project.trim_locked
        self.change(lambda: setattr(self.project, "trim_locked", on), "Lock in/out" if on else "Unlock in/out")

    def _set_trim(self, tin, tout):
        p = self.project
        if self._trim_locked_note():
            return

        def fn():
            if tin is not None:
                p.trim_in = max(0.0, min(tin, p.effective_out() - 0.1 if p.video_duration > 0 else tin))
            if tout is not None:
                t = max(tout, p.trim_in + 0.1)
                p.trim_out = p.out_or_end(t)
        self.change(fn, "Trim")

    def set_in(self):
        self._set_trim(self._time, None)

    def set_out(self):
        self._set_trim(None, self._time)

    def clear_trim(self):
        if self._trim_locked_note():
            return

        def fn():
            self.project.trim_in = 0.0
            self.project.trim_out = None
        self.change(fn, "Clear trim")

    def shift_all(self):
        if not self.project.comments:
            return
        s, ok = QInputDialog.getDouble(self, "Shift all comments",
                                       "Move all comments by (seconds, negative = earlier):", 0.0, -36000, 36000, 3)
        if ok and s:
            def fn():
                for c in self.project.comments:
                    c.start = max(0.0, c.start + s)
            self.change(fn, "Shift all comments")

    def _overlay_toggled(self, on):
        if on != self.project.overlay_enabled:
            self.change(lambda: setattr(self.project, "overlay_enabled", bool(on)), "Comments on video")

    # ── Undo ──────────────────────────────────────────────────────────────────

    def undo(self):
        if self.undo_stack:
            label, snap = self.undo_stack.pop()
            self.redo_stack.append((label, self.project.snapshot()))
            self.project.restore(snap)
            self._set_dirty(True)
            self.refresh_all()
            self.statusBar().showMessage(f"Undid: {label}", 3000)

    def redo(self):
        if self.redo_stack:
            label, snap = self.redo_stack.pop()
            self.undo_stack.append((label, self.project.snapshot()))
            self.project.restore(snap)
            self._set_dirty(True)
            self.refresh_all()

    # ── Profiles ──────────────────────────────────────────────────────────────

    def edit_profiles(self):
        dlg = ProfilesDialog(self.project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        p = self.project

        def fn():
            for removed, target in dlg.removed.items():
                if target is None:
                    p.comments = [c for c in p.comments if c.profile_id != removed]
                else:
                    for c in p.comments:
                        if c.profile_id == removed:
                            c.profile_id = target
            p.profiles = dlg.profiles
        self.change(fn, "Edit profiles")

    # ── Files ─────────────────────────────────────────────────────────────────

    def _set_dirty(self, d: bool):
        self.dirty = d
        self._update_title()

    def _update_title(self):
        p = self.project
        if p.path:
            name = os.path.splitext(os.path.basename(p.path))[0]
        elif p.video_path:
            name = os.path.basename(p.video_path) + " (not saved)"
        else:
            name = "Untitled"
        self.setWindowTitle(f"{name}{' •' if self.dirty else ''} – {APP_NAME} {__version__}")
        self.setWindowModified(self.dirty)

    def confirm_discard(self) -> bool:
        if not self.dirty or (not self.project.comments and not self.project.path and not self.project.is_trimmed()):
            return True
        was = self.pause()
        r = QMessageBox.question(self, APP_NAME, "Save the changes to the project?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        if r == QMessageBox.StandardButton.Discard:
            return True
        if was:
            self.play()
        return False

    def _set_project(self, project: Project, dirty=False):
        self.player.stop()
        self.player.setSource(QUrl())
        self.project = project
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.selected_id = None
        self._time = 0.0
        self.active_profile_id = project.profiles[0].id if project.profiles else None
        self.timeline.set_waveform(None)
        self._set_dirty(dirty)
        if project.video_path and os.path.exists(project.video_path):
            self._load_video(project.video_path)
        self.refresh_all()
        self._update_title()

    def new_project(self):
        if not self.confirm_discard():
            return
        self._set_project(Project())

    def open_dialog(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open", self._last_dir(),
            f"Projects and videos (*{FILE_EXT} *.json " + " ".join("*" + e for e in VIDEO_EXTS) +
            f");;{APP_NAME} project (*{FILE_EXT});;Q-Recorder recording (*.json);;" + VIDEO_FILTER)
        if path:
            self.open_any(path, asked=True)

    def open_video_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open video", self._last_dir(), VIDEO_FILTER)
        if path:
            self.open_any(path)

    def open_qrecorder_dialog(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Q-Recorder recording", self._last_dir(),
                                              "Q-Recorder recording (*.json *.mov *.mp4);;All files (*)")
        if path:
            if os.path.splitext(path)[1].lower() != ".json":
                j = os.path.splitext(path)[0] + ".json"
                if not os.path.exists(j):
                    QMessageBox.warning(self, "Q-Recorder", "There is no .json log next to this video.")
                    return
                path = j
            self.open_any(path, asked=True)

    def _last_dir(self) -> str:
        return str(self.settings.value("lastDir", os.path.expanduser("~")))

    def open_any(self, path: str, asked: bool = False):
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, APP_NAME, f"The file was not found:\n{path}")
            self._remove_recent(path)
            return
        self.settings.setValue("lastDir", os.path.dirname(path))
        ext = os.path.splitext(path)[1].lower()
        if ext not in VIDEO_EXTS and ext not in PROJECT_EXTS:
            # Unknown ending: open it as a video if FFmpeg finds a picture in it
            info = media.probe(path)
            if info.width > 0:
                ext = ".mp4"
            else:
                QMessageBox.warning(self, APP_NAME, f"{os.path.basename(path)} is not a video or project Q-Review can read.")
                return
        if ext in VIDEO_EXTS:
            if self.project.video_path and (self.project.comments or self.project.path):
                box = QMessageBox(self)
                box.setWindowTitle("Open video")
                box.setText(f"Open {os.path.basename(path)}")
                box.setInformativeText("Replace the video in this project (the comments are kept), or start a new project?")
                rep = box.addButton("Replace video", QMessageBox.ButtonRole.AcceptRole)
                new = box.addButton("New project", QMessageBox.ButtonRole.ActionRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.exec()
                if box.clickedButton() == rep:
                    self.replace_video(path)
                elif box.clickedButton() == new and self.confirm_discard():
                    self._new_with_video(path)
                return
            if self.project.video_path is None and (self.project.comments or self.project.path):
                self.replace_video(path)
                return
            if not asked and not self.confirm_discard():
                return
            self._new_with_video(path)
            return
        if not asked and not self.confirm_discard():
            return
        try:
            if ext == ".json" and is_qrecorder_log(path):
                proj = import_qrecorder(path)
                if not os.path.exists(proj.video_path or ""):
                    if not self.quiet:
                        QMessageBox.information(self, "Q-Recorder",
                                                f"The video {os.path.basename(proj.video_path or '')} is not next to the log. "
                                                f"Choose the video with File → Replace video.")
                    proj.video_path = None
                self._set_project(proj, dirty=True)
                self.statusBar().showMessage(
                    f"Imported {len(proj.comments)} comment(s) from Q-Recorder – the recording itself is not changed. "
                    f"Save to keep the project.", 10000)
                return
            proj = Project.load(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Could not open {os.path.basename(path)}:\n{e}")
            return
        missing = proj.video_path and not os.path.exists(proj.video_path)
        self._set_project(proj)
        self._add_recent(path)
        if missing and not self.quiet:
            r = QMessageBox.question(self, "Video not found",
                                     f"The video was not found:\n{proj.video_path}\n\nFind it (or choose another video)?")
            if r == QMessageBox.StandardButton.Yes:
                self.replace_video_dialog()

    def _new_with_video(self, path: str):
        p = Project()
        # Keep the profiles the user already set up
        p.profiles = [type(x)(x.name, x.color, x.show_on_video, x.id) for x in self.project.profiles]
        p.style = self.project.style
        p.default_duration = self.project.default_duration
        p.video_path = path
        self._set_project(p)
        self.statusBar().showMessage("Write comments on the left. Save the project with Ctrl+S.", 8000)

    def replace_video_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the new video", self._last_dir(), VIDEO_FILTER)
        if path:
            self.replace_video(path)

    def replace_video(self, path: str):
        old_d = self.project.video_duration
        snap = self.begin_change()
        self.project.video_path = path
        self.project.video_duration = 0.0
        self._replace_check = (old_d, len(self.project.comments)) if self.project.comments else None
        self._load_video(path, replace=True)
        self.commit_change(snap, "Replace video")
        self._set_dirty(True)

    def _load_video(self, path: str, replace: bool = False):
        self.project.video_path = path
        self._fit_pending = True
        self.timeline.set_waveform(None)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.setPlaybackRate(self.rate.currentData() or 1.0)
        self._time = 0.0
        # Show the first frame (paused, at the in-point)
        start = self.project.trim_in
        self._time = start

        def first_frame():
            if self.project.video_path == path and not self.is_playing():
                self.player.pause()
                self.player.setPosition(int(start * 1000))
        QTimer.singleShot(200, first_frame)

        def work():
            info = media.probe(path)
            self.mediaInfo.emit(path, info)
            wave = media.make_waveform(path) if info.has_audio or info.duration == 0 else None
            self.waveformReady.emit(path, wave)
        threading.Thread(target=work, daemon=True).start()
        self.refresh_all()

    def _media_info(self, path, info):
        if path != self.project.video_path:
            return
        if info.width and info.height:
            self.project.video_size = (info.width, info.height)
        self.project.video_fps = info.fps or 25.0
        if info.duration > 0 and info.width == 0 and not self.quiet:
            QMessageBox.information(self, "Video", f"{os.path.basename(path)} has no picture – only sound.")
        elif info.width:
            # Picture in the file but none in the player after a while → offer a playable copy
            def check():
                if self.project.video_path == path and not self.video.video_item.nativeSize().isValid() \
                        and not self.quiet:
                    codec = f" ({info.video_codec})" if info.video_codec else ""
                    self._offer_convert(f"The player shows no picture for this video format{codec}.")
            QTimer.singleShot(5000, check)
        if info.duration > 0 and self.project.video_duration <= 0:
            self.project.video_duration = info.duration
            if self._fit_pending:
                self._fit_pending = False
                self.timeline.fit()
        self.video.relayout()
        self.statusBar().showMessage(
            f"{os.path.basename(path)} · {info.width}×{info.height} · {info.fps:g} fps · {fmt_precise(info.duration)}"
            + ("" if info.has_audio else " · no sound"), 8000)
        self.refresh_all()

    def _waveform_ready(self, path, png):
        if path == self.project.video_path:
            self.timeline.set_waveform(png)

    def save(self) -> bool:
        if not self.project.path:
            return self.save_as()
        try:
            self.project.save(self.project.path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Could not save:\n{e}")
            return False
        self._set_dirty(False)
        self._add_recent(self.project.path)
        self.statusBar().showMessage(f"Saved {os.path.basename(self.project.path)}", 4000)
        return True

    def save_as(self) -> bool:
        p = self.project
        if p.path:
            start = p.path
        elif p.video_path:
            start = os.path.splitext(p.video_path)[0] + FILE_EXT
        else:
            start = os.path.join(self._last_dir(), "Project" + FILE_EXT)
        path, _ = QFileDialog.getSaveFileName(self, "Save project", start, f"{APP_NAME} project (*{FILE_EXT})")
        if not path:
            return False
        if not path.lower().endswith(FILE_EXT):
            path += FILE_EXT
        p.path = path
        return self.save()

    def save_as_folder(self) -> bool:
        """A folder with the project and a copy of the video – easy to move or send as one."""
        p = self.project
        if not p.video_path or not os.path.exists(p.video_path):
            QMessageBox.information(self, APP_NAME, "Open a video first.")
            return False
        default = os.path.splitext(os.path.basename(p.path or p.video_path))[0]
        parent = QFileDialog.getExistingDirectory(self, "Where should the project folder be made?", self._last_dir())
        if not parent:
            return False
        name, ok = QInputDialog.getText(self, "Save as folder", "Name of the new folder:", text=default)
        name = "".join(ch for ch in (name or "") if ch not in '<>:"/\\|?*').strip()
        if not ok or not name:
            return False
        folder = os.path.join(parent, name)
        if os.path.exists(folder) and os.listdir(folder):
            if QMessageBox.question(self, "Save as folder", f"The folder \"{name}\" already exists and is not empty.\n"
                                    "Put the project in it anyway?") != QMessageBox.StandardButton.Yes:
                return False
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, os.path.basename(p.video_path))
        if os.path.normcase(os.path.abspath(target)) != os.path.normcase(os.path.abspath(p.video_path)):
            if os.path.exists(target) and os.path.getsize(target) == os.path.getsize(p.video_path):
                pass   # already copied
            elif not self._copy_with_progress(p.video_path, target):
                return False
        p.video_path = target
        p.path = os.path.join(folder, name + FILE_EXT)
        self.settings.setValue("lastDir", parent)
        ok = self.save()
        if ok:
            self.statusBar().showMessage(f"Saved in the folder {folder} – the project now uses the copy of the video.", 8000)
        return ok

    def _copy_with_progress(self, src: str, dst: str) -> bool:
        size = max(1, os.path.getsize(src))
        dlg = QProgressDialog(f"Copying {os.path.basename(src)} …", "Cancel", 0, 1000, self)
        dlg.setWindowTitle("Save as folder")
        dlg.setMinimumDuration(0)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        tmp = dst + ".part"
        done = 0
        try:
            with open(src, "rb") as fi, open(tmp, "wb") as fo:
                while True:
                    chunk = fi.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    fo.write(chunk)
                    done += len(chunk)
                    dlg.setValue(int(done / size * 1000))
                    QApplication.processEvents()
                    if dlg.wasCanceled():
                        raise InterruptedError
            os.replace(tmp, dst)
            return True
        except InterruptedError:
            pass
        except Exception as e:
            QMessageBox.warning(self, "Save as folder", f"Could not copy the video:\n{e}")
        finally:
            dlg.reset()
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return False

    # Recent projects
    def _recent(self) -> list[str]:
        v = self.settings.value("recent", [])
        if isinstance(v, str):
            v = [v]
        return [x for x in (v or []) if isinstance(x, str)]

    def _add_recent(self, path):
        lst = [x for x in self._recent() if os.path.normcase(x) != os.path.normcase(path)]
        lst.insert(0, path)
        self.settings.setValue("recent", lst[:10])
        self._update_recent_menu()

    def _remove_recent(self, path):
        self.settings.setValue("recent", [x for x in self._recent() if x != path])
        self._update_recent_menu()

    def _open_recent(self, path):
        if self.confirm_discard():
            self.open_any(path, asked=True)

    def _update_recent_menu(self):
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.clear()
        for path in self._recent():
            menu_item(self.recent_menu, os.path.basename(path), lambda _=False, p=path: self._open_recent(p))
        if not self._recent():
            a = self.recent_menu.addAction("(none)")
            a.setEnabled(False)
        self._update_recent_list()

    def _update_recent_list(self):
        if not hasattr(self, "recent_list"):
            return
        items = self._recent()
        self.recent_list.clear()
        for path in items:
            it = QListWidgetItem(f"{os.path.basename(path)}    —    {os.path.dirname(path)}")
            it.setData(Qt.ItemDataRole.UserRole, path)
            self.recent_list.addItem(it)
        self.recent_list.setVisible(bool(items))
        self.recent_title.setVisible(bool(items))

    # ── Export ────────────────────────────────────────────────────────────────

    def export(self):
        if not self.project.video_path:
            QMessageBox.information(self, "Export", "Open a video first.")
            return
        self.pause()
        ExportDialog(self.project, self).exec()

    # ── Help ──────────────────────────────────────────────────────────────────

    def show_shortcuts(self):
        QMessageBox.information(self, "Keyboard shortcuts", (
            "Space\tPlay / pause\n"
            "← / →\t5 s back / forward (Shift: 1 s)\n"
            ", / .\tOne frame back / forward\n"
            "I / O\tSet in / out point\n"
            "L\tLock / unlock in and out\n"
            "Home / End\tGo to in / out point\n"
            "Enter\tWrite a new comment\n"
            "Esc\tCancel the comment you are writing\n"
            "Ctrl+1 … 9\tChoose profile\n"
            "F2\tEdit the selected comment\n"
            "Delete\tDelete the selected comment\n"
            "Ctrl+M\tMove the selected comment to the playhead\n"
            "Ctrl+T\tComments on video on/off\n"
            "Ctrl+Z / Ctrl+Y\tUndo / redo\n"
            "Ctrl+wheel\tZoom the timeline\n"
            "Alt (while dragging)\tNo snapping"))

    def about(self):
        QMessageBox.about(self, APP_NAME, (
            f"<b>{APP_NAME}</b> {__version__}<br><span style='color:#8e8e93'>{__build__}</span><br><br>"
            "Comments on video – part of the Q-Recorder family.<br><br>"
            "Mikkel Peter Larsen &amp; Claude (Anthropic)<br>"
            "Uses Qt / PyQt6 and FFmpeg."))

    # ── Keys, drag and drop, closing ─────────────────────────────────────────

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.KeyPress or QApplication.activeModalWidget() is not None:
            return False
        if not self.isActiveWindow():
            return False
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)) or \
                (isinstance(fw, QComboBox) and fw.isEditable()):
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self:
            return False
        key, mods = ev.key(), ev.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        K = Qt.Key
        if key == K.Key_Space:
            self.toggle_play()
        elif key == K.Key_Left:
            self.skip(-1 if shift else -5)
        elif key == K.Key_Right:
            self.skip(1 if shift else 5)
        elif key == K.Key_Comma:
            self.step_frame(-1)
        elif key == K.Key_Period:
            self.step_frame(1)
        elif key == K.Key_I:
            self.set_in()
        elif key == K.Key_O:
            self.set_out()
        elif key == K.Key_L:
            self.toggle_trim_lock()
        elif key == K.Key_Home:
            self.seek(self.project.trim_in)
        elif key == K.Key_End:
            self.seek(self.project.effective_out())
        elif key in (K.Key_Delete, K.Key_Backspace):
            self.delete_comment(self.selected_id)
        elif key in (K.Key_Return, K.Key_Enter, K.Key_N):
            self.input.setFocus()
        elif key == K.Key_Escape:
            self.select(None)
        else:
            return False
        return True

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            e.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.open_any(urls[0]))

    def closeEvent(self, e):
        if not self.confirm_discard():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.player.stop()
        e.accept()
