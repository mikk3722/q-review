"""Dark look, close to Q-Recorder on macOS."""
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory

QSS = """
QMainWindow, QDialog { background:#1c1c1e; }
QWidget { color:#f2f2f7; }
QToolTip { background:#2c2c2e; color:#f2f2f7; border:1px solid #3a3a3c; padding:4px; }
QGroupBox { border:1px solid #3a3a3c; border-radius:8px; margin-top:10px; padding-top:6px; }
QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 4px; color:#9a9aa0; }
QPlainTextEdit, QLineEdit, QListWidget, QComboBox, QDoubleSpinBox, QSpinBox {
    background:#2c2c2e; border:1px solid #3a3a3c; border-radius:6px; padding:3px; selection-background-color:#0a84ff; }
QPlainTextEdit:focus, QLineEdit:focus { border:1px solid #0a84ff; }
QListWidget { padding:0; }
QPushButton, QToolButton { background:#3a3a3c; border:1px solid #48484a; border-radius:6px; padding:4px 10px; }
QPushButton:hover, QToolButton:hover { background:#48484a; }
QPushButton:pressed, QToolButton:pressed { background:#2c2c2e; }
QPushButton:disabled, QToolButton:disabled { color:#636366; }
QPushButton#primary { background:#0a84ff; border-color:#0a84ff; font-weight:600; }
QPushButton#primary:hover { background:#409cff; }
QFrame#transport { background:#232326; border-top:1px solid #000; }
QWidget#welcome { background:#111113; }
QSplitter::handle { background:#000; }
QSplitter::handle:horizontal { width:2px; }
QSplitter::handle:vertical { height:2px; }
QMenuBar { background:#232326; }
QMenuBar::item:selected { background:#3a3a3c; }
QMenu { background:#2c2c2e; border:1px solid #3a3a3c; }
QMenu::item:selected { background:#0a84ff; }
QStatusBar { background:#232326; color:#9a9aa0; }
QProgressBar { background:#2c2c2e; border:1px solid #3a3a3c; border-radius:5px; text-align:center; height:16px; }
QProgressBar::chunk { background:#0a84ff; border-radius:4px; }
QScrollBar:horizontal { height:12px; background:#1b1b1d; }
QScrollBar:vertical { width:12px; background:#1b1b1d; }
QScrollBar::handle { background:#48484a; border-radius:5px; min-width:30px; min-height:30px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
"""


def apply(app: QApplication):
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#1c1c1e"), (QPalette.ColorRole.WindowText, "#f2f2f7"),
        (QPalette.ColorRole.Base, "#2c2c2e"), (QPalette.ColorRole.AlternateBase, "#252528"),
        (QPalette.ColorRole.Text, "#f2f2f7"), (QPalette.ColorRole.Button, "#3a3a3c"),
        (QPalette.ColorRole.ButtonText, "#f2f2f7"), (QPalette.ColorRole.Highlight, "#0a84ff"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, "#2c2c2e"),
        (QPalette.ColorRole.ToolTipText, "#f2f2f7"), (QPalette.ColorRole.PlaceholderText, "#8e8e93"),
        (QPalette.ColorRole.Link, "#409cff"),
    ):
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#636366"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#636366"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#636366"))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
