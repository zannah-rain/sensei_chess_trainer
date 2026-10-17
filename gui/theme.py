"""
A single app-wide QSS stylesheet, applied once to MainWindow (Qt stylesheets
cascade to all descendant widgets). Deliberately scoped with object names
(#actionButton, #statsCard, ...) rather than bare type selectors like
"QPushButton" - the chessboard squares (gui/square.py's Square, a QPushButton
subclass that sets its own inline background colour per-square) must not pick
up padding/border-radius/colour meant for the app's real buttons.
"""

ACCENT = "#4caf7d"
ACCENT_BRIGHT = "#5fe3a4"
BACKGROUND = "#1b1e24"
PANEL = "#242933"
PANEL_LIGHT = "#2d333f"
TEXT = "#e8eaed"
TEXT_DIM = "#9aa4b2"
BORDER = "#3a4150"

MAIN_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT};
    font-size: 13px;
}}

QLabel {{
    background: transparent;
}}

QLabel#statsCard {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

QLabel#streakLabel {{
    color: {ACCENT_BRIGHT};
    font-weight: 600;
    font-size: 14px;
}}

QLabel#comboLabel {{
    color: #ffc107;
    font-weight: 600;
    font-size: 14px;
}}

QLabel#badgesLabel {{
    color: {TEXT_DIM};
    padding: 4px 0px;
}}

QPushButton#actionButton {{
    background-color: {ACCENT};
    color: #0c120f;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}}

QPushButton#actionButton:hover {{
    background-color: {ACCENT_BRIGHT};
}}

QPushButton#actionButton:pressed {{
    background-color: #3c8f64;
}}

QPushButton#actionButton:disabled {{
    background-color: {PANEL_LIGHT};
    color: {TEXT_DIM};
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background-color: {PANEL};
}}

QTabBar::tab {{
    background-color: {BACKGROUND};
    color: {TEXT_DIM};
    padding: 6px 14px;
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}

QTabBar::tab:selected {{
    background-color: {PANEL};
    color: {TEXT};
}}

QProgressBar {{
    background-color: {PANEL_LIGHT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: center;
    color: {TEXT};
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 6px;
}}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {PANEL_LIGHT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}

QStatusBar {{
    background-color: {PANEL};
    color: {TEXT_DIM};
}}
"""
