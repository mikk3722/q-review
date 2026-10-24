"""Automatic test of the whole chain – run by the GitHub build on Windows and macOS.

Makes a test video, opens it, adds comments, trims, saves and reopens the project,
imports a Q-Recorder log and exports (burned in + subtitle track + text files).
Writes screenshots and the exported files to the output folder.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import traceback

from PyQt6.QtCore import QEventLoop, QTimer

from . import media, exporter, overlay
from .model import Project, import_qrecorder, fmt_precise

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" – {detail}" if detail else ""), flush=True)


def wait(app, seconds: float, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if until and until():
            return True
        time.sleep(0.02)
    return until() if until else True


def run(app, out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="qreview-selftest-")
    try:
        _run(app, out_dir, work)
    except Exception:
        check("no exception", False, traceback.format_exc())
    finally:
        shutil.rmtree(work, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    with open(os.path.join(out_dir, "selftest.txt"), "w", encoding="utf-8") as f:
        for name, ok, detail in results:
            f.write(("PASS " if ok else "FAIL ") + name + (f" – {detail}" if detail else "") + "\n")
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 1 if failed else 0


def _run(app, out_dir, work):
    ff = media.ffmpeg_path()
    check("ffmpeg found", bool(ff), str(ff))
    video = os.path.join(work, "Q-Recorder 2026-10-24 20-00-00.mov")
    check("test video made", media.make_test_video(video, 12))
    info = media.probe(video)
    check("probe", abs(info.duration - 12) < 0.3 and info.width == 1280 and info.has_audio,
          f"{info.duration} s {info.width}x{info.height} {info.fps} fps audio={info.has_audio}")

    from .mainwindow import MainWindow
    win = MainWindow()
    win.quiet = True
    win.resize(1400, 860)
    win.show()
    win.open_any(video, asked=True)
    loaded = wait(app, 20, lambda: win.project.video_duration > 0)
    check("player loads the video (Qt Multimedia)", loaded and abs(win.project.video_duration - 12) < 0.5,
          f"duration={win.project.video_duration}")
    wait(app, 2, lambda: win.timeline.wave is not None)
    check("waveform", win.timeline.wave is not None)

    # Comments
    p = win.project
    win.add_comment("Light cue 12 comes too early", 1.0)
    win.set_active_profile(p.profiles[2].id)
    win.add_comment("The music fade should be slower – try 5 seconds instead of 3, and keep the vocal on top", 2.0)
    c3 = win.add_comment("Placed by hand, top right", 2.5, p.profiles[1].id)
    c3.x, c3.y = 0.62, 0.08
    hidden = win.add_comment("Not on video", 3.0, p.profiles[3].id)
    win.toggle_on_video(hidden.id)
    check("comments added", len(p.comments) == 4)
    n = len(p.comments)
    win.add_comment("to be undone", 4.0)
    win.undo()
    check("undo", len(p.comments) == n)
    win.redo()
    win.undo()

    # Trim
    win.seek(0.5)
    win.set_in()
    win.seek(10.0)
    win.set_out()
    check("trim", abs(p.trim_in - 0.5) < 0.01 and abs(p.effective_out() - 10.0) < 0.01, f"{p.trim_in}–{p.effective_out()}")

    # Save / open
    proj_path = os.path.join(work, "Test.qreview")
    p.save(proj_path)
    q = Project.load(proj_path)
    check("save and reopen", len(q.comments) == 4 and q.comments[2].x == 0.62 and abs(q.trim_in - 0.5) < 0.01
          and q.video_path == video)
    shutil.copy(proj_path, os.path.join(out_dir, "Test.qreview"))

    # Screenshot with the bubbles
    win.seek(2.7)
    win.select(c3.id)
    wait(app, 1.5)
    win.grab().save(os.path.join(out_dir, "screenshot-main.png"))
    img = overlay.render_image(p, p.comments_at(2.7), 1280, 720)
    img.save(os.path.join(out_dir, "overlay-1280x720.png"))
    check("overlay image", not img.isNull())

    # Export: burned in + text files
    opts = exporter.ExportOptions(folder=work, basename="Export burn", comment_mode="burn")
    from .export_dialog import run_export_blocking
    t0 = time.time()
    files = run_export_blocking(p, opts)
    mp4 = files[0]
    pi = media.probe(mp4)
    check("export burned-in video", os.path.exists(mp4) and abs(pi.duration - 9.5) < 0.2 and pi.has_audio,
          f"{pi.duration:.2f} s in {time.time() - t0:.1f} s")
    for ext in (".txt", ".srt", ".json"):
        check(f"export {ext}", any(f.endswith(ext) for f in files))
    srt = open([f for f in files if f.endswith(".srt")][0], encoding="utf-8").read()
    check("srt times relative to trim", "00:00:00,500 --> 00:00:05,500" in srt, srt.splitlines()[1] if srt else "")
    js = json.load(open([f for f in files if f.endswith(".json")][0], encoding="utf-8"))
    check("json is Q-Recorder compatible", js["video"].endswith(".mp4") and len(js["messages"]) == 4
          and js["messages"][0]["seconds"] == 0.5)
    for f in files:
        shutil.copy(f, out_dir)
    for t in (1.0, 2.2):
        subprocess.run([ff, "-v", "error", "-y", "-ss", str(t), "-i", mp4, "-frames:v", "1",
                        os.path.join(out_dir, f"burned-frame-{t}s.png")], creationflags=media.CREATE_FLAGS)

    # Export: subtitle track, 720p max, no trim
    opts2 = exporter.ExportOptions(folder=work, basename="Export subs", comment_mode="subs", use_trim=False,
                                   max_height=540, txt=False, srt=False, json=False, csv=True)
    files2 = run_export_blocking(p, opts2)
    r = subprocess.run([ff, "-hide_banner", "-i", files2[0]], capture_output=True, text=True,
                       creationflags=media.CREATE_FLAGS)
    check("export with subtitle track", "Subtitle: mov_text" in r.stderr and "960x540" in r.stderr)
    check("export .csv", any(f.endswith(".csv") for f in files2))

    # Q-Recorder import
    log = {
        "app": "Q-Recorder", "video": os.path.basename(video), "startedAt": "2026-10-24T20:00:00.000Z",
        "messages": [
            {"id": 1, "role": "Director", "color": "#E5484D", "author": "Mikkel", "text": "Hello", "seconds": 1.5,
             "recordingTime": "00:00:01.500", "onVideo": True},
            {"id": 2, "role": "Sound", "color": "#3E9BFF", "author": "", "text": "Too loud", "seconds": 4.0,
             "recordingTime": "00:00:04.000", "onVideo": False},
        ],
        "events": [],
        "review": {"notes": [{"id": "rX", "seconds": 6.0, "text": "Review note", "author": "Anna"}]},
    }
    log_path = os.path.splitext(video)[0] + ".json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f)
    imp = import_qrecorder(log_path)
    check("Q-Recorder import", len(imp.comments) == 3 and len(imp.profiles) == 3 and imp.video_path == video
          and imp.comments[1].on_video is False)
    win.open_any(log_path, asked=True)
    wait(app, 10, lambda: win.project.video_duration > 0)
    check("open Q-Recorder recording in the window", len(win.project.comments) == 3)
    win.seek(1.6)
    wait(app, 1.0)
    win.grab().save(os.path.join(out_dir, "screenshot-qrecorder-import.png"))

    # Replace video (shorter)
    short = os.path.join(work, "short.mp4")
    media.make_test_video(short, 5, "640x360")
    win.replace_video(short)
    wait(app, 10, lambda: abs(win.project.video_duration - 5) < 0.5)
    check("replace video keeps comments", len(win.project.comments) == 3 and win.project.video_path == short,
          f"duration={win.project.video_duration}")
    win.dirty = False
    win.close()
