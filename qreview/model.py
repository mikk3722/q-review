"""Project data: profiles, comments, trim – and reading/writing .qreview files.

All times are seconds in the *source* video. Trimming only stores in/out points;
the export subtracts the in-point so the timecodes match the exported video.
"""
from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime

APP_NAME = "Q-Review"
FILE_EXT = ".qreview"
FORMAT_VERSION = 1

# Same default roles as Q-Recorder (Settings.swift → defaultRoles).
DEFAULT_PROFILES = [
    ("Director", "#E5484D"),
    ("Lighting", "#F5A524"),
    ("Sound", "#3E9BFF"),
    ("Stage manager", "#46A758"),
]
REVIEW_COLOR = "#5AC8FA"   # Q-Recorder: notes added while reviewing


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Time formats (same as Q-Recorder's TimeFormat) ─────────────────────────────

def fmt_clock(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}"


def fmt_precise(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    return f"{ms // 3_600_000:02d}:{(ms // 60_000) % 60:02d}:{(ms // 1000) % 60:02d}.{ms % 1000:03d}"


def fmt_short(seconds: float) -> str:
    """00:01:23.4 – for lists."""
    ds = max(0, int(round(seconds * 10)))
    s = ds // 10
    return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}.{ds % 10}"


def fmt_srt(seconds: float) -> str:
    return fmt_precise(seconds).replace(".", ",")


def parse_time(text: str) -> float | None:
    """'1:02:03.5', '02:03', '83.2' → seconds (None if invalid)."""
    text = text.strip().replace(",", ".")
    if not text:
        return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return None
    if len(parts) > 3 or any(p < 0 for p in parts):
        return None
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class Profile:
    name: str
    color: str
    show_on_video: bool = True
    id: str = field(default_factory=new_id)


@dataclass
class Comment:
    profile_id: str
    text: str
    start: float
    duration: float = 5.0
    on_video: bool = True
    # Top-left corner as a fraction of the picture (0–1). None = automatic (stacked bottom left).
    x: float | None = None
    y: float | None = None
    author: str = ""
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    id: str = field(default_factory=new_id)

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def has_position(self) -> bool:
        return self.x is not None and self.y is not None


@dataclass
class OverlayStyle:
    font_scale: float = 1.0        # 1.0 = 30 px at 1080p (as Q-Recorder's chat block)
    max_stacked: int = 4           # automatic bubbles shown at once
    show_name: bool = True         # profile name above the text
    opacity: float = 0.72          # bubble background


class Project:
    """The open project. The UI changes it through MainWindow, which handles undo."""

    def __init__(self):
        self.path: str | None = None          # the .qreview file
        self.video_path: str | None = None
        self.video_duration: float = 0.0      # from the player
        self.video_size: tuple[int, int] = (1920, 1080)
        self.video_fps: float = 25.0
        self.trim_in: float = 0.0
        self.trim_out: float | None = None    # None = end of video
        self.overlay_enabled: bool = True     # "comments on video" (global)
        self.default_duration: float = 5.0
        self.style = OverlayStyle()
        self.profiles: list[Profile] = [Profile(n, c) for n, c in DEFAULT_PROFILES]
        self.comments: list[Comment] = []

    # ── Lookups ──

    def profile(self, pid: str | None) -> Profile | None:
        for p in self.profiles:
            if p.id == pid:
                return p
        return None

    def comment(self, cid: str | None) -> Comment | None:
        for c in self.comments:
            if c.id == cid:
                return c
        return None

    def sorted_comments(self) -> list[Comment]:
        return sorted(self.comments, key=lambda c: (c.start, c.created, c.id))

    def effective_out(self) -> float:
        d = self.video_duration
        if self.trim_out is None:
            return d
        return min(self.trim_out, d) if d > 0 else self.trim_out

    def is_trimmed(self) -> bool:
        return self.trim_in > 0.001 or (self.trim_out is not None and self.video_duration > 0
                                        and self.trim_out < self.video_duration - 0.001)

    def prefix(self, c: Comment) -> str:
        p = self.profile(c.profile_id)
        name = p.name if p else "?"
        return f"{name} · {c.author}" if c.author else name

    def color(self, c: Comment) -> str:
        p = self.profile(c.profile_id)
        return p.color if p else "#8E8E93"

    def visible_on_video(self, c: Comment) -> bool:
        p = self.profile(c.profile_id)
        return self.overlay_enabled and c.on_video and (p is None or p.show_on_video)

    def comments_at(self, t: float, only_video: bool = True) -> list[Comment]:
        out = []
        for c in self.comments:
            if c.start - 1e-6 <= t < c.end - 1e-6:
                if not only_video or self.visible_on_video(c):
                    out.append(c)
        out.sort(key=lambda c: (c.start, c.created, c.id))
        return out

    def ensure_profile(self, name: str, color: str) -> Profile:
        for p in self.profiles:
            if p.name.strip().lower() == name.strip().lower():
                return p
        p = Profile(name or "Unnamed", color or "#8E8E93")
        self.profiles.append(p)
        return p

    # ── Undo snapshots ──

    def snapshot(self) -> dict:
        return copy.deepcopy({
            "trim_in": self.trim_in, "trim_out": self.trim_out,
            "overlay_enabled": self.overlay_enabled, "default_duration": self.default_duration,
            "style": asdict(self.style),
            "profiles": [asdict(p) for p in self.profiles],
            "comments": [asdict(c) for c in self.comments],
        })

    def restore(self, snap: dict):
        snap = copy.deepcopy(snap)
        self.trim_in = snap["trim_in"]
        self.trim_out = snap["trim_out"]
        self.overlay_enabled = snap["overlay_enabled"]
        self.default_duration = snap["default_duration"]
        self.style = OverlayStyle(**snap["style"])
        self.profiles = [Profile(**p) for p in snap["profiles"]]
        self.comments = [Comment(**c) for c in snap["comments"]]

    # ── Files ──

    def to_json(self) -> dict:
        video = None
        if self.video_path:
            video = {"path": os.path.abspath(self.video_path), "name": os.path.basename(self.video_path)}
            if self.path:
                try:
                    video["relative"] = os.path.relpath(self.video_path, os.path.dirname(self.path))
                except ValueError:   # different drive on Windows
                    pass
        return {
            "app": APP_NAME,
            "version": FORMAT_VERSION,
            "saved": datetime.now().isoformat(timespec="seconds"),
            "video": video,
            "trim": {"in": round(self.trim_in, 3),
                     "out": None if self.trim_out is None else round(self.trim_out, 3)},
            "overlayEnabled": self.overlay_enabled,
            "defaultDuration": self.default_duration,
            "style": {"fontScale": self.style.font_scale, "maxStacked": self.style.max_stacked,
                      "showName": self.style.show_name, "opacity": self.style.opacity},
            "profiles": [{"id": p.id, "name": p.name, "color": p.color, "showOnVideo": p.show_on_video}
                         for p in self.profiles],
            "comments": [{
                "id": c.id, "profileId": c.profile_id, "text": c.text,
                "start": round(c.start, 3), "duration": round(c.duration, 3),
                "recordingTime": fmt_precise(c.start),
                "onVideo": c.on_video, "x": c.x, "y": c.y,
                "author": c.author, "created": c.created,
            } for c in self.sorted_comments()],
        }

    def save(self, path: str):
        self.path = path
        data = json.dumps(self.to_json(), indent=2, ensure_ascii=False)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)   # atomic, like Q-Recorder

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            root = json.load(f)
        if root.get("app") != APP_NAME and "comments" not in root:
            raise ValueError("This is not a Q-Review project.")
        p = cls()
        p.path = path
        v = root.get("video") or None
        if v:
            candidates = []
            if v.get("relative"):
                candidates.append(os.path.normpath(os.path.join(os.path.dirname(path), v["relative"])))
            if v.get("path"):
                candidates.append(v["path"])
            if v.get("name"):
                candidates.append(os.path.join(os.path.dirname(path), v["name"]))
            p.video_path = next((c for c in candidates if os.path.exists(c)), candidates[0] if candidates else None)
        trim = root.get("trim") or {}
        p.trim_in = float(trim.get("in") or 0)
        p.trim_out = None if trim.get("out") is None else float(trim["out"])
        p.overlay_enabled = bool(root.get("overlayEnabled", True))
        p.default_duration = float(root.get("defaultDuration", 5.0))
        st = root.get("style") or {}
        p.style = OverlayStyle(font_scale=float(st.get("fontScale", 1.0)),
                               max_stacked=int(st.get("maxStacked", 4)),
                               show_name=bool(st.get("showName", True)),
                               opacity=float(st.get("opacity", 0.72)))
        profs = root.get("profiles")
        if profs:
            p.profiles = [Profile(name=x.get("name", "?"), color=x.get("color", "#8E8E93"),
                                  show_on_video=bool(x.get("showOnVideo", True)), id=x.get("id") or new_id())
                          for x in profs]
        p.comments = []
        for x in root.get("comments") or []:
            p.comments.append(Comment(
                profile_id=x.get("profileId", ""), text=x.get("text", ""),
                start=max(0.0, float(x.get("start", 0))), duration=max(0.1, float(x.get("duration", 5))),
                on_video=bool(x.get("onVideo", True)),
                x=x.get("x"), y=x.get("y"), author=x.get("author", ""),
                created=x.get("created", ""), id=x.get("id") or new_id()))
        # Comments whose profile was removed get a profile again
        for c in p.comments:
            if p.profile(c.profile_id) is None:
                c.profile_id = p.ensure_profile("Unknown", "#8E8E93").id
        return p


# ── Q-Recorder ────────────────────────────────────────────────────────────────

def is_qrecorder_log(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            root = json.load(f)
        return isinstance(root, dict) and ("messages" in root or root.get("app") == "Q-Recorder")
    except Exception:
        return False


def _seconds(d: dict) -> float:
    if isinstance(d.get("seconds"), (int, float)):
        return max(0.0, float(d["seconds"]))
    if isinstance(d.get("recordingTime"), str):
        return parse_time(d["recordingTime"]) or 0.0
    return 0.0


def import_qrecorder(json_path: str, default_duration: float = 5.0) -> Project:
    """Builds a project from a Q-Recorder recording (.json log next to the .mov).

    The chat messages become comments (roles → profiles) and notes added in Q-Recorder's
    playback mode come along as the profile "Review". The Q-Recorder files are only read.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        root = json.load(f)
    p = Project()
    p.profiles = []
    p.default_duration = default_duration
    folder = os.path.dirname(json_path)
    name = root.get("video") or os.path.splitext(os.path.basename(json_path))[0] + ".mov"
    p.video_path = os.path.join(folder, name)

    for m in root.get("messages") or []:
        prof = p.ensure_profile(m.get("role") or "Chat", m.get("color") or "#8E8E93")
        p.comments.append(Comment(profile_id=prof.id, text=m.get("text", ""), start=_seconds(m),
                                  duration=default_duration, on_video=bool(m.get("onVideo", True)),
                                  author=m.get("author", "")))
    review = root.get("review") or {}
    for n in review.get("notes") or []:
        prof = p.ensure_profile("Review", REVIEW_COLOR)
        p.comments.append(Comment(profile_id=prof.id, text=n.get("text", ""), start=_seconds(n),
                                  duration=default_duration, author=n.get("author", "")))
    if not p.profiles:
        p.profiles = [Profile(n, c) for n, c in DEFAULT_PROFILES]
    return p


def read_qrecorder_roles(path: str) -> list[Profile]:
    """Roles from a Q-Recorder project (.protokol) or recording log (.json)."""
    with open(path, "r", encoding="utf-8") as f:
        root = json.load(f)
    out: list[Profile] = []
    roles = (root.get("settings") or {}).get("roles")
    if isinstance(roles, list):
        for r in roles:
            out.append(Profile(r.get("name", "?"), r.get("colorHex", "#8E8E93"), bool(r.get("showOnVideo", True))))
    else:
        seen = set()
        for m in root.get("messages") or []:
            key = (m.get("role") or "").lower()
            if key and key not in seen:
                seen.add(key)
                out.append(Profile(m.get("role"), m.get("color") or "#8E8E93"))
    return out
