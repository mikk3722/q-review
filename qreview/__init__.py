"""Q-Review – comments on video, part of the Q-Recorder family."""
import os as _os
import sys as _sys

# The version. Raise it for each release and add a line to CHANGELOG.md;
# a tag with the same number (git tag v0.2.0) makes GitHub publish the release.
__version__ = "0.2.1"


def _read_build() -> str:
    # version.txt is written by the GitHub build ("build 12, 2026-10-24")
    base = getattr(_sys, "_MEIPASS", _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    try:
        with open(_os.path.join(base, "version.txt"), encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return "from source"


__build__ = _read_build()
