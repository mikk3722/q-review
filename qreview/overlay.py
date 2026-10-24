"""Draws the comment bubbles. The same code draws the preview over the video and the
images that are burned into the exported video, so what you see is what you get.

Look as Q-Recorder's chat block: one rounded box per comment with a coloured stripe
on the left, newest at the bottom, stacked in the bottom left corner.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QImage

from .model import Project, Comment

TEXT_FLAGS = Qt.TextFlag.TextWordWrap.value | Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignTop.value


def _fonts(height: float, scale: float):
    s = height / 1080.0
    size = max(6.0, 30.0 * s * scale)
    body = QFont()
    body.setPixelSize(max(6, round(size)))
    head = QFont(body)
    head.setPixelSize(max(5, round(size * 0.72)))
    head.setBold(True)
    return s, body, head


def _lighter(hex_color: str) -> QColor:
    c = QColor(hex_color)
    return c.lighter(135) if c.lightness() < 150 else c


def layout(project: Project, comments: list[Comment], width: float, height: float):
    """Returns [(comment, box QRectF, header, body_rect, head_rect)] in drawing order."""
    s, body_font, head_font = _fonts(height, project.style.font_scale)
    fm_body = QFontMetricsF(body_font)
    fm_head = QFontMetricsF(head_font)
    pad = 12 * s * project.style.font_scale
    stripe = 6 * s * project.style.font_scale
    gap = 8 * s * project.style.font_scale
    max_text_w = max(40.0, width * 0.42)
    show_name = project.style.show_name

    def measure(c: Comment):
        header = project.prefix(c) if show_name else ""
        text = c.text.strip() or " "
        br = fm_body.boundingRect(QRectF(0, 0, max_text_w, 100000), TEXT_FLAGS, text)
        hr = fm_head.boundingRect(QRectF(0, 0, max_text_w, 100000), TEXT_FLAGS, header) if header else QRectF()
        inner_w = max(br.width(), hr.width())
        head_h = hr.height() + 2 * s if header else 0
        w = inner_w + 2 * pad + stripe
        h = head_h + br.height() + 2 * pad
        return header, text, w, h, head_h, inner_w, br.height()

    placed = []
    auto = [c for c in comments if not c.has_position]
    fixed = [c for c in comments if c.has_position]

    # Automatic: bottom left, newest at the bottom, the newest N
    auto = auto[-max(1, project.style.max_stacked):]
    margin_x = width * 0.03
    bottom = height - height * 0.05
    for c in reversed(auto):
        header, text, w, h, head_h, inner_w, body_h = measure(c)
        box = QRectF(margin_x, bottom - h, w, h)
        if box.top() < height * 0.03:
            break
        placed.append((c, box, header, text, head_h, inner_w, body_h))
        bottom -= h + gap
    placed.reverse()

    for c in fixed:
        header, text, w, h, head_h, inner_w, body_h = measure(c)
        x = min(max(0.0, c.x * width), max(0.0, width - w))
        y = min(max(0.0, c.y * height), max(0.0, height - h))
        placed.append((c, QRectF(x, y, w, h), header, text, head_h, inner_w, body_h))

    out = []
    for c, box, header, text, head_h, inner_w, body_h in placed:
        tx = box.left() + stripe + pad
        head_rect = QRectF(tx, box.top() + pad, inner_w + 2, head_h)
        body_rect = QRectF(tx, box.top() + pad + head_h, inner_w + 2, body_h + 2)
        out.append((c, box, header, text, head_rect, body_rect))
    return out, (s, body_font, head_font, stripe)


def draw(painter: QPainter, project: Project, comments: list[Comment], width: float, height: float,
         selected_id: str | None = None):
    """Draws the bubbles into (0, 0, width, height). Returns {comment_id: box} for hit testing."""
    items, (s, body_font, head_font, stripe) = layout(project, comments, width, height)
    radius = 8 * s * project.style.font_scale
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    boxes = {}
    bg = QColor(0, 0, 0, int(255 * max(0.0, min(1.0, project.style.opacity))))
    for c, box, header, text, head_rect, body_rect in items:
        path = QPainterPath()
        path.addRoundedRect(box, radius, radius)
        painter.fillPath(path, bg)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(box.left(), box.top(), stripe, box.height()), QColor(project.color(c)))
        painter.restore()
        if header:
            painter.setFont(head_font)
            painter.setPen(_lighter(project.color(c)))
            painter.drawText(head_rect, TEXT_FLAGS, header)
        painter.setFont(body_font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(body_rect, TEXT_FLAGS, text)
        if c.id == selected_id:
            pen = QPen(QColor(255, 255, 255, 230), max(1.5, 2.5 * s))
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(-3 * s, -3 * s, 3 * s, 3 * s), radius, radius)
        boxes[c.id] = box
    painter.restore()
    return boxes


def render_image(project: Project, comments: list[Comment], width: int, height: int) -> QImage:
    """A transparent full-frame image with the bubbles (used for burning in)."""
    img = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    if comments:
        p = QPainter(img)
        draw(p, project, comments, width, height)
        p.end()
    return img
