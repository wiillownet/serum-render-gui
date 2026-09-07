"""Palette, fonts and the application stylesheet.

Values are docs/design/qss-reference.md's, with its "QSS is not CSS" section
applied: inset shadows become a darker top border, fractional font sizes are
set on QFont (not in QSS), uppercase and letter-spacing are done in Python.
Focus is one global rule (docs/decisions.md).
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtGui import QFontDatabase, QFont, QGuiApplication

_ICONS = Path(__file__).parent / "icons"
_FONTS = Path(__file__).parent / "fonts"
APP_ICON = _ICONS / "app.png"


def load_fonts() -> list[str]:
    """Register the bundled IBM Plex faces so the app looks the same on a
    machine without them installed. Returns the family names registered."""
    families: list[str] = []
    for ttf in sorted(_FONTS.glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(ttf))
        if fid < 0:
            raise RuntimeError(f"Could not load bundled font {ttf.name}")
        families += QFontDatabase.applicationFontFamilies(fid)
    return families

# Palette. `stepper` and `off_line` are both #23262B on purpose.
ACCENT = "#A6E04D"
ACCENT_LINE = "#BCEA76"
ACCENT_DARK = "#7FBF33"
ACCENT_INK = "#17181A"
WARNING = "#E8A33D"
WARNING_DIM = "#C9954A"
WARNING_WASH = "rgba(232,163,61,0.09)"
STOP = "#D9534C"
STOP_LINE = "#E36B64"
TEXT = "#E6E7EA"
TEXT_VALUE = "#C9CBD1"
TEXT_DIM = "#8B8E97"
TEXT_FAINT = "#5C606A"
TEXT_HINT = "#4E525B"
PANEL = "#1F2126"
PANEL_HEADER = "#1A1C20"
WELL = "#111214"
WINDOW = "#151619"
RAISED = "#282B31"
RAISED_LINE = "#383C44"
STEPPER = "#23262B"
LINE = "#2C2F36"
LINE_TOP = "#232629"  # the "inset shadow" lip
FOCUS_LINE = "#4A4E57"
OFF_FILL = "#17181B"
OFF_LINE = "#23262B"
OFF_TEXT = "#3A3E46"
STEPPER_OFF = "#1B1D21"

SANS = ["IBM Plex Sans", "Helvetica Neue", "Arial"]
MONO = ["IBM Plex Mono", "Menlo", "Courier New"]


def _pt(px: float) -> float:
    """CSS px to Qt points on this screen. macOS reports 72 dpi, so px == pt
    there; the 96-dpi conversion in the reference is for other platforms.

    Fractional sizes are floored first: the font engine snaps 11.5 *up* to
    12 (measured), and the reference says round down, never up, because the
    26px row has no slack."""
    screen = QGuiApplication.primaryScreen()
    dpi = screen.logicalDotsPerInch() if screen else 96.0
    return math.floor(px) * 72.0 / dpi


def _weight(w: int) -> QFont.Weight:
    return QFont.Weight(w)


def sans(px: float, weight: int = 400) -> QFont:
    f = QFont(SANS)
    f.setPointSizeF(_pt(px))
    f.setWeight(_weight(weight))
    return f


def mono(px: float, weight: int = 400, spacing: float = 0.0) -> QFont:
    f = QFont(MONO)
    f.setPointSizeF(_pt(px))
    f.setWeight(_weight(weight))
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


# Disabled recipe, reused verbatim wherever a control locks.
_OFF = f"background: {OFF_FILL}; border: 1px solid {OFF_LINE}; color: {OFF_TEXT};"
_WELL = (
    f"background: {WELL}; border: 1px solid {LINE}; border-top-color: {LINE_TOP};"
    f" border-radius: 4px; color: {TEXT};"
)

QSS = f"""
QMainWindow, QWidget#central, QDialog {{ background: {WINDOW}; }}
QWidget {{ color: {TEXT}; }}
QLabel {{ background: transparent; }}
QLabel:disabled {{ color: {OFF_TEXT}; }}
QLabel#fieldLabel {{ color: {TEXT_DIM}; }}
QLabel#fieldLabel:disabled {{ color: {OFF_TEXT}; }}
QLabel#fieldLabel[state="warning"] {{ color: {WARNING}; }}
QLabel#fieldLabel[state="error"] {{ color: {STOP}; }}
QLabel#hint {{ color: {TEXT_FAINT}; }}
QLabel#body {{ color: {TEXT_DIM}; }}
QLabel#status {{ color: {TEXT_DIM}; }}
QLabel#status[tone="warning"] {{ color: {WARNING}; }}
QLabel#sectionTitle {{ color: {TEXT_FAINT}; }}
QLabel#sectionTitle[modified="true"] {{ color: {WARNING}; }}
QLabel#summary {{ color: {TEXT_HINT}; }}
QLabel#unit {{ color: {TEXT_FAINT}; background: {WELL}; }}
QLabel#unit:disabled {{ background: {OFF_FILL}; }}

QFrame#section {{
  background: {PANEL}; border: 1px solid {LINE}; border-top-color: #303338;
  border-radius: 6px;
}}
QWidget#sectionHeader {{
  background: {PANEL_HEADER};
  border-top-left-radius: 6px; border-top-right-radius: 6px;
}}
QWidget#sectionHeader[expanded="true"] {{ border-bottom: 1px solid {LINE}; }}
QWidget#sectionHeader[expanded="false"] {{
  border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ {_WELL} padding: 0 8px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QLineEdit[dragging="true"] {{ border: 1px solid {FOCUS_LINE}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ {_OFF} }}
QLineEdit:read-only {{ {_OFF} }}
QLineEdit {{ selection-background-color: {RAISED_LINE}; }}
QComboBox {{ padding: 0 6px 0 8px; }}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
  background: {PANEL}; border: 1px solid {RAISED_LINE}; border-radius: 5px;
  padding: 4px; outline: none; selection-background-color: {RAISED};
}}
QComboBox QAbstractItemView::item {{ height: 24px; padding: 0 9px; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QToolButton#step {{
  background: {STEPPER}; border: 1px solid {LINE}; padding: 0;
}}
QToolButton#step[half="up"] {{ border-bottom: none; border-top-left-radius: 3px; border-top-right-radius: 3px; }}
QToolButton#step[half="down"] {{ border-bottom-left-radius: 3px; border-bottom-right-radius: 3px; }}
QToolButton#step:disabled {{ background: {STEPPER_OFF}; border-color: {OFF_LINE}; }}
QToolButton#step:hover {{ background: #2A2E34; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{
  width: 15px; height: 15px; border-radius: 3px;
  background: {WELL}; border: 1px solid {LINE}; border-top-color: {LINE_TOP};
}}
QCheckBox::indicator:hover {{ border-color: {RAISED_LINE}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT_LINE}; image: url({_ICONS / "tick.svg"}); }}
QCheckBox::indicator:disabled {{ background: {OFF_FILL}; border: 1px solid {OFF_LINE}; }}
QCheckBox::indicator:checked:disabled {{ image: url({_ICONS / "tick-off.svg"}); }}
QCheckBox:disabled {{ color: {OFF_TEXT}; }}
QCheckBox:focus {{ outline: none; }}
QCheckBox::indicator:focus {{ border: 1px solid {FOCUS_LINE}; }}

QPushButton {{
  background: {RAISED}; color: {TEXT}; border: 1px solid {RAISED_LINE};
  border-radius: 5px; padding: 0 12px; font-size: 12px;
}}
QPushButton:hover {{ background: #31353C; }}
QPushButton:pressed {{ background: {STEPPER}; }}
QPushButton:focus {{ border: 1px solid {FOCUS_LINE}; outline: none; }}
QPushButton:disabled {{ {_OFF} }}
QPushButton#primary {{
  background: {ACCENT}; color: {ACCENT_INK}; border: 1px solid {ACCENT_LINE};
  font-weight: 600; padding: 0 22px; min-width: 48px;
}}
QPushButton#primary:hover {{ background: #B4E663; }}
QPushButton#primary:pressed {{ background: #94CC42; }}
QPushButton#primary:disabled {{ {_OFF} }}
QPushButton#stop {{
  background: {STOP}; color: #FFFFFF; border: 1px solid {STOP_LINE};
  font-weight: 600; padding: 0 22px; min-width: 48px;
}}
QPushButton#stop:hover {{ background: #E0625B; }}
QPushButton#stop:pressed {{ background: #C4453E; }}
QPushButton#dialog {{ padding: 0 18px; min-width: 56px; }}
QPushButton#footer {{ padding: 0 14px; }}

QToolButton {{
  background: {RAISED}; border: 1px solid {RAISED_LINE}; border-radius: 5px; padding: 0;
}}
QToolButton:hover {{ background: #31353C; }}
QToolButton:pressed {{ background: {STEPPER}; }}
QToolButton:focus {{ border: 1px solid {FOCUS_LINE}; outline: none; }}
QToolButton:disabled {{ {_OFF} }}
QToolButton#bare, QToolButton#bare:disabled {{ background: transparent; border: none; }}
QToolButton#bare:focus {{ border: 1px solid {FOCUS_LINE}; }}
QToolButton#chip {{ background: transparent; border: none; }}

QProgressBar {{
  background: {WELL}; border: none; border-radius: 2px;
}}
QProgressBar::chunk {{
  border-radius: 2px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_DARK}, stop:1 {ACCENT});
}}
QProgressBar[stopped="true"]::chunk {{ background: {TEXT_FAINT}; }}

QTableWidget {{
  background: {PANEL}; border: 1px solid {LINE}; border-radius: 6px;
  gridline-color: transparent; outline: none;
}}
QTableWidget::item {{ padding: 0 14px; border-top: 1px solid {LINE}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
  background: {PANEL_HEADER}; padding: 0 14px; border: none; color: {TEXT_FAINT};
}}
QTableCornerButton::section {{ background: {PANEL_HEADER}; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {RAISED_LINE}; border-radius: 4px; min-height: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {RAISED_LINE}; border-radius: 4px; min-width: 20px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QMenu {{
  background: {PANEL}; border: 1px solid {RAISED_LINE}; border-radius: 5px; padding: 4px;
}}
QMenu::item {{ height: 24px; padding: 0 9px; border-radius: 3px; color: {TEXT}; }}
QMenu::item:selected {{ background: {RAISED}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 3px 4px; }}

QToolTip {{
  background: {STEPPER}; border: 1px solid {FOCUS_LINE}; border-radius: 5px;
  padding: 9px 11px; color: {TEXT_VALUE}; font-size: 11px;
}}

QFrame#profileRow {{ border-top: 1px solid {LINE}; background: transparent; }}
QFrame#profileRow[amber="true"] {{ background: {WARNING_WASH}; }}
QWidget#listHeader {{ background: {PANEL_HEADER}; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
QFrame#list {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 6px; }}
QLabel#badge {{
  border: 1.5px solid {WARNING}; border-radius: 13px; color: {WARNING}; background: transparent;
}}
"""
