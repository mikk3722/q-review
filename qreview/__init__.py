"""Q-Review – comments on video, part of the Q-Recorder family."""
import os as _os
import sys as _sys


def _read_version() -> str:
    # version.txt is written by the GitHub build (tag + build number)
    base = getattr(_sys, "_MEIPASS", _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    try:
        with open(_os.path.join(base, "version.txt"), encoding="utf-8-sig") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


__version__ = _read_version()
