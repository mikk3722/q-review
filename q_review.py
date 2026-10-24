"""Q-Review – comments on video (Windows and macOS).

Run:        python q_review.py [file]
Self-test:  python q_review.py --selftest <output folder>
"""
import os
import sys


def main():
    if "--selftest" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QApplication
    from qreview import style
    from qreview.model import APP_NAME

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

    from qreview.mainwindow import MainWindow
    win = MainWindow()
    win.show()
    files = [a for a in sys.argv[1:] if not a.startswith("-") and os.path.exists(a)]
    if files:
        win.open_any(os.path.abspath(files[0]), asked=True)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
