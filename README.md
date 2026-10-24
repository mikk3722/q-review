# Q-Review

Comments on video – the review part of Q-Recorder as a stand-alone app for **Windows** (and macOS).

- **Open** a video, a Q-Review project or a Q-Recorder recording (the `.json` log next to the `.mov`).
  Q-Recorder's chat notes become comments, its roles become profiles. The recording itself is never changed.
- **Write comments** on the left. There is one profile to start with; add more (Director, Lighting, Sound … like
  Q-Recorder's roles) under *Edit profiles* – or import them from a Q-Recorder project.
  The small tick on each comment decides whether it is shown on the video.
  The time is held from the moment you start writing, and playback pauses while you write (can be switched off).
- **Timeline**: one track per profile. Drag comments to move them (also to another profile), drag the edges to change
  the length. Comments snap to the playhead, the trim and each other (hold Alt to turn snapping off).
- **On the video**: comments are shown as bubbles like Q-Recorder's chat block (bottom left). Drag a bubble to place it
  anywhere; right-click → *Automatic position* puts it back. *Comments on video* turns them all on/off,
  each comment and each profile can also be switched off.
- **Trim**: drag the yellow handles in the timeline, or press **I** / **O** at the playhead. **Lock** (or **L**) locks
  in and out so they can't be moved by accident. Nothing is cut until you export.
- **Nudge**: the ◁| and |▷ buttons (or , and .) move one frame.
- **Replace video**: *File → Replace video* keeps all comments (*Edit → Shift all comments* if the new video starts
  at a different point). A project whose video has moved asks you to find it.
- **Export**:
  - Video (MP4, H.264) – comments burned into the picture (exactly as in the preview), as a subtitle track that
    can be switched on/off in the player, or without comments. Original size, 1080p, 720p or 540p.
  - Comments with timecodes – `.txt` (as Q-Recorder's log), `.srt`, `.csv` (opens in Excel) and `.json`
    (Q-Recorder's log format, so Q-Recorder's *Play* mode can open the exported video).
  - Timecodes start at 00:00:00 at the trim in-point, so they match the exported video.

## Keys

| Key | |
|---|---|
| Space | Play / pause |
| ← / → | 5 s back / forward (Shift: 1 s) |
| , / . | One frame back / forward |
| I / O | Set in / out point |
| L | Lock / unlock in and out |
| Home / End | Go to in / out point |
| Enter | Write a new comment (Enter adds it, Shift+Enter = new line, Esc = cancel) |
| Ctrl+1 … 9 | Choose profile |
| F2 / Delete | Edit / delete the selected comment |
| Ctrl+T | Comments on video on/off |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Ctrl+wheel | Zoom the timeline |

## Files

- *File → Save as folder with video* makes one folder with the project and a copy of the video – easy to move
  or hand on. The export can also put all its files in a new folder (on by default).

- `<name>.qreview` – the project (JSON): video path (absolute and relative), trim, profiles, comments.
  Times are always in the original video's time; the export takes care of the trim.

## Download

See [Releases](../../releases). Windows: unzip `Q-Review-windows.zip` and run `Q-Review.exe` (FFmpeg is included).

## Versions

The version is `__version__` in `qreview/__init__.py`; what changed is in `CHANGELOG.md`.
For a release: raise the number, add to the changelog, push, then `git tag v0.2.0 && git push --tags`.

## Building

Push a tag (`git tag v0.1.0 && git push --tags`) – GitHub Actions builds, tests and publishes
the Windows ZIP and the macOS DMG (same setup as Wing Theatre Controller). Ordinary pushes do not build;
*Actions → Build Q-Review → Run workflow* builds and tests without publishing.

Running from source:

```bash
pip install -r requirements.txt
python q_review.py
python q_review.py --selftest out   # automatic test: makes a test video, comments, trims, exports
```

## Structure

```
q_review.py              ← start
qreview/model.py         ← project, profiles, comments, .qreview files, Q-Recorder import
qreview/mainwindow.py    ← main window, player, menus, keys
qreview/panels.py        ← left side: profiles, writing comments, list, selected comment
qreview/timeline.py      ← timeline with tracks, drag, trim
qreview/videoview.py     ← video with draggable bubbles
qreview/overlay.py       ← draws the bubbles (preview and export use the same code)
qreview/exporter.py      ← TXT/SRT/CSV/JSON and the FFmpeg command
qreview/export_dialog.py ← export dialog with progress
qreview/media.py         ← FFmpeg: finding it, video info, waveform
qreview/selftest.py      ← automatic test (run by the build)
```

## Developers
- **Mikkel Peter Larsen**
- **Claude** (Anthropic — claude.ai)

Uses PyQt6 (Riverbank Computing / Qt) and FFmpeg (via imageio-ffmpeg).
