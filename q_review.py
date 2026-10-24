"""Q-Review – comments on video (Windows and macOS).

Run:        python q_review.py [file]
Self-test:  python q_review.py --selftest <output folder>

If the app fails to start, the reason is written to a log file and shown in a message:
  Windows: %LOCALAPPDATA%\\Q-Review\\q-review.log
  macOS:   ~/Library/Logs/Q-Review/q-review.log
"""
import os
import sys
import traceback
from datetime import datetime

LOG_PATH = None
_log = None


def log_folder() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Q-Review")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Logs/Q-Review")
    return os.path.expanduser("~/.q-review")


def open_log():
    """A fresh log for every start (the previous one is kept as q-review.old.log)."""
    global LOG_PATH, _log
    try:
        folder = log_folder()
        os.makedirs(folder, exist_ok=True)
        LOG_PATH = os.path.join(folder, "q-review.log")
        if os.path.exists(LOG_PATH):
            os.replace(LOG_PATH, os.path.join(folder, "q-review.old.log"))
        _log = open(LOG_PATH, "w", encoding="utf-8", buffering=1)
    except Exception:
        _log = None


def log(msg: str):
    if _log:
        try:
            _log.write(f"{datetime.now().strftime('%H:%M:%S')}  {msg}\n")
        except Exception:
            pass


def show_fatal(text: str):
    """Shows the error even when Qt itself could not start."""
    full = f"Q-Review could not start.\n\n{text}\n\nLog: {LOG_PATH}"
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "Q-Review", full)
            return
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, full, "Q-Review", 0x10)
            return
        except Exception:
            pass
    print(full, file=sys.stderr)


def excepthook(kind, value, tb):
    text = "".join(traceback.format_exception(kind, value, tb))
    log("UNCAUGHT EXCEPTION\n" + text)
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None and "--selftest" not in sys.argv:
            QMessageBox.warning(None, "Q-Review", f"Something went wrong:\n\n{value}\n\nDetails are in the log:\n{LOG_PATH}")
    except Exception:
        pass


def main():
    open_log()
    import platform
    log(f"Start – {' '.join(sys.argv)}")
    log(f"Python {sys.version.split()[0]} · {platform.platform()} · machine {platform.machine()} · "
        f"frozen={getattr(sys, 'frozen', False)}")
    try:
        import faulthandler
        if _log:
            faulthandler.enable(file=_log)   # hard crashes (e.g. in a Qt library) end up in the log too
    except Exception:
        pass
    sys.excepthook = excepthook

    if "--selftest" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt6.QtCore import QCoreApplication, QLibraryInfo, qInstallMessageHandler, QT_VERSION_STR, PYQT_VERSION_STR
    except Exception as e:
        log("Could not load Qt:\n" + traceback.format_exc())
        show_fatal(f"Qt could not be loaded: {e}")
        sys.exit(1)
    log(f"Qt {QT_VERSION_STR} · PyQt {PYQT_VERSION_STR}")

    def qt_messages(mode, context, message):
        log(f"Qt: {message}")
    qInstallMessageHandler(qt_messages)

    # Use Qt's FFmpeg player on every platform (also macOS, where the default only plays what macOS plays),
    # so MKV, AVI, WebM, MXF, MPEG-2, DV … play too. Only if the FFmpeg plugin is there.
    if "QT_MEDIA_BACKEND" not in os.environ:
        try:
            plugins = os.path.join(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath), "multimedia")
            found = os.listdir(plugins)
            log(f"Multimedia plugins: {found}")
            if any("ffmpeg" in n.lower() for n in found):
                os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"
        except OSError as e:
            log(f"No multimedia plugin folder: {e}")

    try:
        from PyQt6.QtWidgets import QApplication
        from qreview import style, __version__
        from qreview.model import APP_NAME
        log(f"Q-Review {__version__}")

        QCoreApplication.setOrganizationName("MikkelPeterLarsen")
        QCoreApplication.setOrganizationDomain("mikkelpeterlarsen.dk")
        QCoreApplication.setApplicationName(APP_NAME)
        if sys.platform == "win32":
            try:   # own taskbar icon/group instead of python.exe
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("dk.mikkelpeterlarsen.qreview")
            except Exception:
                pass
        app = QApplication(sys.argv)
        log(f"Qt platform: {app.platformName()}")
        style.apply(app)
        from PyQt6.QtGui import QIcon
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        icon = os.path.join(base, "assets", "icon.png")
        if os.path.exists(icon):
            app.setWindowIcon(QIcon(icon))

        if "--selftest" in sys.argv:
            from qreview.selftest import run
            i = sys.argv.index("--selftest")
            out = sys.argv[i + 1] if len(sys.argv) > i + 1 else "selftest-output"
            sys.exit(run(app, out))

        from qreview import media
        log(f"FFmpeg: {media.ffmpeg_path()}")
        from qreview.mainwindow import MainWindow
        win = MainWindow()
        win.show()
        log("Window shown")
        files = [a for a in sys.argv[1:] if not a.startswith("-") and os.path.exists(a)]
        if files:
            win.open_any(os.path.abspath(files[0]), asked=True)
        code = app.exec()
        log(f"Quit ({code})")
        sys.exit(code)
    except SystemExit:
        raise
    except Exception as e:
        log("Start failed:\n" + traceback.format_exc())
        show_fatal(f"{type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
