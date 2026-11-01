# Changelog

## 0.2.5 – 2026-11-01
- Export: if an export with the same name exists, Q-Review asks – *Replace*, *Keep both* (the new one gets a
  number) or *Cancel*. When replacing, the old video is kept until the new one is finished.
- The Windows installer is delivered as `Q-Review-Setup.zip`, because company networks often block downloads
  of .exe files. The installer inside is signed as before.

## 0.2.4 – 2026-11-01
- Windows installer (`Q-Review-Setup.exe`, signed): installs for all users or only you, Start menu entry,
  optional desktop icon, double-click on a `.qreview` project opens it, uninstall under *Settings → Apps*.
  The ZIP stays as a portable version.
- Autosave: a saved project is saved by itself a moment after each change (*File → Autosave*, on by default).
  Unsaved work is kept in a recovery file, and Q-Review offers to restore it if it was not closed properly.
- The window and panel sizes stay put (switching profile no longer moves them) and are remembered between
  starts; a saved project also remembers its window and panel sizes.
- Toolbar at the top: Open, Save, Comments on video, Look … and Export.
- No volume slider (more room on small screens) – *Playback → Mute* or M.
- The video follows the playhead closely while dragging it in the timeline and ends exactly where you let go.

## 0.2.3 – 2026-11-01
- The Windows version is signed (Azure Artifact Signing, "Mikkel Peter Larsen"), so Smart App Control
  lets it start. SmartScreen may still warn on the first downloads until the signature has built up reputation.

## 0.2.2 – 2026-10-24
- The macOS version is signed with Developer ID and notarised by Apple (app and DMG), so it opens with a
  normal double-click.
- If Q-Review fails to start, the reason is shown and written to a log file
  (Windows: %LOCALAPPDATA%\Q-Review\q-review.log, macOS: ~/Library/Logs/Q-Review). *Help → Show log file*.

## 0.2.1 – 2026-10-24
- The writing field is a card that stands out: border in the profile's colour (brighter while writing),
  title with the profile, the time large in yellow (🔒 while held), bigger text.
- Many more video formats: Qt's FFmpeg player is used on macOS too (MKV, AVI, WebM, MXF, MPEG-2, DV, MTS …);
  files with unknown endings are tried as video; interlaced video is deinterlaced and non-square pixels
  (PAL/NTSC 16:9) are shown correctly in the export; a playable copy is offered if the player shows no picture.
- Export: by default only PDF and video; the export always follows the trim (no checkbox any more).
- The text export is now a PDF: time, role with its colour and the comment, one row each (A4, page numbers).
- Deleting everything you have written works like Esc: playback continues and the time is no longer held.

## 0.2.0 – 2026-10-24
- One profile ("Notes") to start with – more under *Edit profiles*.
- The "Selected comment" box is gone: the tick on each comment decides "on video"; edit with double-click / F2,
  times by dragging in the timeline, the rest by right-click (incl. *Length …*).
- Transport: only nudge (one frame back / forward) and play.
- Lock in/out (*Lock* button or L).
- The out-point can reach the end of the video; the timeline stops at the end and scrolls while dragging at its edge.
- The writing field is at the bottom of the left side.
- *File → Save as folder with video*: one folder with the project and a copy of the video.
- Export can put everything in a new folder (on by default).
- Version number in the title bar and under *Help → About*.

## 0.1.0 – 2026-10-24
- First version: video, comments with profiles, timeline with drag and trim, bubbles on the video,
  projects (.qreview), Q-Recorder import, replace video, export (MP4 burned in / subtitle track, TXT, SRT, CSV, JSON).
