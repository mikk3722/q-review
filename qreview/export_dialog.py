"""The Export dialog: choose what to export, then run FFmpeg with a progress bar."""
from __future__ import annotations

import os
import shutil
import tempfile

from PyQt6.QtCore import Qt, QProcess, QSettings, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox, QRadioButton, QComboBox, QLineEdit, QPushButton,
    QLabel, QProgressBar, QFileDialog, QMessageBox, QFormLayout, QButtonGroup, QDialogButtonBox,
)

from .model import fmt_precise
from . import exporter, media


class ExportDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Export")
        self.setMinimumWidth(560)
        self.proc: QProcess | None = None
        self.work: str | None = None
        self.settings = QSettings()
        s = self.settings

        lay = QVBoxLayout(self)

        # Where
        where = QGroupBox("Save as")
        f = QFormLayout(where)
        row = QHBoxLayout()
        default_folder = os.path.dirname(project.path or project.video_path or os.path.expanduser("~"))
        self.folder = QLineEdit(default_folder)
        row.addWidget(self.folder, 1)
        browse = QPushButton("Choose …")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        f.addRow("Folder", row)
        src = os.path.splitext(os.path.basename(project.video_path or "Export"))[0]
        self.name = QLineEdit(f"{src} – review")
        f.addRow("Name", self.name)
        self.own_folder = QCheckBox("Put everything in a new folder with this name")
        self.own_folder.setChecked(s.value("export/ownFolder", True, bool))
        f.addRow("", self.own_folder)
        lay.addWidget(where)

        # The trim is always used: the export is from the in-point to the out-point
        length = project.effective_out() - project.trim_in
        trim = QLabel(
            f"Trimmed: {fmt_precise(project.trim_in)} – {fmt_precise(project.effective_out())}  ({fmt_precise(length)})"
            if project.is_trimmed() else f"Whole video ({fmt_precise(project.video_duration)})")
        trim.setStyleSheet("color:#ffd60a;" if project.is_trimmed() else "color:#9a9aa0;")
        trim.setToolTip("The export always follows the in- and out-point. Timecodes start at 00:00:00 at the in-point.")
        lay.addWidget(trim)

        # Video
        vid = QGroupBox("Video (MP4, H.264)")
        vid.setCheckable(True)
        vid.setChecked(True)
        self.video_box = vid
        v = QVBoxLayout(vid)
        self.mode_group = QButtonGroup(self)
        self.burn = QRadioButton("Comments burned into the picture (as you see them)")
        self.subs = QRadioButton("Comments as a subtitle track (can be switched on/off in the player)")
        self.none = QRadioButton("No comments in the video")
        for i, b in enumerate((self.burn, self.subs, self.none)):
            self.mode_group.addButton(b, i)
            v.addWidget(b)
        mode = s.value("export/mode", "burn")
        {"burn": self.burn, "subs": self.subs, "none": self.none}.get(mode, self.burn).setChecked(True)
        if not project.overlay_enabled:
            self.burn.setText(self.burn.text() + " – comments on video is switched off")
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Quality"))
        self.quality = QComboBox()
        for label, crf in (("High (large file)", 18), ("Normal", 21), ("Small file", 26)):
            self.quality.addItem(label, crf)
        self.quality.setCurrentIndex(int(s.value("export/quality", 1)))
        opts.addWidget(self.quality)
        opts.addSpacing(16)
        opts.addWidget(QLabel("Size"))
        self.size = QComboBox()
        w, h = project.video_size
        self.size.addItem(f"Original ({w}×{h})", 0)
        for mh in (1080, 720, 540):
            if h > mh:
                self.size.addItem(f"{mh}p", mh)
        self.size.setCurrentIndex(min(int(s.value("export/size", 0)), self.size.count() - 1))
        opts.addWidget(self.size)
        opts.addStretch()
        v.addLayout(opts)
        lay.addWidget(vid)

        # Comments
        com = QGroupBox("Comments with timecodes")
        c = QVBoxLayout(com)
        files = QHBoxLayout()
        self.pdf = QCheckBox("PDF (.pdf)")
        self.pdf.setToolTip("Time, role (with its colour) and comment – ready to print or send")
        self.srt = QCheckBox("Subtitles (.srt)")
        self.csv = QCheckBox("Excel (.csv)")
        self.json = QCheckBox("Q-Recorder log (.json)")
        # Default: PDF and video only
        for cb, default in ((self.pdf, True), (self.srt, False), (self.csv, False), (self.json, False)):
            cb.setChecked(default)
            files.addWidget(cb)
        c.addLayout(files)
        # PDF layout: template + editor
        lay_row = QHBoxLayout()
        lay_row.addWidget(QLabel("PDF layout"))
        self.pdf_combo = QComboBox()
        self.pdf_combo.setMinimumWidth(200)
        self.pdf_combo.activated.connect(self._pdf_template_chosen)
        lay_row.addWidget(self.pdf_combo)
        edit = QPushButton("Edit layout …")
        edit.setToolTip("Choose columns, colours, header, footer and logo – and save it as a template")
        edit.clicked.connect(self._edit_pdf_layout)
        lay_row.addWidget(edit)
        lay_row.addStretch()
        c.addLayout(lay_row)
        self.pdf.toggled.connect(lambda on: (self.pdf_combo.setEnabled(on), edit.setEnabled(on)))
        self._load_pdf_template()
        self.json.setToolTip("Same layout as Q-Recorder's log – Q-Recorder's Play mode can open the exported video with it.")
        self.only_video = QCheckBox("Only comments marked \"Show on video\"")
        self.only_video.setChecked(s.value("export/onlyVideo", False, bool))
        c.addWidget(self.only_video)
        lay.addWidget(com)

        self.count = QLabel()
        self.count.setStyleSheet("color:#9a9aa0;")
        lay.addWidget(self.count)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.buttons = QDialogButtonBox()
        self.export_btn = self.buttons.addButton("Export", QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_btn = self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.export_btn.clicked.connect(self.start)
        self.cancel_btn.clicked.connect(self.cancel)
        lay.addWidget(self.buttons)

        self.only_video.toggled.connect(self._update)
        self._update()

    def _update(self):
        opts = self.options()
        n = len(exporter.plan(self.project, opts).items)
        self.count.setText(f"{n} comment(s) will be exported.")

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Export to", self.folder.text())
        if d:
            self.folder.setText(d)

    def options(self) -> exporter.ExportOptions:
        mode = {0: "burn", 1: "subs", 2: "none"}[max(0, self.mode_group.checkedId())]
        return exporter.ExportOptions(
            folder=self.folder.text().strip(), basename=self.name.text().strip() or "Export",
            use_trim=True, relative_times=True,
            pdf=self.pdf.isChecked(), txt=False, srt=self.srt.isChecked(), csv=self.csv.isChecked(), json=self.json.isChecked(),
            video=self.video_box.isChecked(), comment_mode=mode, crf=int(self.quality.currentData()),
            max_height=int(self.size.currentData() or 0), only_on_video=self.only_video.isChecked(),
            pdf_template=self.pdf_template)

    # ── PDF template ──

    def _load_pdf_template(self):
        """The layout used last time (also with changes that were not saved as a template)."""
        from . import pdfexport as pe
        import json
        t = None
        raw = self.settings.value("export/pdfTemplateJson", "")
        if raw:
            try:
                t = pe.normalize(json.loads(raw))
            except Exception:
                t = None
        self.pdf_template = t or pe.normalize(None)
        self._fill_pdf_combo()

    def _fill_pdf_combo(self):
        from . import pdfexport as pe
        self.pdf_combo.blockSignals(True)
        self.pdf_combo.clear()
        names = [t["name"] for t in pe.list_templates()]
        for n in names:
            self.pdf_combo.addItem(n, n)
        cur = self.pdf_template["name"]
        saved = pe.get_template(cur) if cur in names else None
        if saved is not None and saved != self.pdf_template:
            self.pdf_combo.addItem(f"{cur} (changed)", "__current__")
            self.pdf_combo.setCurrentIndex(self.pdf_combo.count() - 1)
        else:
            self.pdf_combo.setCurrentIndex(max(0, self.pdf_combo.findData(cur)))
        self.pdf_combo.blockSignals(False)

    def _pdf_template_chosen(self, _i):
        from . import pdfexport as pe
        name = self.pdf_combo.currentData()
        if name != "__current__":
            self.pdf_template = pe.get_template(name)
            self._fill_pdf_combo()

    def _edit_pdf_layout(self):
        from .pdf_dialog import PdfLayoutDialog
        o = self.options()
        p = exporter.plan(self.project, o)
        video_name = (o.basename + ".mp4") if o.video else os.path.basename(self.project.video_path or "")
        dlg = PdfLayoutDialog(self.project, p, video_name, self.pdf_template, self)
        if dlg.exec():
            self.pdf_template = dlg.template
        self._fill_pdf_combo()

    def _remember(self, o):
        import json
        self.settings.setValue("export/pdfTemplateJson", json.dumps(o.pdf_template or {}, ensure_ascii=False))
        s = self.settings
        s.setValue("export/folder", o.folder)
        s.setValue("export/mode", o.comment_mode)
        s.setValue("export/quality", self.quality.currentIndex())
        s.setValue("export/size", self.size.currentIndex())
        s.setValue("export/onlyVideo", o.only_on_video)

    # ── Running ──

    def start(self):
        o = self.options()
        if not os.path.isdir(o.folder):
            QMessageBox.warning(self, "Export", "The folder does not exist.")
            return
        if not (o.video or o.pdf or o.srt or o.csv or o.json):
            QMessageBox.information(self, "Export", "Choose at least one thing to export.")
            return
        if o.video and not (self.project.video_path and os.path.exists(self.project.video_path)):
            QMessageBox.warning(self, "Export", "The video file was not found.")
            return
        if o.video and not media.ffmpeg_path():
            QMessageBox.warning(self, "Export", "FFmpeg was not found, so the video cannot be exported.")
            return
        self._remember(o)
        self.settings.setValue("export/ownFolder", self.own_folder.isChecked())
        clean = "".join(ch for ch in o.basename if ch not in '<>:"/\\|?*').strip() or "Export"
        exts = [".pdf", ".txt", ".srt", ".csv", ".json"] + ([".mp4"] if o.video else [])
        own = self.own_folder.isChecked()

        # Does an export with this name exist already? Then ask.
        if own:
            target = os.path.join(o.folder, clean)
            exists = os.path.isdir(target) and bool(os.listdir(target))
            what = f"The folder \"{clean}\" already exists in\n{o.folder}"
        else:
            found = [clean + e for e in exts if os.path.exists(os.path.join(o.folder, clean + e))]
            exists = bool(found)
            what = "These files already exist:\n" + "\n".join(found)
        overwrite = False
        if exists:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Export")
            box.setText("An export with this name already exists.")
            box.setInformativeText(what + "\n\nReplace it, or keep both (the new one gets a number)?")
            replace = box.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
            keep = box.addButton("Keep both", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(keep)
            box.exec()
            if box.clickedButton() == replace:
                overwrite = True
            elif box.clickedButton() != keep:
                self.name.setFocus()
                self.name.selectAll()
                return

        if own:
            folder, n = os.path.join(o.folder, clean), 2
            if not overwrite:
                while os.path.exists(folder) and os.listdir(folder):
                    folder, n = os.path.join(o.folder, f"{clean} {n}"), n + 1
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                QMessageBox.warning(self, "Export", f"Could not make the folder:\n{e}")
                return
            o.folder = folder
        self.export_folder = o.folder
        base = clean if overwrite else exporter.unique_base(o.folder, clean, exts)
        self.out_files = []
        video_name = base + ".mp4" if o.video else os.path.basename(self.project.video_path or "")
        try:
            self.out_files += exporter.write_text_files(self.project, o, base, video_name)
        except Exception as e:
            QMessageBox.warning(self, "Export", f"Could not write the comment files:\n{e}")
            return
        if not o.video:
            self._done(True, "")
            return

        self.work = tempfile.mkdtemp(prefix="qreview-export-")
        self.status.setText("Preparing the comments …")
        self.repaint()
        out = os.path.join(o.folder, base + ".mp4")
        self.video_final = out
        part = os.path.join(o.folder, base + ".partial.mp4")   # the old video stays until the new one is done
        try:
            cmd, self.length = exporter.build_video_command(self.project, o, part, self.work)
        except Exception as e:
            self._cleanup()
            QMessageBox.warning(self, "Export", f"Could not prepare the export:\n{e}")
            return
        self.video_out = part
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(self.work)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._progress)
        self.proc.finished.connect(self._finished)
        self.errors = ""
        self.proc.readyReadStandardError.connect(self._stderr)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.export_btn.setEnabled(False)
        self.video_box.setEnabled(False)
        self.status.setText("Exporting the video …")
        self.proc.start(cmd[0], cmd[1:])

    def _stderr(self):
        self.errors += bytes(self.proc.readAllStandardError()).decode("utf-8", "replace")
        self.errors = self.errors[-4000:]

    def _progress(self):
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in data.splitlines():
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                frac = max(0.0, min(1.0, us / 1e6 / max(0.04, self.length)))
                self.progress.setValue(int(frac * 1000))
                self.status.setText(f"Exporting the video … {int(frac * 100)} %")

    def _finished(self, code, _status):
        ok = code == 0 and os.path.exists(self.video_out)
        self.proc = None
        if ok:
            try:
                os.replace(self.video_out, self.video_final)
                self.video_out = self.video_final
            except OSError as e:
                ok = False
                self.errors += f"\nCould not put the video in place: {e}"
        if ok:
            self.out_files.insert(0, self.video_out)
        self._done(ok, self.errors)

    def _done(self, ok: bool, errors: str):
        self._cleanup()
        self.progress.setVisible(False)
        self.export_btn.setEnabled(True)
        if ok:
            names = "\n".join(os.path.basename(f) for f in self.out_files)
            box = QMessageBox(self)
            box.setWindowTitle("Export")
            box.setText("The export is done.")
            box.setInformativeText(names)
            show = box.addButton("Show folder", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Ok)
            box.exec()
            if box.clickedButton() == show:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.export_folder))
            self.accept()
        else:
            try:
                if os.path.exists(self.video_out):
                    os.remove(self.video_out)
            except Exception:
                pass
            self.video_box.setEnabled(True)
            self.status.setText("")
            QMessageBox.warning(self, "Export", "The video export failed.\n\n" + (errors.strip()[-1500:] or "Unknown error"))

    def cancel(self):
        if self.proc:
            if QMessageBox.question(self, "Export", "Stop the export?") != QMessageBox.StandardButton.Yes:
                return
            self.proc.finished.disconnect()
            self.proc.kill()
            self.proc.waitForFinished(3000)
            self.proc = None
            try:
                os.remove(self.video_out)
            except Exception:
                pass
            self._cleanup()
        self.reject()

    def closeEvent(self, e):
        if self.proc:
            e.ignore()
            self.cancel()
        else:
            super().closeEvent(e)

    def _cleanup(self):
        if self.work:
            shutil.rmtree(self.work, ignore_errors=True)
            self.work = None


def run_export_blocking(project, opts: exporter.ExportOptions) -> list[str]:
    """Used by the self-test: the same export without a dialog."""
    import subprocess
    exts = [".pdf", ".txt", ".srt", ".csv", ".json", ".mp4"]
    base = exporter.unique_base(opts.folder, opts.basename, exts)
    out_files = exporter.write_text_files(project, opts, base, base + ".mp4")
    if opts.video:
        work = tempfile.mkdtemp(prefix="qreview-export-")
        out = os.path.join(opts.folder, base + ".mp4")
        cmd, _ = exporter.build_video_command(project, opts, out, work)
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, creationflags=media.CREATE_FLAGS)
        shutil.rmtree(work, ignore_errors=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-2000:])
        out_files.insert(0, out)
    return out_files
