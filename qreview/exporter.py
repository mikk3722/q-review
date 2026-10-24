"""Export: comments as TXT / SRT / CSV / JSON, and the video (trimmed, with or without comments)."""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime

from .model import Project, Comment, APP_NAME, fmt_precise, fmt_srt
from . import overlay, media


@dataclass
class ExportOptions:
    folder: str
    basename: str
    use_trim: bool = True
    relative_times: bool = True     # text files: 00:00 = start of the exported video
    pdf: bool = True
    txt: bool = False                # plain text log (not in the dialog any more)
    srt: bool = True
    csv: bool = False
    json: bool = True
    video: bool = True
    comment_mode: str = "burn"      # "burn" | "subs" | "none"
    crf: int = 20
    max_height: int = 0             # 0 = original
    only_on_video: bool = False     # text files: only comments marked "on video"


@dataclass
class TimedComment:
    comment: Comment
    start: float      # in the time base of the export
    end: float


@dataclass
class ExportPlan:
    window_start: float
    window_end: float
    shift: float
    items: list[TimedComment] = field(default_factory=list)


def plan(project: Project, opts: ExportOptions, for_video: bool = False) -> ExportPlan:
    """Which comments go in the export and their times (clipped to the trim)."""
    dur = project.video_duration
    if opts.use_trim:
        a, b = project.trim_in, project.effective_out()
    else:
        a, b = 0.0, dur
    if b <= 0:   # duration unknown: everything
        b = max([c.end for c in project.comments] + [a + 1])
    shift = a if (for_video or opts.relative_times) else 0.0
    items = []
    for c in project.sorted_comments():
        if opts.only_on_video and not for_video and not c.on_video:
            continue
        if c.end <= a + 1e-6 or c.start >= b - 1e-6:
            continue
        s, e = max(c.start, a), min(c.end, b)
        items.append(TimedComment(c, s - shift, e - shift))
    return ExportPlan(a, b, shift, items)


# ── Text files ────────────────────────────────────────────────────────────────

def make_txt(project: Project, p: ExportPlan, video_name: str) -> str:
    lines = [f"{APP_NAME} – {video_name}",
             f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
             f"Source: {os.path.basename(project.video_path or '')}"]
    if project.is_trimmed():
        lines.append(f"Trim: {fmt_precise(p.window_start)} – {fmt_precise(p.window_end)}")
    if p.shift:
        lines.append("Times are relative to the start of the trimmed video.")
    lines.append(f"Comments: {len(p.items)}")
    lines.append("")
    for t in p.items:
        body = t.comment.text.replace("\n", "\n" + " " * 16)
        lines.append(f"{fmt_precise(t.start)}    {project.prefix(t.comment).upper()}: {body}")
    return "\n".join(lines) + "\n"


def write_pdf(project: Project, p: ExportPlan, video_name: str, path: str):
    """A4 PDF: time, role (with its colour), comment – one row per comment."""
    import html
    from PyQt6.QtCore import QMarginsF
    from PyQt6.QtGui import QPdfWriter, QPageSize, QPageLayout, QTextDocument, QFont, QColor

    def esc(t):
        return html.escape(t).replace("\n", "<br>")

    def text_color(hex_color):
        c = QColor(hex_color)
        while c.lightness() > 120:
            c = c.darker(125)
        return c.name()

    info = [f"Video: {esc(video_name)}"]
    src = os.path.basename(project.video_path or "")
    if src and src != video_name:
        info.append(f"Source: {esc(src)}")
    if project.is_trimmed():
        info.append(f"Trim: {fmt_precise(p.window_start)} – {fmt_precise(p.window_end)}")
    info.append(f"Exported {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    info.append(f"{len(p.items)} comment(s)")
    note = "Times are from the start of the exported (trimmed) video." if p.shift else ""

    rows = []
    for i, t in enumerate(p.items):
        c = t.comment
        prof = project.profile(c.profile_id)
        color = project.color(c)
        name = esc(prof.name if prof else "")
        who = f"<br><span style='color:#777777;'>{esc(c.author)}</span>" if c.author else ""
        off = "" if c.on_video else "<br><span style='color:#999999;'>not on video</span>"
        bg = "#ffffff" if i % 2 == 0 else "#f4f4f6"
        rows.append(
            f"<tr bgcolor='{bg}'>"
            f"<td bgcolor='{color}' width='5'></td>"
            f"<td width='96'><span style='font-family:Menlo,Consolas,monospace; font-size:9pt;'>{fmt_precise(t.start)}</span>"
            f"<br><span style='font-family:Menlo,Consolas,monospace; font-size:7.5pt; color:#888888;'>– {fmt_precise(t.end)}</span></td>"
            f"<td width='120'><b style='color:{text_color(color)};'>{name}</b>{who}{off}</td>"
            f"<td>{esc(c.text)}</td></tr>")
    if not rows:
        rows.append("<tr><td></td><td colspan='3' style='color:#777777;'>No comments.</td></tr>")

    doc_html = (
        "<html><body style='font-size:10pt; color:#1c1c1e;'>"
        f"<p style='font-size:17pt; font-weight:bold; margin-bottom:2px;'>{esc(os.path.splitext(video_name)[0])}</p>"
        f"<p style='color:#666666; font-size:8.5pt; margin-top:0;'>{' &nbsp;·&nbsp; '.join(info)}"
        + (f"<br>{note}" if note else "") + "</p>"
        "<table width='100%' cellspacing='0' cellpadding='6' border='0'>"
        "<thead><tr bgcolor='#1c1c1e'>"
        "<th width='5'></th>"
        "<th align='left' style='color:#ffffff;'>Time</th>"
        "<th align='left' style='color:#ffffff;'>Role</th>"
        "<th align='left' style='color:#ffffff;'>Comment</th></tr></thead>"
        + "".join(rows) + "</table>"
        f"<p style='color:#999999; font-size:7.5pt;'>{APP_NAME}</p>"
        "</body></html>")

    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setTitle(f"{os.path.splitext(video_name)[0]} – comments")
    writer.setCreator(APP_NAME)
    doc = QTextDocument()
    f = QFont()
    f.setPointSizeF(10)
    doc.setDefaultFont(f)
    doc.setHtml(doc_html)
    printer = getattr(doc, "print", None) or getattr(doc, "print_")
    printer(writer)


def make_srt(project: Project, p: ExportPlan) -> str:
    out = []
    for i, t in enumerate(p.items, 1):
        text = "\n".join(l.strip() for l in t.comment.text.splitlines() if l.strip()) or " "
        end = max(t.end, t.start + 0.1)
        out.append(f"{i}\n{fmt_srt(t.start)} --> {fmt_srt(end)}\n[{project.prefix(t.comment)}] {text}\n")
    return "\n".join(out) + ("\n" if out else "")


def make_csv(project: Project, p: ExportPlan) -> str:
    """Semicolon separated with BOM, so Danish Excel opens it directly."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Start", "End", "Duration (s)", "Profile", "Author", "Text", "On video"])
    for t in p.items:
        prof = project.profile(t.comment.profile_id)
        w.writerow([fmt_precise(t.start), fmt_precise(t.end), f"{t.end - t.start:.3f}".replace(".", ","),
                    prof.name if prof else "", t.comment.author, t.comment.text,
                    "Yes" if t.comment.on_video else "No"])
    return "﻿" + buf.getvalue()


def make_json(project: Project, p: ExportPlan, video_name: str) -> str:
    """Laid out like a Q-Recorder log, so Q-Recorder's playback mode can open the export."""
    messages = []
    for i, t in enumerate(p.items, 1):
        c = t.comment
        prof = project.profile(c.profile_id)
        messages.append({
            "id": i,
            "role": prof.name if prof else "",
            "color": project.color(c),
            "author": c.author,
            "text": c.text,
            "seconds": round(t.start, 3),
            "recordingTime": fmt_precise(t.start),
            "duration": round(t.end - t.start, 3),
            "onVideo": c.on_video,
            "source": "q-review",
            "context": "",
            "timecode": "",
        })
    root = {
        "app": APP_NAME,
        "video": video_name,
        "exportedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": os.path.basename(project.video_path or ""),
        "trim": {"in": round(p.window_start, 3), "out": round(p.window_end, 3)},
        "timesRelativeToTrim": bool(p.shift),
        "messages": messages,
        "events": [],
    }
    return json.dumps(root, indent=2, ensure_ascii=False, sort_keys=True)


def unique_base(folder: str, base: str, exts: list[str]) -> str:
    """'name', 'name 2', … – nothing is overwritten (as in Q-Recorder)."""
    candidate, n = base, 2
    while any(os.path.exists(os.path.join(folder, candidate + e)) for e in exts):
        candidate = f"{base} {n}"
        n += 1
    return candidate


def write_text_files(project: Project, opts: ExportOptions, base: str, video_name: str) -> list[str]:
    p = plan(project, opts)
    written = []

    def put(ext, text):
        path = os.path.join(opts.folder, base + ext)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        written.append(path)

    if opts.pdf:
        path = os.path.join(opts.folder, base + ".pdf")
        write_pdf(project, p, video_name, path)
        written.append(path)
    if opts.txt:
        put(".txt", make_txt(project, p, video_name))
    if opts.srt:
        put(".srt", make_srt(project, p))
    if opts.csv:
        put(".csv", make_csv(project, p))
    if opts.json:
        put(".json", make_json(project, p, video_name))
    return written


# ── Video ─────────────────────────────────────────────────────────────────────

def output_size(project: Project, max_height: int) -> tuple[int, int]:
    w, h = project.video_size
    if w <= 0 or h <= 0:
        w, h = 1920, 1080
    if max_height and h > max_height:
        w = w * max_height / h
        h = max_height
    return int(round(w / 2)) * 2, int(round(h / 2)) * 2


def build_overlay_track(project: Project, p: ExportPlan, width: int, height: int, folder: str) -> str | None:
    """Renders the bubbles as transparent images, one per change, and writes an
    ffconcat list that shows each image for exactly as long as it is on screen."""
    length = p.window_end - p.window_start
    items = [t for t in p.items if project.visible_on_video(t.comment)]
    if not items or length <= 0:
        return None
    cuts = {0.0, length}
    for t in items:
        cuts.add(min(max(t.start, 0.0), length))
        cuts.add(min(max(t.end, 0.0), length))
    cuts = sorted(cuts)
    segments = []   # (key, duration)
    images = {}
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 0.0005:
            continue
        mid = (a + b) / 2
        active = [t.comment for t in items if t.start <= mid < t.end]
        active.sort(key=lambda c: (c.start, c.created, c.id))
        key = tuple(c.id for c in active)
        if segments and segments[-1][0] == key:
            segments[-1] = (key, segments[-1][1] + (b - a))
        else:
            segments.append((key, b - a))
        if key not in images:
            name = f"ov{len(images):05d}.png"
            img = overlay.render_image(project, active, width, height)
            img.save(os.path.join(folder, name), "PNG")
            images[key] = name
    # End on an empty picture so nothing hangs on after the last comment.
    if () not in images:
        name = f"ov{len(images):05d}.png"
        overlay.render_image(project, [], width, height).save(os.path.join(folder, name), "PNG")
        images[()] = name
    if segments[-1][0] != ():
        segments.append(((), 0.04))
    lines = ["ffconcat version 1.0"]
    for key, dur in segments:
        lines.append(f"file '{images[key]}'")
        lines.append(f"duration {dur:.4f}")
    lines.append(f"file '{images[segments[-1][0]]}'")
    path = os.path.join(folder, "overlay.ffconcat")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def build_video_command(project: Project, opts: ExportOptions, out_path: str, work: str) -> tuple[list[str], float]:
    """The ffmpeg command line and the length of the result (for the progress bar)."""
    ff = media.ffmpeg_path()
    if not ff:
        raise RuntimeError("FFmpeg was not found.")
    p = plan(project, opts, for_video=True)
    length = max(0.04, p.window_end - p.window_start)
    w, h = output_size(project, opts.max_height)

    cmd = [ff, "-hide_banner", "-y", "-nostdin", "-progress", "pipe:1", "-nostats", "-loglevel", "error"]
    if p.window_start > 0:
        cmd += ["-ss", f"{p.window_start:.3f}"]
    cmd += ["-t", f"{length:.3f}", "-i", project.video_path]
    next_input = 1
    info = media.probe(project.video_path)
    deint = "bwdif=mode=send_frame:parity=auto:deint=all," if info.interlaced else ""
    scale = f"{deint}scale={w}:{h}:flags=bicubic,setsar=1"

    ov = build_overlay_track(project, p, w, h, work) if opts.comment_mode == "burn" else None
    if ov:
        cmd += ["-f", "concat", "-safe", "0", "-i", ov]
        cmd += ["-filter_complex",
                f"[0:v:0]{scale}[base];[{next_input}:v]format=rgba[ov];"
                f"[base][ov]overlay=0:0:eof_action=repeat:format=auto,format=yuv420p[v]",
                "-map", "[v]"]
        next_input += 1
    else:
        cmd += ["-vf", scale + ",format=yuv420p", "-map", "0:v:0"]
    cmd += ["-map", "0:a?"]

    if opts.comment_mode == "subs" and p.items:
        srt = os.path.join(work, "comments.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(make_srt(project, p))
        # Inputs must come before the output options: insert the subtitle input after the others.
        insert_at = cmd.index("-filter_complex") if "-filter_complex" in cmd else cmd.index("-vf")
        cmd[insert_at:insert_at] = ["-i", srt]
        cmd += ["-map", f"{next_input}:0", "-c:s", "mov_text",
                "-metadata:s:s:0", "title=Comments", "-disposition:s:0", "default"]
        next_input += 1

    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(opts.crf),
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-t", f"{length:.3f}", out_path]
    return cmd, length
