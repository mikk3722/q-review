"""The PDF layout dialog: choose what the PDF shows, see it, and save it as a template."""
from __future__ import annotations

import copy
import json
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget, QLabel, QLineEdit, QPlainTextEdit,
    QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QPushButton, QListWidget, QListWidgetItem, QScrollArea,
    QInputDialog, QMessageBox, QFileDialog, QColorDialog, QGridLayout, QDialogButtonBox, QSizePolicy, QFrame,
)

from . import pdfexport as pe

TEMPLATE_EXT = ".qrtemplate"


class PdfLayoutDialog(QDialog):
    """Returns the chosen (and possibly edited) template in .template after exec()."""

    def __init__(self, project, plan, video_name: str, template: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF layout")
        self.resize(1180, 780)
        self.project, self.plan, self.video_name = project, plan, video_name
        self.template = pe.normalize(template)
        self._loading = False
        self._page = 0
        self._dirty = False

        root = QVBoxLayout(self)

        # Templates
        top = QHBoxLayout()
        top.addWidget(QLabel("Template"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(220)
        self.combo.activated.connect(self._choose)
        top.addWidget(self.combo)
        for text, tip, fn in (("Save", "Save the changes in this template", self._save),
                              ("Save as …", "Save as a new template", self._save_as),
                              ("Delete", "Delete this template", self._delete),
                              ("Import …", "Import a template file", self._import),
                              ("Export …", "Save the template as a file to share", self._export)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            top.addWidget(b)
            if text == "Save":
                self.save_btn = b
            if text == "Delete":
                self.delete_btn = b
        top.addStretch()
        root.addLayout(top)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        # Settings (left)
        tabs = QTabWidget()
        tabs.setMinimumWidth(430)
        tabs.setMaximumWidth(520)
        body.addWidget(tabs)

        # Content
        w = QWidget()
        f = QFormLayout(w)
        self.title = QLineEdit()
        self.subtitle = QLineEdit()
        self.note = QPlainTextEdit()
        self.note.setFixedHeight(70)
        self.note.setPlaceholderText("e.g. Dress rehearsal 3 – Bellevue Teatret")
        f.addRow("Title", self.title)
        f.addRow("Subtitle", self.subtitle)
        f.addRow("Note", self.note)
        self.info = QCheckBox("Info line (video, trim, date, number of comments)")
        self.summary = QCheckBox("Summary: number of comments per role")
        self.group = QCheckBox("One section per role (instead of one list in time order)")
        self.zebra = QCheckBox("Every other row grey")
        for cb in (self.info, self.summary, self.group, self.zebra):
            f.addRow("", cb)
        self.color_style = QComboBox()
        for label, key in (("Coloured stripe", "stripe"), ("Coloured role name", "text"),
                           ("Stripe and coloured name", "both"), ("No colours", "none")):
            self.color_style.addItem(label, key)
        f.addRow("Role colour", self.color_style)
        self.accent = QPushButton()
        self.accent.clicked.connect(self._pick_accent)
        f.addRow("Table heading", self.accent)
        tabs.addTab(w, "Content")

        # Columns
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel("Tick the columns to show. Drag or use ▲▼ to change the order, double-click to rename a heading.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9a9aa0;")
        v.addWidget(hint)
        self.cols = QListWidget()
        self.cols.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.cols.itemChanged.connect(lambda _i: self._changed())
        self.cols.model().rowsMoved.connect(lambda *_: self._changed())
        v.addWidget(self.cols, 1)
        row = QHBoxLayout()
        for text, d in (("▲", -1), ("▼", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, d=d: self._move_col(d))
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        tabs.addTab(w, "Columns")

        # Page
        w = QWidget()
        f = QFormLayout(w)
        self.page_size = QComboBox()
        for k in pe.PAGE_SIZES:
            self.page_size.addItem(k, k)
        f.addRow("Paper", self.page_size)
        self.orient = QComboBox()
        self.orient.addItem("Portrait", False)
        self.orient.addItem("Landscape", True)
        f.addRow("Orientation", self.orient)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(6, 16)
        self.font_size.setSingleStep(0.5)
        self.font_size.setSuffix(" pt")
        f.addRow("Text size", self.font_size)
        self.margin = QSpinBox()
        self.margin.setRange(5, 40)
        self.margin.setSuffix(" mm")
        f.addRow("Margins", self.margin)
        tabs.addTab(w, "Page")

        # Header & footer
        w = QWidget()
        g = QGridLayout(w)
        g.addWidget(QLabel(""), 0, 0)
        for c, name in enumerate(("Left", "Centre", "Right"), 1):
            lab = QLabel(name)
            lab.setStyleSheet("color:#9a9aa0;")
            g.addWidget(lab, 0, c)
        self.hf = {}
        for r, part in enumerate(("header", "footer"), 1):
            g.addWidget(QLabel("Header" if part == "header" else "Footer"), r, 0)
            for c, side in enumerate(("left", "center", "right"), 1):
                e = QLineEdit()
                e.textChanged.connect(lambda _t: self._changed())
                g.addWidget(e, r, c)
                self.hf[(part, side)] = e
        logo_row = QHBoxLayout()
        self.logo_label = QLabel("No logo")
        self.logo_label.setFixedHeight(40)
        self.logo_label.setMinimumWidth(80)
        logo_row.addWidget(self.logo_label)
        b = QPushButton("Choose logo …")
        b.clicked.connect(self._choose_logo)
        logo_row.addWidget(b)
        b = QPushButton("Remove")
        b.clicked.connect(self._remove_logo)
        logo_row.addWidget(b)
        self.logo_pos = QComboBox()
        self.logo_pos.addItem("Logo left in the header", "left")
        self.logo_pos.addItem("Logo right in the header", "right")
        logo_row.addWidget(self.logo_pos)
        logo_row.addStretch()
        g.addLayout(logo_row, 3, 0, 1, 4)
        ph = QLabel("You can use: " + " · ".join(f"<b>{k}</b> {v}" for k, v in pe.PLACEHOLDERS))
        ph.setWordWrap(True)
        ph.setTextFormat(Qt.TextFormat.RichText)
        ph.setStyleSheet("color:#9a9aa0;")
        g.addWidget(ph, 4, 0, 1, 4)
        g.setRowStretch(5, 1)
        tabs.addTab(w, "Header and footer")

        # Preview (right)
        right = QVBoxLayout()
        nav = QHBoxLayout()
        self.prev_btn = QPushButton("◀")
        self.prev_btn.clicked.connect(lambda: self._go(-1))
        self.next_btn = QPushButton("▶")
        self.next_btn.clicked.connect(lambda: self._go(1))
        self.page_label = QLabel()
        nav.addWidget(QLabel("Preview"))
        nav.addStretch()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.page_label)
        nav.addWidget(self.next_btn)
        right.addLayout(nav)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("background:#3a3a3c;")
        area = QScrollArea()
        area.setWidget(self.preview_label)
        area.setWidgetResizable(True)
        right.addWidget(area, 1)
        body.addLayout(right, 1)

        bb = QDialogButtonBox()
        use = bb.addButton("Use for this export", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # Any change → preview again (a little later, so typing stays smooth)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._render)
        for wdg in (self.title, self.subtitle):
            wdg.textChanged.connect(lambda _t: self._changed())
        self.note.textChanged.connect(self._changed)
        for cb in (self.info, self.summary, self.group, self.zebra):
            cb.toggled.connect(lambda _b: self._changed())
        for combo in (self.color_style, self.page_size, self.orient, self.logo_pos):
            combo.currentIndexChanged.connect(lambda _i: self._changed())
        self.font_size.valueChanged.connect(lambda _v: self._changed())
        self.margin.valueChanged.connect(lambda _v: self._changed())

        self._fill_combo(self.template["name"])
        self._load(self.template)
        self._dirty = False
        self._render()

    # ── Template list ──

    def _fill_combo(self, select: str):
        self.combo.blockSignals(True)
        self.combo.clear()
        for t in pe.list_templates():
            self.combo.addItem(t["name"], t["name"])
        i = self.combo.findData(select)
        self.combo.setCurrentIndex(max(0, i))
        self.combo.blockSignals(False)
        standard = self.combo.currentData() == pe.STANDARD
        self.delete_btn.setEnabled(not standard)
        self.save_btn.setEnabled(not standard)
        self.save_btn.setToolTip("Standard can't be changed – use Save as …" if standard else "Save the changes in this template")

    def _choose(self, _i):
        name = self.combo.currentData()
        if self._dirty and QMessageBox.question(self, "PDF layout", "Leave the changes that are not saved?") \
                != QMessageBox.StandardButton.Yes:
            self._fill_combo(self.template["name"])
            return
        self.template = pe.get_template(name)
        self._fill_combo(name)
        self._load(self.template)
        self._dirty = False
        self._page = 0
        self._render()

    def _save(self):
        t = self.current()
        if t["name"] == pe.STANDARD:
            return self._save_as()
        try:
            pe.save_template(t)
        except Exception as e:
            QMessageBox.warning(self, "PDF layout", str(e))
            return
        self._dirty = False
        self._fill_combo(t["name"])

    def _save_as(self):
        name, ok = QInputDialog.getText(self, "Save template", "Name of the template:",
                                        text="" if self.template["name"] == pe.STANDARD else self.template["name"] + " copy")
        name = (name or "").strip()
        if not ok or not name:
            return
        if name == pe.STANDARD:
            QMessageBox.information(self, "PDF layout", "Choose another name than Standard.")
            return
        if any(t["name"] == name for t in pe.list_templates()) and \
                QMessageBox.question(self, "PDF layout", f"\"{name}\" exists. Replace it?") != QMessageBox.StandardButton.Yes:
            return
        t = self.current()
        t["name"] = name
        try:
            pe.save_template(t)
        except Exception as e:
            QMessageBox.warning(self, "PDF layout", str(e))
            return
        self.template = t
        self._dirty = False
        self._fill_combo(name)

    def _delete(self):
        name = self.combo.currentData()
        if name == pe.STANDARD:
            return
        if QMessageBox.question(self, "PDF layout", f"Delete the template \"{name}\"?") != QMessageBox.StandardButton.Yes:
            return
        pe.delete_template(name)
        self.template = pe.normalize(None)
        self._fill_combo(pe.STANDARD)
        self._load(self.template)
        self._dirty = False
        self._render()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import template", "",
                                              f"Q-Review template (*{TEMPLATE_EXT} *.json);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                t = pe.normalize(json.load(fh))
        except Exception as e:
            QMessageBox.warning(self, "Import", f"Could not read the template:\n{e}")
            return
        if t["name"] == pe.STANDARD:
            t["name"] = os.path.splitext(os.path.basename(path))[0]
        pe.save_template(t)
        self.template = t
        self._fill_combo(t["name"])
        self._load(t)
        self._dirty = False
        self._render()

    def _export(self):
        t = self.current()
        path, _ = QFileDialog.getSaveFileName(self, "Export template", t["name"] + TEMPLATE_EXT,
                                              f"Q-Review template (*{TEMPLATE_EXT})")
        if not path:
            return
        if not path.lower().endswith(TEMPLATE_EXT):
            path += TEMPLATE_EXT
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(t, fh, indent=2, ensure_ascii=False)

    # ── Fields ↔ template ──

    def _load(self, t: dict):
        self._loading = True
        self.title.setText(t["title"])
        self.subtitle.setText(t["subtitle"])
        self.note.setPlainText(t["note"])
        self.info.setChecked(t["info"])
        self.summary.setChecked(t["summary"])
        self.group.setChecked(t["group"])
        self.zebra.setChecked(t["zebra"])
        self.color_style.setCurrentIndex(max(0, self.color_style.findData(t["colorStyle"])))
        self._accent = t["accent"]
        self._style_accent()
        self.cols.clear()
        for key, on, label in t["columns"]:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
            it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            it.setToolTip(f"Column: {pe.COLUMNS[key][0]}")
            self.cols.addItem(it)
        self.page_size.setCurrentIndex(max(0, self.page_size.findData(t["page"])))
        self.orient.setCurrentIndex(1 if t["landscape"] else 0)
        self.font_size.setValue(float(t["fontSize"]))
        self.margin.setValue(int(t["margin"]))
        for (part, side), e in self.hf.items():
            e.setText(t[part][side])
        self._logo = t.get("logo")
        self._show_logo()
        self.logo_pos.setCurrentIndex(0 if t["logoPos"] == "left" else 1)
        self._loading = False

    def current(self) -> dict:
        cols = []
        for i in range(self.cols.count()):
            it = self.cols.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            cols.append([key, it.checkState() == Qt.CheckState.Checked, it.text().strip() or pe.COLUMNS[key][0]])
        return pe.normalize({
            "name": self.template["name"],
            "title": self.title.text(), "subtitle": self.subtitle.text(), "note": self.note.toPlainText(),
            "info": self.info.isChecked(), "summary": self.summary.isChecked(), "group": self.group.isChecked(),
            "zebra": self.zebra.isChecked(), "colorStyle": self.color_style.currentData(), "accent": self._accent,
            "columns": cols, "page": self.page_size.currentData(), "landscape": bool(self.orient.currentData()),
            "fontSize": self.font_size.value(), "margin": self.margin.value(),
            "header": {s: self.hf[("header", s)].text() for s in ("left", "center", "right")},
            "footer": {s: self.hf[("footer", s)].text() for s in ("left", "center", "right")},
            "logo": self._logo, "logoPos": self.logo_pos.currentData(),
        })

    def _changed(self):
        if self._loading:
            return
        self._dirty = True
        self._timer.start()

    def _move_col(self, d):
        r = self.cols.currentRow()
        n = r + d
        if 0 <= r < self.cols.count() and 0 <= n < self.cols.count():
            it = self.cols.takeItem(r)
            self.cols.insertItem(n, it)
            self.cols.setCurrentRow(n)
            self._changed()

    def _pick_accent(self):
        c = QColorDialog.getColor(QColor(self._accent), self, "Table heading colour")
        if c.isValid():
            self._accent = c.name()
            self._style_accent()
            self._changed()

    def _style_accent(self):
        c = QColor(self._accent)
        self.accent.setText(self._accent.upper())
        self.accent.setStyleSheet(f"background:{c.name()}; color:{'#000' if c.lightness() > 140 else '#fff'};")

    def _choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose logo", "", "Images (*.png *.jpg *.jpeg *.svg *.bmp *.gif)")
        if not path:
            return
        data = pe.logo_from_file(path)
        if not data:
            QMessageBox.warning(self, "Logo", "The image could not be read.")
            return
        self._logo = data
        self._show_logo()
        self._changed()

    def _remove_logo(self):
        self._logo = None
        self._show_logo()
        self._changed()

    def _show_logo(self):
        img = pe._logo_image({"logo": self._logo})
        if img is None:
            self.logo_label.setPixmap(QPixmap())
            self.logo_label.setText("No logo")
        else:
            self.logo_label.setPixmap(QPixmap.fromImage(img).scaledToHeight(36, Qt.TransformationMode.SmoothTransformation))

    # ── Preview ──

    def _go(self, d):
        self._page += d
        self._render()

    def _render(self):
        try:
            img, pages = pe.preview(self.project, self.plan, self.video_name, self.current(), self._page)
        except Exception as e:
            self.preview_label.setText(f"Preview failed: {e}")
            return
        self._page = max(0, min(self._page, pages - 1))
        self.page_label.setText(f"Page {self._page + 1} of {pages}")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < pages - 1)
        pm = QPixmap.fromImage(img)
        avail = max(300, self.preview_label.parentWidget().height() - 20) if self.preview_label.parentWidget() else 700
        self.preview_label.setPixmap(pm.scaledToHeight(min(avail, pm.height()), Qt.TransformationMode.SmoothTransformation))
        star = " •" if self._dirty else ""
        self.setWindowTitle(f"PDF layout – {self.template['name']}{star}")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_timer"):
            self._timer.start()

    def accept(self):
        self.template = self.current()
        super().accept()
