"""FFmpeg: finding it, reading video information and drawing the audio waveform."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

_ffmpeg: str | None = None

# No console window flashing up on Windows
CREATE_FLAGS = 0x08000000 if sys.platform == "win32" else 0


def ffmpeg_path() -> str | None:
    """FFmpeg bundled with the app (imageio-ffmpeg), next to the app, or installed on the system."""
    global _ffmpeg
    if _ffmpeg and os.path.exists(_ffmpeg):
        return _ffmpeg
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidates = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates.append(os.path.join(base, exe))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), exe))
    for c in candidates:
        if os.path.exists(c):
            _ffmpeg = c
            return c
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            _ffmpeg = p
            return p
    except Exception:
        pass
    p = shutil.which("ffmpeg")
    if p:
        _ffmpeg = p
    return p


class VideoInfo:
    def __init__(self):
        self.duration = 0.0
        self.width = 0
        self.height = 0
        self.fps = 25.0
        self.has_audio = False
        self.audio_streams = 0
        self.video_codec = ""


def probe(path: str) -> VideoInfo:
    """Reads duration, size, frame rate and audio from `ffmpeg -i` (no ffprobe needed)."""
    info = VideoInfo()
    ff = ffmpeg_path()
    if not ff:
        return info
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30, creationflags=CREATE_FLAGS)
        text = r.stderr
    except Exception:
        return info
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        info.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in text.splitlines():
        if "Stream #" in line and "Video:" in line and not info.width:
            cm = re.search(r"Video:\s*([A-Za-z0-9_]+)", line)
            if cm:
                info.video_codec = cm.group(1)
            sm = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
            if sm:
                info.width, info.height = int(sm.group(1)), int(sm.group(2))
            fm = re.search(r"(\d+(?:\.\d+)?)\s*fps", line) or re.search(r"(\d+(?:\.\d+)?)\s*tbr", line)
            if fm:
                try:
                    v = float(fm.group(1))
                    if 1 <= v <= 300:
                        info.fps = v
                except ValueError:
                    pass
        if "Stream #" in line and "Audio:" in line:
            info.has_audio = True
            info.audio_streams += 1
    # Phone videos filmed upright: ffmpeg turns them, so width and height swap.
    rm = re.search(r"rotation of (-?\d+(?:\.\d+)?)", text) or re.search(r"rotate\s*:\s*(-?\d+)", text)
    if rm and info.width:
        try:
            if round(abs(float(rm.group(1)))) % 180 == 90:
                info.width, info.height = info.height, info.width
        except ValueError:
            pass
    return info


def make_waveform(path: str, width: int = 4000, height: int = 80) -> str | None:
    """A PNG with the audio waveform (whole file), or None if there is no audio."""
    ff = ffmpeg_path()
    if not ff:
        return None
    out = os.path.join(tempfile.gettempdir(), f"qreview-wave-{abs(hash(path)) % 10**10}-{width}.png")
    cmd = [ff, "-hide_banner", "-v", "error", "-y", "-i", path, "-filter_complex",
           f"[0:a:0]aformat=channel_layouts=mono,showwavespic=s={width}x{height}:colors=0x9AA7B8:scale=sqrt",
           "-frames:v", "1", out]
    try:
        subprocess.run(cmd, capture_output=True, timeout=600, creationflags=CREATE_FLAGS)
    except Exception:
        return None
    return out if os.path.exists(out) and os.path.getsize(out) > 0 else None


def make_test_video(path: str, seconds: int = 12, size: str = "1280x720") -> bool:
    """A test video with picture and sound (used by the self-test)."""
    ff = ffmpeg_path()
    if not ff:
        return False
    cmd = [ff, "-hide_banner", "-v", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-c:a", "aac", "-shortest", path]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_FLAGS)
    if r.returncode != 0:
        print(r.stderr)
    return r.returncode == 0 and os.path.exists(path)
