"""The PDF layout dialog: one page of settings in plain words, with a live preview on the right.

Fields that can hold changing information (page number, date, project …) get a ＋ button that
inserts it – nobody has to remember {page}.
"""
from __future__ import annotations

import json
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPixmap, QAction
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QWidget, QLabel, QLineEdit, QPlainTextEdit,
    QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QPushButton, QToolButton, QListWidget, QListWidgetItem,
    QScrollArea, QInputDialog, QMessageBox, QFileDialog, QColorDialog, QDialogButtonBox, QGroupBox, QMenu,
    QRadioButton, QButtonGroup, QFrame, QSizePolicy,
)

from . import pdfexport as pe

TEMPLATE_EXT = ".qrtemplate"

# What the ＋ menus offer, in plain words
INSERTS = [
    ("Page number", "{page}"), ("Number of pages", "{pages}"), ("Page 1 of 3", "Page {page} of {pages}"),
    (None, None),
    ("Project name", "{project}"), ("Video name", "{video}"), ("Original video file", "{source}"),
    (None, None),
    ("Date of the export", "{date}"), ("Time of the export", "{time}"),
    ("Trim (in – out)", "{trim}"), ("Length of the export", "{length}"), ("Number of comments", "{count}"),
    (None, None),
    ("Q-Review and version", "{app} {version}"),
]


def insert_button(target, parent) -> QToolButton:
    """A small ＋ button that inserts a placeholder at the cursor in a QLineEdit."""
    b = QToolButton(parent)
    b.setText("＋")
    b.setToolTip("Insert page number, date, project name …")
    b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    m = QMenu(b)
    for label, token in INSERTS:
        if label is None:
            m.addSeparator()
            continue
        a = QAction(label, m)
        a.triggered.connect(lambda _=False, tok=token: (target.insert(tok), target.setFocus()))
        m.addAction(a)
    b.setMenu(m)
    return b


def section(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    box = QGroupBox(title)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 16, 12, 12)
    lay.setSpacing(8)
    return box, lay


class PdfLayoutDialog(QDialog):
    """Returns the chosen (and possibly edited) template in .template after exec()."""

    def __init__(self, project, plan, video_name: str, template: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF layout")
        self.resize(1200, 820)
        self.project, self.plan, self.video_name = project, plan, video_name
        self.template = pe.normalize(template)
        self._loading = False
        self._page = 0
        self._dirty = False
        self._logo = None
        self._accent = "#1c1c1e"

        root = QVBoxLayout(self)

        # ── Templates ──
        top = QHBoxLayout()
        lab = QLabel("Template")
        lab.setStyleSheet("font-weight:600;")
        top.addWidget(lab)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        self.combo.activated.connect(self._choose)
        top.addWidget(self.combo)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save)
        top.addWidget(self.save_btn)
        b = QPushButton("Save as new …")
        b.setToolTip("Keep this layout as a template with its own name")
        b.clicked.connect(self._save_as)
        top.addWidget(b)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip("Delete, import or export templates")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        mm = QMenu(more)
        self.delete_act = mm.addAction("Delete this template")
        self.delete_act.triggered.connect(self._delete)
        mm.addSeparator()
        mm.addAction("Import a template file …").triggered.connect(self._import)
        mm.addAction("Export this template to a file …").triggered.connect(self._export)
        more.setMenu(mm)
        top.addWidget(more)
        self.state = QLabel()
        self.state.setStyleSheet("color:#ffd60a;")
        top.addWidget(self.state)
        top.addStretch()
        root.addLayout(top)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        # ── Settings (left, one scrollable page) ──
        form_host = QWidget()
        col = QVBoxLayout(form_host)
        col.setSpacing(12)

        # Top of the page
        box, lay = section("Top of the first page")
        g = QGridLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("e.g. {project}")
        self.subtitle = QLineEdit()
        self.subtitle.setPlaceholderText("e.g. Notes from the dress rehearsal")
        for r, (name, edit) in enumerate((("Title", self.title), ("Subtitle", self.subtitle))):
            g.addWidget(QLabel(name), r, 0)
            g.addWidget(edit, r, 1)
            g.addWidget(insert_button(edit, self), r, 2)
        lay.addLayout(g)
        self.note = QPlainTextEdit()
        self.note.setFixedHeight(58)
        self.note.setPlaceholderText("A note under the title (optional), e.g. Dress rehearsal 3 – Bellevue Teatret")
        lay.addWidget(self.note)
        self.info = QCheckBox("Show video, trim, date and number of comments")
        self.summary = QCheckBox("Show how many comments each role has")
        lay.addWidget(self.info)
        lay.addWidget(self.summary)
        col.addWidget(box)

        # Comments
        box, lay = section("Comments")
        order = QHBoxLayout()
        order.addWidget(QLabel("Order"))
        self.order_time = QRadioButton("One list in time order")
        self.order_role = QRadioButton("A section for each role")
        grp = QButtonGroup(self)
        grp.addButton(self.order_time)
        grp.addButton(self.order_role)
        order.addWidget(self.order_time)
        order.addWidget(self.order_role)
        order.addStretch()
        lay.addLayout(order)
        lab = QLabel("Columns – tick the ones to show, drag to change the order, double-click a name to rename it")
        lab.setWordWrap(True)
        lab.setStyleSheet("color:#9a9aa0;")
        lay.addWidget(lab)
        cols_row = QHBoxLayout()
        self.cols = QListWidget()
        self.cols.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.cols.setFixedHeight(172)
        self.cols.itemChanged.connect(lambda _i: self._changed())
        self.cols.model().rowsMoved.connect(lambda *_: self._changed())
        cols_row.addWidget(self.cols, 1)
        arrows = QVBoxLayout()
        for text, d in (("▲", -1), ("▼", 1)):
            b = QToolButton()
            b.setText(text)
            b.clicked.connect(lambda _=False, d=d: self._move_col(d))
            arrows.addWidget(b)
        arrows.addStretch()
        cols_row.addLayout(arrows)
        lay.addLayout(cols_row)
        f = QFormLayout()
        self.color_style = QComboBox()
        for label, key in (("Coloured stripe at the left", "stripe"), ("Role name in its colour", "text"),
                           ("Both stripe and coloured name", "both"), ("No colours", "none")):
            self.color_style.addItem(label, key)
        f.addRow("Role colours", self.color_style)
        acc = QHBoxLayout()
        self.accent = QPushButton()
        self.accent.setFixedWidth(110)
        self.accent.clicked.connect(self._pick_accent)
        acc.addWidget(self.accent)
        self.zebra = QCheckBox("Every other row grey")
        acc.addWidget(self.zebra)
        acc.addStretch()
        f.addRow("Heading colour", acc)
        lay.addLayout(f)
        col.addWidget(box)

        # Paper
        box, lay = section("Paper")
        row = QHBoxLayout()
        self.page_size = QComboBox()
        for k in pe.PAGE_SIZES:
            self.page_size.addItem(k, k)
        row.addWidget(self.page_size)
        self.orient = QComboBox()
        self.orient.addItem("Portrait", False)
        self.orient.addItem("Landscape", True)
        row.addWidget(self.orient)
        row.addSpacing(12)
        row.addWidget(QLabel("Text"))
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(6, 16)
        self.font_size.setSingleStep(0.5)
        self.font_size.setSuffix(" pt")
        row.addWidget(self.font_size)
        row.addWidget(QLabel("Margins"))
        self.margin = QSpinBox()
        self.margin.setRange(5, 40)
        self.margin.setSuffix(" mm")
        row.addWidget(self.margin)
        row.addStretch()
        lay.addLayout(row)
        col.addWidget(box)

        # Header and footer
        box, lay = section("Header and footer (on every page)")
        g = QGridLayout()
        g.setHorizontalSpacing(4)
        for c, name in enumerate(("Left", "Centre", "Right")):
            lab = QLabel(name)
            lab.setStyleSheet("color:#9a9aa0;")
            g.addWidget(lab, 0, 1 + c * 2)
        self.hf = {}
        for r, part in enumerate(("header", "footer"), 1):
            g.addWidget(QLabel("Header" if part == "header" else "Footer"), r, 0)
            for c, side in enumerate(("left", "center", "right")):
                e = QLineEdit()
                e.textChanged.connect(lambda _t: self._changed())
                g.addWidget(e, r, 1 + c * 2)
                g.addWidget(insert_button(e, self), r, 2 + c * 2)
                self.hf[(part, side)] = e
        lay.addLayout(g)
        quick = QHBoxLayout()
        quick.addWidget(QLabel("Quick:"))
        for text, fn in (("Page numbers in the footer", self._quick_pages),
                         ("Project and date in the header", self._quick_header),
                         ("Clear header and footer", self._quick_clear)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            quick.addWidget(b)
        quick.addStretch()
        lay.addLayout(quick)
        logo_row = QHBoxLayout()
        logo_row.addWidget(QLabel("Logo"))
        self.logo_label = QLabel("None")
        self.logo_label.setFixedSize(110, 40)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setStyleSheet("background:#2c2c2e; border:1px solid #3a3a3c; border-radius:6px; color:#8e8e93;")
        logo_row.addWidget(self.logo_label)
        b = QPushButton("Choose …")
        b.clicked.connect(self._choose_logo)
        logo_row.addWidget(b)
        self.logo_remove = QPushButton("Remove")
        self.logo_remove.clicked.connect(self._remove_logo)
        logo_row.addWidget(self.logo_remove)
        self.logo_pos = QComboBox()
        self.logo_pos.addItem("Left in the header", "left")
        self.logo_pos.addItem("Right in the header", "right")
        logo_row.addWidget(self.logo_pos)
        logo_row.addStretch()
        lay.addLayout(logo_row)
        col.addWidget(box)
        col.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(form_host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(560)
        scroll.setMaximumWidth(640)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(scroll)

        # ── Preview (right) ──
        right = QVBoxLayout()
        nav = QHBoxLayout()
        lab = QLabel("Preview")
        lab.setStyleSheet("font-weight:600;")
        nav.addWidget(lab)
        nav.addStretch()
        self.prev_btn = QToolButton()
        self.prev_btn.setText("◀")
        self.prev_btn.clicked.connect(lambda: self._go(-1))
        self.next_btn = QToolButton()
        self.next_btn.setText("▶")
        self.next_btn.clicked.connect(lambda: self._go(1))
        self.page_label = QLabel()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.page_label)
        nav.addWidget(self.next_btn)
        right.addLayout(nav)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview_label.setStyleSheet("background:#3a3a3c; border-radius:8px;")
        right.addWidget(self.preview_label, 1)
        body.addLayout(right, 1)

        bb = QDialogButtonBox()
        use = bb.addButton("Use for this export", QDialogButtonBox.ButtonRole.AcceptRole)
        use.setObjectName("primary")
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # Any change → new preview a moment later (typing stays smooth)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._render)
        for w in (self.title, self.subtitle):
            w.textChanged.connect(lambda _t: self._changed())
        self.note.textChanged.connect(self._changed)
        for cb in (self.info, self.summary, self.zebra, self.order_time, self.order_role):
            cb.toggled.connect(lambda _b: self._changed())
        for combo in (self.color_style, self.page_size, self.orient, self.logo_pos):
            combo.currentIndexChanged.connect(lambda _i: self._changed())
        self.font_size.valueChanged.connect(lambda _v: self._changed())
        self.margin.valueChanged.connect(lambda _v: self._changed())

        self._fill_combo(self.template["name"])
        self._load(self.template)
        self._dirty = self.template != pe.get_template(self.template["name"])
        self._update_state()
        QTimer.singleShot(0, self._render)

    # ── Templates ──

    def _fill_combo(self, select: str):
        self.combo.blockSignals(True)
        self.combo.clear()
        for t in pe.list_templates():
            self.combo.addItem(t["name"], t["name"])
        self.combo.setCurrentIndex(max(0, self.combo.findData(select)))
        self.combo.blockSignals(False)
        standard = self.combo.currentData() == pe.STANDARD
        self.delete_act.setEnabled(not standard)
        self.save_btn.setEnabled(not standard)
        self.save_btn.setToolTip("Standard can't be changed – use Save as new …" if standard
                                 else "Save the changes in this template")

    def _update_state(self):
        self.state.setText("changed – not saved" if self._dirty else "")
        self.setWindowTitle(f"PDF layout – {self.template['name']}{' •' if self._dirty else ''}")

    def _choose(self, _i):
        name = self.combo.currentData()
        if self._dirty and QMessageBox.question(self, "PDF layout", "Forget the changes that are not saved?") \
                != QMessageBox.StandardButton.Yes:
            self._fill_combo(self.template["name"])
            return
        self.template = pe.get_template(name)
        self._fill_combo(name)
        self._load(self.template)
        self._dirty = False
        self._page = 0
        self._update_state()
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
        self.template = t
        self._dirty = False
        self._fill_combo(t["name"])
        self._update_state()

    def _save_as(self):
        suggestion = "" if self.template["name"] == pe.STANDARD else self.template["name"] + " copy"
        name, ok = QInputDialog.getText(self, "Save as new template", "Name of the template:", text=suggestion)
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
        self._update_state()

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
        self._update_state()
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
        self._update_state()
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
        (self.order_role if t["group"] else self.order_time).setChecked(True)
        self.zebra.setChecked(t["zebra"])
        self.color_style.setCurrentIndex(max(0, self.color_style.findData(t["colorStyle"])))
        self._accent = t["accent"]
        self._style_accent()
        self.cols.clear()
        for key, on, label in t["columns"]:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
                        | Qt.ItemFlag.ItemIsDragEnabled)
            it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            original = pe.COLUMNS[key][0]
            it.setToolTip(f"Shows: {original}" + ("" if label == original else f" (heading renamed to \"{label}\")"))
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
            "info": self.info.isChecked(), "summary": self.summary.isChecked(), "group": self.order_role.isChecked(),
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
        self._update_state()
        self._timer.start()

    def _move_col(self, d):
        r = self.cols.currentRow()
        n = r + d
        if 0 <= r < self.cols.count() and 0 <= n < self.cols.count():
            it = self.cols.takeItem(r)
            self.cols.insertItem(n, it)
            self.cols.setCurrentRow(n)
            self._changed()

    # Quick choices
    def _quick_pages(self):
        self.hf[("footer", "right")].setText("Page {page} of {pages}")

    def _quick_header(self):
        self.hf[("header", "left")].setText("{project}")
        self.hf[("header", "right")].setText("{date}")

    def _quick_clear(self):
        for e in self.hf.values():
            e.clear()

    def _pick_accent(self):
        c = QColorDialog.getColor(QColor(self._accent), self, "Colour of the table heading")
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
        self.logo_remove.setEnabled(img is not None)
        self.logo_pos.setEnabled(img is not None)
        if img is None:
            self.logo_label.setPixmap(QPixmap())
            self.logo_label.setText("None")
        else:
            self.logo_label.setPixmap(QPixmap.fromImage(img).scaled(
                104, 34, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    # ── Preview ──

    def _go(self, d):
        self._page += d
        self._render()

    def _render(self):
        try:
            img, pages = pe.preview(self.project, self.plan, self.video_name, self.current(), self._page, dpi=120)
        except Exception as e:
            self.preview_label.setText(f"The preview failed:\n{e}")
            return
        self._page = max(0, min(self._page, pages - 1))
        self.page_label.setText(f"Page {self._page + 1} of {pages}")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < pages - 1)
        pm = QPixmap.fromImage(img)
        size = self.preview_label.size()
        w, h = max(200, size.width() - 24), max(200, size.height() - 24)
        self.preview_label.setPixmap(pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_timer"):
            self._timer.start()

    def accept(self):
        self.template = self.current()
        super().accept()
