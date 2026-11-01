"""PDF export with templates: columns, grouping, colours, page setup, header/footer and logo.

A template is a plain dict (saved as JSON). The same code draws the PDF and the preview in the
layout dialog, so the preview shows exactly what will be exported.
"""
from __future__ import annotations

import base64
import copy
import html
import json
import os
import re
from datetime import datetime

from PyQt6.QtCore import Qt, QMarginsF, QRectF, QSizeF, QByteArray, QStandardPaths
from PyQt6.QtGui import (QPdfWriter, QPageSize, QPageLayout, QTextDocument, QFont, QFontMetricsF, QColor,
                         QPainter, QImage, QAbstractTextDocumentLayout, QPen)

from .model import Project, APP_NAME, fmt_precise
from . import __version__

STANDARD = "Standard"

# key → (default heading, width in % of the table)
COLUMNS = {
    "start": ("Time", 12),
    "end": ("End", 12),
    "duration": ("Length", 8),
    "role": ("Role", 16),
    "author": ("Author", 12),
    "comment": ("Comment", 0),       # takes what is left
    "onvideo": ("On video", 8),
}

PAGE_SIZES = {"A4": QPageSize.PageSizeId.A4, "A3": QPageSize.PageSizeId.A3, "Letter": QPageSize.PageSizeId.Letter}

PLACEHOLDERS = [
    ("{project}", "project name"), ("{video}", "exported video"), ("{source}", "original video"),
    ("{date}", "export date"), ("{time}", "export time"), ("{count}", "number of comments"),
    ("{trim}", "in – out"), ("{length}", "length of the export"),
    ("{page}", "page number"), ("{pages}", "number of pages"),
    ("{app}", "Q-Review"), ("{version}", "version"),
]

DEFAULT = {
    "name": STANDARD,
    "page": "A4",
    "landscape": False,
    "fontSize": 10.0,
    "margin": 15,
    "title": "{video}",
    "subtitle": "",
    "note": "",
    "info": True,
    "summary": False,
    "group": False,                 # one section per role instead of one long list
    "colorStyle": "stripe",         # stripe | text | both | none
    "zebra": True,
    "accent": "#1c1c1e",            # table heading background
    "columns": [["start", True, "Time"], ["end", True, "End"], ["duration", False, "Length"],
                ["role", True, "Role"], ["author", False, "Author"], ["comment", True, "Comment"],
                ["onvideo", False, "On video"]],
    "header": {"left": "", "center": "", "right": ""},
    "footer": {"left": "{app} {version}", "center": "", "right": "Page {page} of {pages}"},
    "logo": None,                   # PNG as base64
    "logoPos": "right",             # left | right
}


def normalize(t: dict | None) -> dict:
    """A complete template – missing keys (older or hand-edited files) get the defaults."""
    out = copy.deepcopy(DEFAULT)
    if not isinstance(t, dict):
        return out
    for k, v in t.items():
        if k in ("header", "footer") and isinstance(v, dict):
            out[k].update({kk: str(vv) for kk, vv in v.items() if kk in ("left", "center", "right")})
        elif k == "columns" and isinstance(v, list):
            cols, seen = [], set()
            for c in v:
                if isinstance(c, (list, tuple)) and c and c[0] in COLUMNS and c[0] not in seen:
                    label = str(c[2]) if len(c) > 2 and c[2] else COLUMNS[c[0]][0]
                    cols.append([c[0], bool(c[1]) if len(c) > 1 else True, label])
                    seen.add(c[0])
            for key, (label, _w) in COLUMNS.items():
                if key not in seen:
                    cols.append([key, False, label])
            out["columns"] = cols
        elif k in out:
            out[k] = v
    if out["page"] not in PAGE_SIZES:
        out["page"] = "A4"
    if out["colorStyle"] not in ("stripe", "text", "both", "none"):
        out["colorStyle"] = "stripe"
    try:
        out["fontSize"] = min(16.0, max(6.0, float(out["fontSize"])))
        out["margin"] = min(40, max(5, int(out["margin"])))
    except (TypeError, ValueError):
        out["fontSize"], out["margin"] = 10.0, 15
    return out


# ── Stored templates ──────────────────────────────────────────────────────────

def templates_dir() -> str:
    d = os.environ.get("QREVIEW_TEMPLATE_DIR")
    if not d:
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation) \
            or os.path.join(os.path.expanduser("~"), ".q-review")
        d = os.path.join(base, "pdf-templates")
    os.makedirs(d, exist_ok=True)
    return d


def _file_for(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "Template"
    return os.path.join(templates_dir(), safe + ".json")


def list_templates() -> list[dict]:
    """Standard first, then the saved ones by name."""
    out = [normalize(None)]
    try:
        names = sorted(os.listdir(templates_dir()), key=str.lower)
    except OSError:
        names = []
    for n in names:
        if n.lower().endswith(".json"):
            try:
                with open(os.path.join(templates_dir(), n), encoding="utf-8") as f:
                    t = normalize(json.load(f))
                if t["name"] != STANDARD:
                    out.append(t)
            except Exception:
                pass
    return out


def get_template(name: str | None) -> dict:
    for t in list_templates():
        if t["name"] == name:
            return t
    return normalize(None)


def save_template(t: dict):
    t = normalize(t)
    if t["name"] == STANDARD:
        raise ValueError("The Standard template can't be changed – save it under another name.")
    tmp = _file_for(t["name"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(t, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _file_for(t["name"]))


def delete_template(name: str):
    if name != STANDARD:
        try:
            os.remove(_file_for(name))
        except OSError:
            pass


def logo_from_file(path: str, max_px: int = 600) -> str | None:
    """A logo file as base64 PNG (scaled down), so the template is self-contained."""
    img = QImage(path)
    if img.isNull():
        return None
    if img.width() > max_px or img.height() > max_px:
        img = img.scaled(max_px, max_px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    from PyQt6.QtCore import QBuffer, QIODevice
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return base64.b64encode(bytes(ba)).decode("ascii")


def _logo_image(t: dict) -> QImage | None:
    if not t.get("logo"):
        return None
    img = QImage()
    try:
        img.loadFromData(base64.b64decode(t["logo"]))
    except Exception:
        return None
    return None if img.isNull() else img


# ── Content ───────────────────────────────────────────────────────────────────

class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fill(text: str, ctx: dict) -> str:
    try:
        return (text or "").format_map(_Safe(ctx))
    except (ValueError, IndexError):
        return text or ""


def context(project: Project, plan, video_name: str) -> dict:
    now = datetime.now()
    length = max(0.0, plan.window_end - plan.window_start)
    return {
        "project": os.path.splitext(os.path.basename(project.path or project.video_path or "Untitled"))[0],
        "video": os.path.splitext(video_name)[0],
        "source": os.path.basename(project.video_path or ""),
        "date": now.strftime("%d-%m-%Y"),
        "time": now.strftime("%H:%M"),
        "count": str(len(plan.items)),
        "trim": f"{fmt_precise(plan.window_start)} – {fmt_precise(plan.window_end)}",
        "length": fmt_precise(length),
        "app": APP_NAME,
        "version": __version__,
        "page": "{page}", "pages": "{pages}",   # filled per page
    }


def _esc(t: str) -> str:
    return html.escape(t or "").replace("\n", "<br>")


def _readable(hex_color: str) -> str:
    c = QColor(hex_color)
    while c.lightness() > 120:
        c = c.darker(125)
    return c.name()


def _nobreak(s: str) -> str:
    """Short cells and headings never break over two lines: non-breaking spaces and hyphens."""
    return s.replace(" ", "&nbsp;").replace("-", "&#8209;")


def _column_widths(project, items, cols, t, dpi: float, page_width: float) -> dict:
    """The width each short column needs (widest heading or value), the same in every table of the PDF.

    Measured on an image with the same resolution (font metrics straight from a PDF writer are not reliable
    on every platform), and together never more than 60 % of the page, so the comment always has room."""
    device = QImage(4, 4, QImage.Format.Format_RGB32)
    dpm = int(round(dpi / 0.0254))
    device.setDotsPerMeterX(dpm)
    device.setDotsPerMeterY(dpm)
    base = QFont()
    base.setPointSizeF(t["fontSize"])
    bold = QFont(base)
    bold.setBold(True)
    mono = QFont(base)
    mono.setFamilies(["Menlo", "Consolas", "Courier New"])
    mono.setStyleHint(QFont.StyleHint.Monospace)
    fm = {"base": QFontMetricsF(base, device), "bold": QFontMetricsF(bold, device), "mono": QFontMetricsF(mono, device)}
    pad = dpi * 0.12                                # cell padding + air (about 3 mm)
    widths = {}
    for key, _on, label in cols:
        if key == "comment":
            continue
        w = fm["bold"].horizontalAdvance(label)
        for tc in items:
            c = tc.comment
            if key == "start":
                w = max(w, fm["mono"].horizontalAdvance(fmt_precise(tc.start)))
            elif key == "end":
                w = max(w, fm["mono"].horizontalAdvance(fmt_precise(tc.end)))
            elif key == "duration":
                w = max(w, fm["mono"].horizontalAdvance(f"{tc.end - tc.start:.1f} s"))
            elif key == "role":
                prof = project.profile(c.profile_id)
                w = max(w, fm["bold"].horizontalAdvance(prof.name if prof else ""))
            elif key == "author":
                w = max(w, fm["base"].horizontalAdvance(c.author or ""))
            elif key == "onvideo":
                w = max(w, fm["base"].horizontalAdvance("✓"))
        # +15 %: text in the PDF is set a little wider than on screen
        widths[key] = w * 1.15 + pad
    limit = page_width * 0.6
    total = sum(widths.values())
    if total > limit > 0:
        widths = {k: v * limit / total for k, v in widths.items()}
    # As a percentage of the page: pixel widths are read differently by the PDF writer on Windows and macOS
    return {k: round(v / page_width * 100, 2) for k, v in widths.items()}


def build_html(project: Project, plan, video_name: str, t: dict, ctx: dict, dpi: float = 300,
               page_width: float = 0) -> str:
    cs = t["colorStyle"]
    stripe = cs in ("stripe", "both")
    colored = cs in ("text", "both")
    cols = [c for c in t["columns"] if c[1]]
    if t["group"]:
        cols = [c for c in cols if c[0] != "role"]
    if not cols:
        cols = [["comment", True, "Comment"]]
    has_comment = any(c[0] == "comment" for c in cols)
    accent = QColor(t.get("accent") or "#1c1c1e")
    widths = _column_widths(project, plan.items, cols, t, dpi, page_width) \
        if page_width > 0 and any(c[0] == "comment" for c in cols) else {}
    head_text = "#ffffff" if accent.lightness() < 140 else "#000000"

    def cell(key, tc):
        c = tc.comment
        prof = project.profile(c.profile_id)
        mono = "font-family:Menlo,Consolas,'Courier New',monospace;"
        if key == "start":
            return f"<span style=\"{mono}\">{fmt_precise(tc.start)}</span>"
        if key == "end":
            return f"<span style=\"{mono} color:#666666;\">{fmt_precise(tc.end)}</span>"
        if key == "duration":
            return f"<span style=\"{mono}\">{tc.end - tc.start:.1f}&nbsp;s</span>"
        if key == "role":
            name = _nobreak(_esc(prof.name if prof else ""))
            color = _readable(project.color(c)) if colored else "#1c1c1e"
            return f"<b style='color:{color};'>{name}</b>"
        if key == "author":
            return _nobreak(_esc(c.author))
        if key == "comment":
            return _esc(c.text)
        if key == "onvideo":
            return "✓" if c.on_video else "–"
        return ""

    def table(items) -> str:
        head = ["<table width='100%' cellspacing='0' cellpadding='5' border='0'>", f"<thead><tr bgcolor='{accent.name()}'>"]
        if stripe:
            head.append("<th width='0.8%'></th>")
        for key, _on, label in cols:
            # Only the comment may wrap; the other columns get exactly the width their content needs
            text = _esc(label) if key == "comment" else _nobreak(_esc(label))
            width = f" width='{widths[key]}%'" if key in widths else ""
            head.append(f"<th align='left'{width} style='color:{head_text};'>{text}</th>")
        head.append("</tr></thead>")
        rows = []
        for i, tc in enumerate(items):
            bg = "#f4f4f6" if t["zebra"] and i % 2 else "#ffffff"
            r = [f"<tr bgcolor='{bg}'>"]
            if stripe:
                r.append(f"<td bgcolor='{project.color(tc.comment)}'></td>")
            for key, _on, _label in cols:
                r.append(f"<td valign='top'>{cell(key, tc)}</td>")
            r.append("</tr>")
            rows.append("".join(r))
        if not rows:
            rows.append(f"<tr><td colspan='{len(cols) + (1 if stripe else 0)}' style='color:#777777;'>No comments.</td></tr>")
        return "".join(head) + "".join(rows) + "</table>"

    parts = ["<html><body style='color:#1c1c1e;'>"]
    title = fill(t["title"], ctx)
    if title:
        parts.append(f"<p style='font-size:170%; font-weight:bold; margin:0;'>{_esc(title)}</p>")
    sub = fill(t["subtitle"], ctx)
    if sub:
        parts.append(f"<p style='font-size:120%; color:#444444; margin:2px 0 0 0;'>{_esc(sub)}</p>")
    if t["info"]:
        info = [f"Video: {_esc(video_name)}"]
        if ctx["source"] and ctx["source"] != video_name:
            info.append(f"Source: {_esc(ctx['source'])}")
        if project.is_trimmed():
            info.append(f"Trim: {ctx['trim']}")
        info.append(f"Exported {ctx['date']} {ctx['time']}")
        info.append(f"{ctx['count']} comment(s)")
        note = "<br>Times are from the start of the exported (trimmed) video." if plan.shift else ""
        parts.append(f"<p style='color:#666666; font-size:85%; margin:6px 0 0 0;'>{' &nbsp;·&nbsp; '.join(info)}{note}</p>")
    note = fill(t["note"], ctx)
    if note:
        parts.append(f"<p style='margin:10px 0 0 0;'>{_esc(note)}</p>")
    if t["summary"]:
        counts = []
        for prof in project.profiles:
            n = sum(1 for tc in plan.items if tc.comment.profile_id == prof.id)
            if n:
                counts.append(f"<span style='color:{prof.color};'>■</span>&nbsp;{_esc(prof.name)}: <b>{n}</b>")
        if counts:
            parts.append(f"<p style='margin:10px 0 0 0;'>{' &nbsp;&nbsp; '.join(counts)}</p>")
    parts.append("<p style='margin:0; font-size:50%;'>&nbsp;</p>")
    if t["group"]:
        for prof in project.profiles:
            items = [tc for tc in plan.items if tc.comment.profile_id == prof.id]
            if not items:
                continue
            color = _readable(prof.color) if colored or not stripe else "#1c1c1e"
            parts.append(f"<p style='font-size:125%; font-weight:bold; margin:14px 0 4px 0;'>"
                         f"<span style='color:{prof.color};'>■</span>&nbsp;<span style='color:{color};'>{_esc(prof.name)}</span>"
                         f"<span style='color:#888888; font-weight:normal;'> &nbsp;({len(items)})</span></p>")
            parts.append(table(items))
    else:
        parts.append(table(plan.items))
    parts.append("</body></html>")
    return "".join(parts)


# ── Drawing pages ─────────────────────────────────────────────────────────────

class _Pages:
    """Lays out the content for one paint device and draws page by page."""

    def __init__(self, project, plan, video_name, t, device, width, height):
        self.t = t
        self.ctx = context(project, plan, video_name)
        self.W, self.H = width, height
        self.hf_font = QFont()
        self.hf_font.setPointSizeF(max(6.0, t["fontSize"] * 0.8))
        fm = QFontMetricsF(self.hf_font, device)
        self.line = fm.height()
        self.logo = _logo_image(t)
        self.logo_h = self.line * 2.4 if self.logo is not None else 0
        has_header = any(t["header"].values()) or self.logo is not None
        has_footer = any(t["footer"].values())
        self.hh = (max(self.line, self.logo_h) + self.line * 0.9) if has_header else 0
        self.fh = (self.line * 1.9) if has_footer else 0
        self.ch = max(10.0, self.H - self.hh - self.fh)
        self.doc = QTextDocument()
        self.doc.documentLayout().setPaintDevice(device)
        f = QFont()
        f.setPointSizeF(t["fontSize"])
        self.doc.setDefaultFont(f)
        self.doc.setDocumentMargin(0)
        self.doc.setPageSize(QSizeF(self.W, self.ch))
        self.doc.setHtml(build_html(project, plan, video_name, t, self.ctx, device.logicalDpiX(), self.W))
        self.pages = max(1, self.doc.pageCount())

    def draw(self, painter: QPainter, i: int):
        t, W, H = self.t, self.W, self.H
        ctx = dict(self.ctx, page=str(i + 1), pages=str(self.pages))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setFont(self.hf_font)
        painter.setPen(QColor("#555555"))
        flags_v = Qt.AlignmentFlag.AlignVCenter

        # Header
        if self.hh:
            band = QRectF(0, 0, W, self.hh - self.line * 0.6)
            left_x, right_x = 0.0, W
            if self.logo is not None:
                lw = self.logo.width() * self.logo_h / max(1, self.logo.height())
                y = (band.height() - self.logo_h) / 2
                if t["logoPos"] == "left":
                    painter.drawImage(QRectF(0, y, lw, self.logo_h), self.logo)
                    left_x = lw + self.line
                else:
                    painter.drawImage(QRectF(W - lw, y, lw, self.logo_h), self.logo)
                    right_x = W - lw - self.line
            painter.drawText(QRectF(left_x, band.top(), max(0, right_x - left_x), band.height()),
                             (Qt.AlignmentFlag.AlignLeft | flags_v), fill(t["header"]["left"], ctx))
            painter.drawText(QRectF(0, band.top(), W, band.height()), (Qt.AlignmentFlag.AlignHCenter | flags_v),
                             fill(t["header"]["center"], ctx))
            painter.drawText(QRectF(left_x, band.top(), max(0, right_x - left_x), band.height()),
                             (Qt.AlignmentFlag.AlignRight | flags_v), fill(t["header"]["right"], ctx))
            painter.setPen(QPen(QColor("#cccccc"), max(1.0, self.line * 0.05)))
            y = self.hh - self.line * 0.45
            painter.drawLine(0, int(y), int(W), int(y))
            painter.setPen(QColor("#555555"))

        # Footer
        if self.fh:
            top = H - self.fh
            painter.setPen(QPen(QColor("#cccccc"), max(1.0, self.line * 0.05)))
            y = top + self.line * 0.35
            painter.drawLine(0, int(y), int(W), int(y))
            painter.setPen(QColor("#555555"))
            band = QRectF(0, top + self.line * 0.6, W, self.line * 1.2)
            painter.drawText(band, (Qt.AlignmentFlag.AlignLeft | flags_v), fill(t["footer"]["left"], ctx))
            painter.drawText(band, (Qt.AlignmentFlag.AlignHCenter | flags_v), fill(t["footer"]["center"], ctx))
            painter.drawText(band, (Qt.AlignmentFlag.AlignRight | flags_v), fill(t["footer"]["right"], ctx))
        painter.restore()

        # Content of this page
        painter.save()
        painter.translate(0, self.hh - i * self.ch)
        clip = QRectF(0, i * self.ch, W, self.ch)
        painter.setClipRect(clip)
        pc = QAbstractTextDocumentLayout.PaintContext()
        pc.clip = clip
        self.doc.documentLayout().draw(painter, pc)
        painter.restore()


def _page_layout(t: dict) -> QPageLayout:
    orient = QPageLayout.Orientation.Landscape if t["landscape"] else QPageLayout.Orientation.Portrait
    m = float(t["margin"])
    return QPageLayout(QPageSize(PAGE_SIZES[t["page"]]), orient, QMarginsF(m, m, m, m), QPageLayout.Unit.Millimeter)


def write_pdf(project: Project, plan, video_name: str, path: str, template: dict | None = None) -> int:
    """Writes the PDF. Returns the number of pages."""
    t = normalize(template)
    writer = QPdfWriter(path)
    writer.setResolution(300)
    writer.setPageLayout(_page_layout(t))
    writer.setTitle(fill(t["title"], context(project, plan, video_name)) or f"{os.path.splitext(video_name)[0]} – comments")
    writer.setCreator(f"{APP_NAME} {__version__}")
    pages = _Pages(project, plan, video_name, t, writer, writer.width(), writer.height())
    painter = QPainter(writer)
    try:
        for i in range(pages.pages):
            if i:
                writer.newPage()
            pages.draw(painter, i)
    finally:
        painter.end()
    return pages.pages


def preview(project: Project, plan, video_name: str, template: dict | None, page: int = 0,
            dpi: int = 110) -> tuple[QImage, int]:
    """One page as an image (for the layout dialog). Returns (image, number of pages)."""
    t = normalize(template)
    rect = _page_layout(t).fullRectPixels(dpi)
    img = QImage(rect.width(), rect.height(), QImage.Format.Format_RGB32)
    dpm = int(round(dpi / 0.0254))
    img.setDotsPerMeterX(dpm)
    img.setDotsPerMeterY(dpm)
    img.fill(QColor("white"))
    margin = t["margin"] / 25.4 * dpi
    pages = _Pages(project, plan, video_name, t, img, rect.width() - 2 * margin, rect.height() - 2 * margin)
    page = max(0, min(page, pages.pages - 1))
    p = QPainter(img)
    p.translate(margin, margin)
    pages.draw(p, page)
    p.end()
    return img, pages.pages
