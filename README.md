# Q-Review

Comments on video – the review part of Q-Recorder as a stand-alone app for **Windows** (and macOS).

- **Open** a video, a Q-Review project or a Q-Recorder recording (the `.json` log next to the `.mov`).
  Q-Recorder's chat notes become comments, its roles become profiles. The recording itself is never changed.
- **Write comments** on the left – as a *profile* (Director, Lighting, Sound, Stage manager … like Q-Recorder's roles).
  The time is held from the moment you start writing, and playback pauses while you write (can be switched off).
- **Timeline**: one track per profile. Drag comments to move them (also to another profile), drag the edges to change
  the length. Comments snap to the playhead, the trim and each other (hold Alt to turn snapping off).
- **On the video**: comments are shown as bubbles like Q-Recorder's chat block (bottom left). Drag a bubble to place it
  anywhere; right-click → *Automatic position* puts it back. *Comments on video* turns them all on/off,
  each comment and each profile can also be switched off.
- **Trim**: drag the yellow handles in the timeline, or press **I** / **O** at the playhead. Nothing is cut until you export.
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
| Home / End | Go to in / out point |
| Enter | Write a new comment (Enter adds it, Shift+Enter = new line, Esc = cancel) |
| Ctrl+1 … 9 | Choose profile |
| F2 / Delete | Edit / delete the selected comment |
| Ctrl+T | Comments on video on/off |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Ctrl+wheel | Zoom the timeline |

## Files

- `<name>.qreview` – the project (JSON): video path (absolute and relative), trim, profiles, comments.
  Times are always in the original video's time; the export takes care of the trim.

## Download

See [Releases](../../releases). Windows: unzip `Q-Review-windows.zip` and run `Q-Review.exe` (FFmpeg is included).

## Building

Push a tag (`git tag v0.1.0 && git push --tags`) – GitHub Actions builds, tests and publishes
the Windows ZIP and the macOS DMG (same setup as Wing Theatre Controller). Every push to `main` builds and tests
too; the files are under *Actions → the run → Artifacts*.

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
