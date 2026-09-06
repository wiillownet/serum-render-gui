"""Widgets shared by the main window and the dialogs.

One ElidingLabel, one PathField, one Section, one stepper spin box. Every
recipe the design repeats lives here once. See docs/design/CORRECTIONS.md
section 6 for the Qt facts these work around.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import style

# ---- Icons ----------------------------------------------------------------

# Line-art glyphs as (stroke width, list of polylines in a 0..1 unit box).
# Close enough to the SVGs; the shapes are simple enough to draw by hand.
_GLYPHS: dict[str, tuple[float, list[list[tuple[float, float]]]]] = {
    "chevron-right": (1.3, [[(0.35, 0.2), (0.65, 0.5), (0.35, 0.8)]]),
    "chevron-down": (1.3, [[(0.2, 0.35), (0.5, 0.65), (0.8, 0.35)]]),
    "chevrons": (1.2, [[(0.3, 0.38), (0.5, 0.18), (0.7, 0.38)], [(0.3, 0.62), (0.5, 0.82), (0.7, 0.62)]]),
    "up": (1.1, [[(0.2, 0.68), (0.5, 0.32), (0.8, 0.68)]]),
    "down": (1.1, [[(0.2, 0.32), (0.5, 0.68), (0.8, 0.32)]]),
    "tick": (1.5, [[(0.1, 0.55), (0.4, 0.85), (0.9, 0.2)]]),
    "clear": (1.3, [[(0.25, 0.25), (0.75, 0.75)], [(0.75, 0.25), (0.25, 0.75)]]),
    "folder": (1.2, [
        [(0.1, 0.3), (0.1, 0.85), (0.9, 0.85), (0.9, 0.4), (0.5, 0.4), (0.4, 0.3), (0.1, 0.3)],
        [(0.45, 0.62), (0.7, 0.62)], [(0.6, 0.52), (0.7, 0.62), (0.6, 0.72)],
    ]),
    "revert": (1.5, [[(0.35, 0.2), (0.15, 0.4), (0.35, 0.6)], [(0.15, 0.4), (0.65, 0.4), (0.8, 0.55), (0.8, 0.65), (0.65, 0.8), (0.35, 0.8)]]),
    "save": (1.2, [
        [(0.15, 0.15), (0.7, 0.15), (0.85, 0.3), (0.85, 0.85), (0.15, 0.85), (0.15, 0.15)],
        [(0.3, 0.15), (0.3, 0.4), (0.65, 0.4), (0.65, 0.15)], [(0.3, 0.85), (0.3, 0.6), (0.7, 0.6), (0.7, 0.85)],
    ]),
    "gear": (1.25, [
        [(0.5, 0.1), (0.5, 0.22)], [(0.5, 0.78), (0.5, 0.9)], [(0.1, 0.5), (0.22, 0.5)], [(0.78, 0.5), (0.9, 0.5)],
        [(0.22, 0.22), (0.3, 0.3)], [(0.7, 0.7), (0.78, 0.78)], [(0.78, 0.22), (0.7, 0.3)], [(0.3, 0.7), (0.22, 0.78)],
    ]),
    "duplicate": (1.2, [
        [(0.35, 0.35), (0.85, 0.35), (0.85, 0.85), (0.35, 0.85), (0.35, 0.35)],
        [(0.65, 0.35), (0.65, 0.15), (0.15, 0.15), (0.15, 0.65), (0.35, 0.65)],
    ]),
    "rename": (1.2, [[(0.15, 0.85), (0.35, 0.85), (0.85, 0.35), (0.65, 0.15), (0.15, 0.65), (0.15, 0.85)], [(0.55, 0.25), (0.75, 0.45)]]),
    "delete": (1.2, [
        [(0.15, 0.28), (0.85, 0.28)], [(0.38, 0.28), (0.38, 0.15), (0.62, 0.15), (0.62, 0.28)],
        [(0.25, 0.28), (0.3, 0.88), (0.7, 0.88), (0.75, 0.28)], [(0.43, 0.42), (0.43, 0.75)], [(0.57, 0.42), (0.57, 0.75)],
    ]),
}


def glyph_pixmap(name: str, color: str, size: int, box: QSize | None = None) -> QPixmap:
    """A glyph rendered at 2x for retina. `box` is the pixmap size when the
    glyph is not square (chevrons are 9x12, the tick 10x8)."""
    box = box or QSize(size, size)
    pm = QPixmap(box * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    width, lines = _GLYPHS[name]
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    w, h = box.width(), box.height()
    for line in lines:
        path = QPainterPath(QPointF(line[0][0] * w, line[0][1] * h))
        for x, y in line[1:]:
            path.lineTo(x * w, y * h)
        p.drawPath(path)
    if name == "gear":
        p.drawEllipse(QPointF(w / 2, h / 2), w * 0.28, h * 0.28)
        p.drawEllipse(QPointF(w / 2, h / 2), w * 0.1, h * 0.1)
    p.end()
    return pm


def icon(name: str, color: str = style.TEXT_DIM, size: int = 14,
         box: QSize | None = None) -> QIcon:
    ic = QIcon()
    ic.addPixmap(glyph_pixmap(name, color, size, box), QIcon.Mode.Normal)
    ic.addPixmap(glyph_pixmap(name, style.OFF_TEXT, size, box), QIcon.Mode.Disabled)
    return ic


# ---- Small factories ------------------------------------------------------


def field_label(text: str, width: int, tooltip: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("fieldLabel")
    lab.setFixedSize(width, 26)
    lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    lab.setFont(style.sans(11))
    if tooltip:
        lab.setToolTip(tooltip)
    return lab


def set_state(widget: QWidget, prop: str, value) -> None:
    """Set a dynamic property and force the stylesheet to re-evaluate it."""
    widget.setProperty(prop, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def push_button(text: str, height: int = 26, kind: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setFixedHeight(height)
    b.setFont(style.sans(12, 600 if kind in ("primary", "stop") else 400))
    if kind:
        b.setObjectName(kind)
    b.setAutoDefault(False)
    b.setDefault(False)
    b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return b


def tool_button(name: str, size: int | tuple[int, int] = 26, glyph: int = 13,
                bare: bool = False, color: str = style.TEXT_DIM) -> QToolButton:
    b = QToolButton()
    w, h = (size, size) if isinstance(size, int) else size
    b.setFixedSize(w, h)
    b.setIcon(icon(name, color, glyph))
    b.setIconSize(QSize(glyph, glyph))
    if bare:
        b.setObjectName("bare")
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    return b


def check_box(text: str, tooltip: str = "") -> QCheckBox:
    cb = QCheckBox(text)
    cb.setFixedHeight(26)
    cb.setFont(style.sans(11.5))
    if tooltip:
        cb.setToolTip(tooltip)
    return cb


def combo(items: list[str], tooltip: str = "") -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    c.setFixedHeight(26)
    c.setFont(style.mono(11.5, 500))
    c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    if tooltip:
        c.setToolTip(tooltip)
    _Chevrons(c)
    return c


class _Chevrons(QLabel):
    """The double chevron at the right of a combo, drawn as a child label so
    the QSS drop-down can stay empty."""

    def __init__(self, parent: QComboBox) -> None:
        super().__init__(parent)
        self.setPixmap(glyph_pixmap("chevrons", style.TEXT_DIM, 12, QSize(9, 12)))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        parent.installEventFilter(self)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.EnabledChange):
            self.move(obj.width() - 9 - 7, (obj.height() - 12) // 2)
            color = style.TEXT_DIM if obj.isEnabled() else style.OFF_TEXT
            self.setPixmap(glyph_pixmap("chevrons", color, 12, QSize(9, 12)))
        return False


# ---- ElidingLabel ---------------------------------------------------------


class ElidingLabel(QLabel):
    """A QLabel that elides from the stored original string (never from what
    is displayed) and does not push its row wider than the layout allows."""

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(1)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self._relayout()

    def full_text(self) -> str:
        return self._full

    def setFont(self, font) -> None:  # noqa: N802
        super().setFont(font)
        self._relayout()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._relayout()

    def _relayout(self) -> None:
        width = max(self.contentsRect().width(), 6)
        super().setText(QFontMetrics(self.font()).elidedText(self._full, self._mode, width))


# ---- PathField ------------------------------------------------------------


class PathField(QLineEdit):
    """A path QLineEdit: drop target, resolved tick, tail-visible.

    `folder=True` rows take a dropped file's containing directory. The tick
    means "this path resolves" and nothing more; `set_resolved` decides.
    """

    path_changed = Signal(str)

    def __init__(self, placeholder: str, folder: bool) -> None:
        super().__init__()
        self._folder = folder
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(26)
        self.setFont(style.mono(11.5, 500))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAcceptDrops(True)
        self._tick = QAction(icon("tick", style.ACCENT, 10, QSize(10, 8)), "", self)
        self._tick_shown = False
        self.editingFinished.connect(self._finished)

    def path(self) -> str:
        return self.text().strip()

    def set_path(self, text: str) -> None:
        self.setText(text)
        self.setToolTip(text)
        self.setCursorPosition(len(text))
        self.path_changed.emit(text)

    def set_resolved(self, ok: bool) -> None:
        # QAction.setVisible does not hide a QLineEdit's trailing icon on
        # 6.11; adding and removing the action does.
        if ok and not self._tick_shown:
            self.addAction(self._tick, QLineEdit.ActionPosition.TrailingPosition)
        elif not ok and self._tick_shown:
            self.removeAction(self._tick)
        self._tick_shown = ok

    def _finished(self) -> None:
        self.set_path(self.path())

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            set_state(self, "dragging", True)
            ev.acceptProposedAction()

    def dragLeaveEvent(self, ev) -> None:
        set_state(self, "dragging", False)

    def dropEvent(self, ev) -> None:
        set_state(self, "dragging", False)
        urls = ev.mimeData().urls()
        if not urls:
            return
        p = Path(urls[0].toLocalFile())
        if self._folder and p.is_file():
            p = p.parent
        self.set_path(str(p))
        ev.acceptProposedAction()


# ---- Spin box with a sibling stepper --------------------------------------


class _SuffixLabel(QLabel):
    """Unit text inside a spin box, right-aligned, in the faint mono face.
    QSpinBox.setSuffix cannot be styled separately (qss-reference #14)."""

    def __init__(self, spin: QAbstractSpinBox, text: str) -> None:
        super().__init__(text, spin)
        self.setObjectName("unit")
        self.setFont(style.mono(10))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        spin.installEventFilter(self)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.adjustSize()
            self.move(obj.width() - self.width() - 9, (obj.height() - self.height()) // 2)
        return False


def spin_box(lo, hi, value, suffix: str = "", decimals: int | None = None,
             tooltip: str = "") -> tuple[QAbstractSpinBox, QWidget]:
    """A well-styled spin box and its 14px stepper column. Lay them out with
    5px between; the stepper is a sibling, not a subcontrol."""
    spin = QSpinBox() if decimals is None else QDoubleSpinBox()
    if decimals is not None:
        spin.setDecimals(decimals)
        spin.setSingleStep(0.1)
    spin.setRange(lo, hi)
    spin.setValue(value)
    spin.setFixedHeight(26)
    spin.setFont(style.mono(11.5, 500))
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    if tooltip:
        spin.setToolTip(tooltip)
    label = _SuffixLabel(spin, suffix)
    spin.suffix_label = label  # type: ignore[attr-defined]

    stepper = QWidget()
    stepper.setFixedSize(14, 22)
    lay = QVBoxLayout(stepper)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for half, name, fn in (("up", "up", spin.stepUp), ("down", "down", spin.stepDown)):
        b = QToolButton()
        b.setObjectName("step")
        b.setProperty("half", half)
        b.setFixedSize(14, 11)
        b.setIcon(icon(name, style.TEXT_DIM, 7, QSize(7, 4)))
        b.setIconSize(QSize(7, 4))
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setAutoRepeat(True)
        b.clicked.connect(fn)
        lay.addWidget(b)
    # Lock the stepper with the field; the buttons are not the spin's own.
    spin.installEventFilter(_EnableMirror(spin, stepper))
    return spin, stepper


class _EnableMirror(QObject):
    def __init__(self, source: QWidget, target: QWidget) -> None:
        super().__init__(source)
        self._target = target

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() == QEvent.Type.EnabledChange:
            self._target.setEnabled(obj.isEnabled())
        return False


# ---- Section --------------------------------------------------------------


class _Header(QWidget):
    clicked = Signal()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class Section(QFrame):
    """A collapsible group: 24px header strip plus a body. The header is the
    whole click target. The Profile section is built with collapsible=False."""

    toggled = Signal(bool)

    def __init__(self, title: str, collapsible: bool = True,
                 summary_mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> None:
        super().__init__()
        self.setObjectName("section")
        self._collapsible = collapsible
        self._expanded = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = _Header()
        self.header.setObjectName("sectionHeader")
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(12, 6, 12, 6)
        hl.setSpacing(8)
        self.chevron = QLabel()
        self.chevron.setFixedSize(10, 10)
        self.dot = QLabel()
        self.dot.setFixedSize(5, 5)
        self.dot.setStyleSheet(f"background: {style.WARNING}; border-radius: 2px;")
        self.dot.setVisible(False)
        self.title = QLabel(title.upper())
        self.title.setObjectName("sectionTitle")
        self.title.setFont(style.mono(9.5, 500, spacing=1.1))
        self.summary = ElidingLabel("", summary_mode)
        self.summary.setObjectName("summary")
        self.summary.setFont(style.mono(10.5))
        self.summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.summary.setVisible(False)
        if collapsible:
            hl.addWidget(self.chevron)
        hl.addWidget(self.dot)
        hl.addWidget(self.title)
        hl.addWidget(self.summary, 1)
        outer.addWidget(self.header)

        self.body = QWidget()
        outer.addWidget(self.body)
        if collapsible:
            self.header.clicked.connect(lambda: self.set_expanded(not self._expanded))
        self._apply()

    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, on: bool) -> None:
        if not self._collapsible:
            on = True
        if on == self._expanded:
            return
        self._expanded = on
        self._apply()
        self.toggled.emit(on)

    def _apply(self) -> None:
        # 24, plus the 1px bottom rule the header owns only while expanded.
        self.header.setFixedHeight(25 if self._expanded else 24)
        self.body.setVisible(self._expanded)
        self.summary.setVisible(not self._expanded)
        self.chevron.setPixmap(glyph_pixmap(
            "chevron-down" if self._expanded else "chevron-right", style.TEXT_FAINT, 10))
        set_state(self.header, "expanded", self._expanded)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def set_modified(self, on: bool) -> None:
        self.dot.setVisible(on)
        set_state(self.title, "modified", on)

    def set_locked(self, locked: bool, keep: tuple[QWidget, ...] = ()) -> None:
        """Disable every control in the body except `keep` (the reveal
        buttons). Not setEnabled on the section: that kills the toggle."""
        for w in self.body.findChildren(QWidget):
            if w in keep or isinstance(w, (_SuffixLabel, _Chevrons)) or w.objectName() == "step":
                continue
            if isinstance(w, (QLineEdit, QAbstractSpinBox, QComboBox, QCheckBox,
                              QPushButton, QToolButton, QLabel)):
                if w.property("lock_exempt"):
                    continue
                if locked:
                    w.setProperty("was_enabled", w.isEnabled())
                    w.setEnabled(False)
                else:
                    w.setEnabled(bool(w.property("was_enabled")))
