"""The main window: profile strip, four collapsible sections, and the footer
row that carries the whole render lifecycle.

Window sizing lives in one method, `_fit`. The window's height changes only
there, and only when a section is toggled.
"""
from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QSizePolicy,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from serum_render.config import plugin_path_looks_valid
from serum_render.formats import PresetFormat

from . import strings as S
from . import style
from .dialogs import ProfileManager, SaveProfileDialog, SetupSheet, TableDialog, UnsavedDialog
from .planner import Library, Plan, RenderParams, _EXTENSION_FOR, compose_fast, plan, scan
from .profiles import PROFILE_KEYS, ProfileStore, built_in_values
from .runner import RenderRunner
from .widgets import (
    ElidingLabel,
    PathField,
    Section,
    check_box,
    combo,
    field_label,
    icon,
    push_button,
    set_state,
    spin_box,
    tool_button,
)

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_SAMPLE_RATES = ["44100", "48000", "88200", "96000"]
_BIT_DEPTHS = ["16", "24", "32f"]
_FORMATS = ["WAV", "NPY"]
_FORMAT_PREFIX = "{format}/"
_EXAMPLE_TOKENS = {"{preset}": "Deep_Sub_01", "{folder}": "Bass", "{subpath}": "Bass",
                   "{subdir}": "Bass", "{format}": "serum1"}
SECTION_KEYS = {
    "sound": ("note", "velocity", "duration", "tail", "midi_path"),
    "audio": ("sample_rate", "bit_depth", "output_format", "deterministic"),
    "files": ("filename_template", "no_recurse"),
}


def note_name(n: int) -> str:
    return f"{_NOTE_NAMES[n % 12]}{n // 12 - 1}"


class ProfileCombo(QComboBox):
    """The profile name in mono, with an amber `(modified)` run drawn after
    it. A plain QComboBox renders one string in one colour."""

    def __init__(self) -> None:
        super().__init__()
        self.display = ""
        self.modified = False
        self.setFixedHeight(26)
        self.setFont(style.mono(11.5, 500))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, ev) -> None:
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = ""
        p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        rect = self.rect().adjusted(9, 0, -24, 0)
        fm = p.fontMetrics()
        suffix = f" {S.MODIFIED}" if self.modified else ""
        avail = rect.width() - fm.horizontalAdvance(suffix)
        name = fm.elidedText(self.display, Qt.TextElideMode.ElideRight, avail)
        p.setPen(QColor(style.TEXT if self.isEnabled() else style.OFF_TEXT))
        p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        if suffix:
            rect2 = rect.adjusted(fm.horizontalAdvance(name), 0, 0, 0)
            p.setPen(QColor(style.WARNING if self.isEnabled() else style.OFF_TEXT))
            p.drawText(rect2, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, suffix)


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings, store: ProfileStore) -> None:
        super().__init__()
        self.setWindowTitle("serum-render")
        self.settings = settings
        settings.setParent(self)  # outlive-the-window signals (editingFinished) still reach it
        self.store = store
        self.runner = RenderRunner(self)
        self._library = Library()
        self._plan = Plan()
        self._profile: str | None = None
        self._baseline: dict = built_in_values()
        self._batch: dict | None = None
        self._last: dict = {}
        self._list_kind: str | None = None
        self._footer_frozen = False
        self._loading = True

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self._build_profile(root)
        self._build_folders(root)
        self._build_sound(root)
        self._build_audio(root)
        self._build_files(root)
        self._build_footer(root)
        self._build_menu()

        self.runner.started.connect(self._on_started)
        self.runner.result.connect(self._on_result)
        self.runner.done.connect(self._on_done)
        self.runner.failed.connect(self._on_failed)
        self.runner.stopped.connect(self._on_stopped)

        self._load_settings()
        self._loading = False
        self._rescan()
        self._refresh()
        for sec in (self.folders, self.sound, self.audio, self.files):
            sec.toggled.connect(self._section_toggled)
        self._fit()

    # ---- sizing: the only place the window's size is set --------------------

    def _fit(self) -> None:
        central = self.centralWidget()
        central.layout().activate()
        central.updateGeometry()
        h = central.sizeHint().height() + self.menuBar().sizeHint().height()
        self.setFixedSize(640, h)

    def _section_toggled(self, _on: bool) -> None:
        self._fit()
        for name, sec in self._sections().items():
            self.settings.setValue(f"ui/expanded_{name}", sec.expanded())

    def _sections(self) -> dict[str, Section]:
        return {"folders": self.folders, "sound": self.sound, "audio": self.audio, "files": self.files}

    # ---- construction --------------------------------------------------------

    @staticmethod
    def _row(*widgets, spacing: int = 10) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(spacing)
        for item in widgets:
            if isinstance(item, int):
                hl.addSpacing(item)
            elif isinstance(item, tuple):
                hl.addWidget(item[0], item[1])
            else:
                hl.addWidget(item)
        w.setFixedHeight(26)
        return w

    def _build_profile(self, root: QVBoxLayout) -> None:
        self.profile_sec = Section(S.SECTION_PROFILE, collapsible=False)
        body = QHBoxLayout(self.profile_sec.body)
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(8)
        self.revert_btn = tool_button("revert", (22, 26), 13, bare=True, color=style.OFF_TEXT)
        self.revert_btn.clicked.connect(self._revert_all)
        self.combo = ProfileCombo()
        self.combo.activated.connect(self._combo_activated)
        self.save_btn = tool_button("save", (22, 26), 14, bare=True)
        self.save_btn.setToolTip(S.SAVE_TOOLTIP)
        self.save_btn.clicked.connect(self._save_profile)
        body.addWidget(self.revert_btn)
        body.addWidget(self.combo, 1)
        body.addWidget(self.save_btn)
        root.addWidget(self.profile_sec)

    def _path_row(self, label: str, field: PathField, browse_fn) -> tuple[QWidget, QWidget, QWidget]:
        browse = push_button(S.BROWSE)
        browse.clicked.connect(browse_fn)
        reveal = tool_button("folder", 26, 13)
        reveal.setToolTip(S.reveal_tooltip())
        reveal.setProperty("lock_exempt", True)
        reveal.clicked.connect(lambda: self._reveal(field.path()))
        return self._row(field_label(label, 78), (field, 1), browse, reveal), browse, reveal

    def _build_folders(self, root: QVBoxLayout) -> None:
        self.folders = Section(S.SECTION_FOLDERS, summary_mode=Qt.TextElideMode.ElideLeft)
        body = QVBoxLayout(self.folders.body)
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(9)
        self.presets = PathField(S.NOT_SET, folder=True)
        self.presets.path_changed.connect(lambda _t: self._presets_changed())
        self.output = PathField(S.NOT_SET, folder=True)
        self.output.path_changed.connect(lambda _t: self._changed())
        row, _b, self.reveal_presets = self._path_row(
            S.LABEL_PRESETS, self.presets, lambda: self._browse_dir(self.presets, S.LABEL_PRESETS))
        body.addWidget(row)
        row, _b, self.reveal_output = self._path_row(
            S.LABEL_OUTPUT, self.output, lambda: self._browse_dir(self.output, S.LABEL_OUTPUT))
        body.addWidget(row)
        self.separate = check_box(S.SEPARATE_FOLDERS)
        self.separate.toggled.connect(self._separate_toggled)
        body.addWidget(self._row(field_label("", 78), (self.separate, 1)))
        self.skip_existing = check_box(S.SKIP_EXISTING)
        self.skip_existing.toggled.connect(lambda _c: self._changed())
        body.addWidget(self._row(field_label("", 78), (self.skip_existing, 1)))
        root.addWidget(self.folders)

    def _grid(self, section: Section) -> QGridLayout:
        g = QGridLayout(section.body)
        g.setContentsMargins(12, 12, 12, 12)
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(9)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        return g

    def _spin_row(self, key: str, label: str, lo, hi, value, suffix: str,
                  decimals: int | None = None) -> QWidget:
        spin, stepper = spin_box(lo, hi, value, suffix, decimals, S.TOOLTIPS[key])
        revert = tool_button("revert", (18, 26), 12, bare=True, color=style.OFF_TEXT)
        revert.clicked.connect(lambda: self._revert_field(key))
        spin.valueChanged.connect(lambda _v: self._changed())
        self.spins[key] = spin
        self.reverts[key] = revert
        row = self._row(field_label(label, 78, S.TOOLTIPS[key]), revert, (spin, 1), -5, stepper)
        row.setToolTip(S.TOOLTIPS[key])
        self.spin_rows[key] = row
        return row

    def _build_sound(self, root: QVBoxLayout) -> None:
        self.sound = Section(S.SECTION_SOUND)
        self.spins: dict = {}
        self.reverts: dict = {}
        self.spin_rows: dict = {}
        g = self._grid(self.sound)
        g.addWidget(self._spin_row("note", S.LABEL_NOTE, 0, 127, 48, "C3"), 0, 0)
        g.addWidget(self._spin_row("velocity", S.LABEL_VELOCITY, 1, 127, 127, ""), 0, 1)
        g.addWidget(self._spin_row("duration", S.LABEL_DURATION, 0.01, 600.0, 1.0, "s", 2), 1, 0)
        g.addWidget(self._spin_row("tail", S.LABEL_TAIL, 0.0, 600.0, 0.5, "s", 2), 1, 1)
        self.spins["note"].valueChanged.connect(
            lambda v: self.spins["note"].suffix_label.setText(note_name(v)))

        self.midi = PathField(S.MIDI_EMPTY, folder=False)
        self.midi.setToolTip(S.TOOLTIPS["midi"])
        self.midi.path_changed.connect(lambda _t: self._changed())
        browse = push_button(S.BROWSE)
        browse.clicked.connect(self._browse_midi)
        self.midi_clear = tool_button("clear", 26, 11)
        self.midi_clear.clicked.connect(lambda: self.midi.set_path(""))
        spacer = QWidget()
        spacer.setFixedSize(18, 26)
        g.addWidget(self._row(field_label(S.LABEL_MIDI, 78, S.TOOLTIPS["midi"]), spacer,
                              (self.midi, 1), browse, self.midi_clear), 2, 0, 1, 2)
        root.addWidget(self.sound)

    def _build_audio(self, root: QVBoxLayout) -> None:
        self.audio = Section(S.SECTION_AUDIO)
        g = self._grid(self.audio)
        self.sample_rate = combo(_SAMPLE_RATES, S.TOOLTIPS["sample_rate"])
        self.bit_depth = combo(_BIT_DEPTHS, S.TOOLTIPS["bit_depth"])
        self.fmt = combo(_FORMATS, S.TOOLTIPS["format"])
        self.deterministic = check_box(S.DETERMINISTIC, S.TOOLTIPS["deterministic"])
        for c in (self.sample_rate, self.bit_depth, self.fmt):
            c.currentIndexChanged.connect(lambda _i: self._changed())
        self.deterministic.toggled.connect(lambda _c: self._changed())
        g.addWidget(self._row(field_label(S.LABEL_SAMPLE_RATE, 78, S.TOOLTIPS["sample_rate"]),
                              (self.sample_rate, 1)), 0, 0)
        g.addWidget(self._row(field_label(S.LABEL_BIT_DEPTH, 78, S.TOOLTIPS["bit_depth"]),
                              (self.bit_depth, 1)), 0, 1)
        g.addWidget(self._row(field_label(S.LABEL_FORMAT, 78, S.TOOLTIPS["format"]),
                              (self.fmt, 1)), 1, 0)
        g.addWidget(self._row(field_label("", 78), (self.deterministic, 1)), 1, 1)
        root.addWidget(self.audio)

    def _build_files(self, root: QVBoxLayout) -> None:
        self.files = Section(S.SECTION_FILES)
        g = self._grid(self.files)
        self.template = QLineEdit()
        self.template.setFixedHeight(26)
        self.template.setFont(style.mono(11.5, 500))
        self.template.textChanged.connect(lambda _t: self._changed())
        g.addWidget(self._row(field_label(S.LABEL_FILENAME, 78), (self.template, 1)), 0, 0, 1, 2)
        self.no_recurse = check_box(S.NO_RECURSE, S.TOOLTIPS["no_recurse"])
        self.no_recurse.toggled.connect(lambda _c: self._presets_changed())
        g.addWidget(self._row(field_label("", 78), (self.no_recurse, 1)), 1, 0)
        root.addWidget(self.files)

    def _build_footer(self, root: QVBoxLayout) -> None:
        footer = QWidget()
        footer.setFixedHeight(30)
        hl = QHBoxLayout(footer)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)
        self.gear = tool_button("gear", 30, 14)
        self.gear.setToolTip(S.PREFERENCES)
        self.gear.clicked.connect(self._open_setup)
        hl.addWidget(self.gear)

        block = QWidget()
        block.setFixedHeight(30)
        bl = QVBoxLayout(block)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        bl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.bar = QProgressBar()
        self.bar.setFixedHeight(5)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        self.status_row = QWidget()
        sl = QHBoxLayout(self.status_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(12)
        self.status = ElidingLabel("")
        self.status.setObjectName("status")
        self.status.setFont(style.mono(11))
        self.eta = QLabel("")
        self.eta.setObjectName("status")
        self.eta.setFont(style.mono(11))
        self.eta.setVisible(False)
        sl.addWidget(self.status, 1)
        sl.addWidget(self.eta)
        bl.addWidget(self.bar)
        bl.addWidget(self.status_row)
        hl.addWidget(block, 1)

        self.list_btn = push_button(S.FAILURES, 30, "footer")
        self.list_btn.setVisible(False)
        self.list_btn.clicked.connect(self._open_list)
        hl.addWidget(self.list_btn)
        self.reveal_done = tool_button("folder", 30, 14)
        self.reveal_done.setToolTip(S.reveal_tooltip())
        self.reveal_done.setVisible(False)
        self.reveal_done.clicked.connect(lambda: self._reveal(self.output.path()))
        hl.addWidget(self.reveal_done)
        self.primary = push_button(S.RENDER, 30, "primary")
        self.primary.setMinimumWidth(92)
        self.primary.clicked.connect(self._primary_clicked)
        hl.addWidget(self.primary)
        root.addWidget(footer)
        self._set_bar_visible(False)

    def _build_menu(self) -> None:
        # The containing QMenu is mandatory; macOS relocates the item and
        # hides the emptied "File" menu. See CORRECTIONS.md section 6.
        m = self.menuBar().addMenu("File")
        a = QAction(S.PREFERENCES, self)
        a.setMenuRole(QAction.MenuRole.PreferencesRole)
        a.setShortcut("Ctrl+,")
        a.triggered.connect(self._open_setup)
        m.addAction(a)

    # ---- settings ------------------------------------------------------------

    def _load_settings(self) -> None:
        s = self.settings
        self.presets.setText(s.value("run/presets", "", str))
        self.output.setText(s.value("run/output", "", str))
        for f in (self.presets, self.output):
            f.setToolTip(f.text())
            f.setCursorPosition(len(f.text()))
        self.skip_existing.setChecked(s.value("run/skip_existing", False, bool))
        name = s.value("ui/profile", "Default", str)
        self._set_profile(name if name in self.store.names() else "Default", load=True)
        for key, sec in self._sections().items():
            sec.set_expanded(s.value(f"ui/expanded_{key}", key == "folders", bool))

    def machine(self) -> dict:
        s = self.settings
        return {
            "serum1": s.value("machine/serum1", "", str),
            "serum2": s.value("machine/serum2", "", str),
            "workers": s.value("machine/workers", 7, int),
            "workers_auto": s.value("machine/workers_auto", True, bool),
        }

    def _save_machine(self, v: dict) -> None:
        for k in ("serum1", "serum2", "workers", "workers_auto"):
            self.settings.setValue(f"machine/{k}", v[k])

    def _plugin(self, key: str) -> Path | None:
        p = self.machine()[key]
        fmt = PresetFormat.SERUM1 if key == "serum1" else PresetFormat.SERUM2
        return Path(p) if p and plugin_path_looks_valid(p, fmt) else None

    # ---- values ----------------------------------------------------------------

    def profile_values(self) -> dict:
        midi = self.midi.path()
        return {
            "note": self.spins["note"].value(),
            "velocity": self.spins["velocity"].value(),
            "duration": self.spins["duration"].value(),
            "tail": self.spins["tail"].value(),
            "midi_path": midi or None,
            "sample_rate": int(self.sample_rate.currentText()),
            "bit_depth": self.bit_depth.currentText(),
            "output_format": self.fmt.currentText().lower(),
            "filename_template": self.template.text(),
            "deterministic": self.deterministic.isChecked(),
            "no_recurse": self.no_recurse.isChecked(),
        }

    def _apply_values(self, v: dict) -> None:
        was = self._loading
        self._loading = True
        try:
            for k in ("note", "velocity", "duration", "tail"):
                self.spins[k].setValue(v[k])
            self.midi.setText(str(v["midi_path"] or ""))
            self.midi.setToolTip(self.midi.text())
            self.sample_rate.setCurrentText(str(v["sample_rate"]))
            self.bit_depth.setCurrentText(str(v["bit_depth"]))
            self.fmt.setCurrentText(str(v["output_format"]).upper())
            self.template.setText(v["filename_template"])
            self.deterministic.setChecked(bool(v["deterministic"]))
            self.no_recurse.setChecked(bool(v["no_recurse"]))
        finally:
            self._loading = was
        self._rescan()
        self._changed()

    def params(self) -> RenderParams | None:
        if not self.presets.path() or not self.output.path():
            return None
        m = self.machine()
        v = self.profile_values()
        v["midi_path"] = Path(v["midi_path"]) if v["midi_path"] else None
        return RenderParams(
            presets_dir=Path(self.presets.path()), output_dir=Path(self.output.path()),
            serum1_plugin_path=self._plugin("serum1"), serum2_plugin_path=self._plugin("serum2"),
            workers=int(m["workers"]), workers_auto=bool(m["workers_auto"]),
            skip_existing=self.skip_existing.isChecked(), **v,
        )

    # ---- change handling -----------------------------------------------------

    def _presets_changed(self) -> None:
        self._rescan()
        self._changed()

    def _rescan(self) -> None:
        p = self.presets.path()
        self._library = scan(Path(p), recurse=not self.no_recurse.isChecked()) if p else Library()

    def _changed(self) -> None:
        if self._loading:
            return
        self._footer_frozen = False
        self._refresh()

    def _separate_toggled(self, on: bool) -> None:
        if self._loading:
            return
        t = self.template.text()
        if on and not t.startswith(_FORMAT_PREFIX):
            self.template.setText(_FORMAT_PREFIX + t)
        elif not on and t.startswith(_FORMAT_PREFIX):
            self.template.setText(t[len(_FORMAT_PREFIX):])

    def _refresh(self) -> None:
        """Re-plan and redraw everything derived from the widgets."""
        s = self.settings
        s.setValue("run/presets", self.presets.path())
        s.setValue("run/output", self.output.path())
        s.setValue("run/skip_existing", self.skip_existing.isChecked())

        # Cross-widget rules
        midi_set = bool(self.midi.path())
        for k in ("note", "velocity"):
            self.spins[k].setEnabled(not midi_set)
            self.reverts[k].setEnabled(not midi_set)
            self.spin_rows[k].setToolTip(S.TOOLTIPS["midi"] if midi_set else S.TOOLTIPS[k])
        self.midi_clear.setVisible(midi_set)
        self.bit_depth.setEnabled(self.fmt.currentText() != "NPY")
        t = self.template.text()
        was = self._loading
        self._loading = True
        self.separate.setChecked(t.startswith(_FORMAT_PREFIX))
        self._loading = was
        self.template.setToolTip(S.filename_tooltip(self._example()))
        for f, btn in ((self.presets, self.reveal_presets), (self.output, self.reveal_output)):
            exists = bool(f.path()) and Path(f.path()).is_dir()
            btn.setEnabled(exists)
            f.set_resolved(exists)

        # Profile state
        v = self.profile_values()
        modified = {k: v[k] != self._baseline[k] for k in PROFILE_KEYS}
        any_mod = any(modified.values())
        for key, sec in (("sound", self.sound), ("audio", self.audio), ("files", self.files)):
            sec.set_modified(any(modified[k] for k in SECTION_KEYS[key]))
        for k, btn in self.reverts.items():
            btn.setIcon(_revert_icon(modified[k]))
            btn.setToolTip(S.revert_tooltip(self._profile) if modified[k] else "")
        self.revert_btn.setIcon(_revert_icon(any_mod))
        self.revert_btn.setEnabled(any_mod)
        self.revert_btn.setToolTip(S.revert_tooltip(self._profile))
        self.combo.modified = any_mod
        self.combo.update()

        # Summaries
        midi_name = Path(self.midi.path()).name if midi_set else None
        self.sound.set_summary(S.sound_summary(
            note_name(v["note"]), v["velocity"], v["duration"], v["tail"], midi_name))
        self.audio.set_summary(S.audio_summary(v["sample_rate"], v["bit_depth"], v["output_format"]))
        self.files.set_summary(v["filename_template"])
        self.folders.set_summary(self.output.path())

        # Plan and footer
        p = self.params()
        self._plan = plan(self._library, p) if p else Plan()
        if self._batch is None:
            self._show_ready()

    def _example(self) -> str:
        stem = compose_fast(self.template.text(), _EXAMPLE_TOKENS,
                            self.spins["note"].value(), self.spins["velocity"].value())
        return stem + _EXTENSION_FOR.get(self.fmt.currentText().lower(), ".wav")

    # ---- footer, before a batch ----------------------------------------------

    def _set_status(self, text: str, warning: bool = False) -> None:
        self.status.setText(text)
        set_state(self.status, "tone", "warning" if warning else "")

    def _set_bar_visible(self, on: bool) -> None:
        self.bar.setVisible(on)
        self.status_row.setFixedHeight(15 if on else 30)
        self.eta.setVisible(on)

    def _show_ready(self) -> None:
        p = self._plan
        label = S.RENDER
        list_kind = None
        if self._footer_frozen:
            pass
        elif not self.presets.path():
            self._set_status("")
        elif not self.output.path():
            self._set_status(S.FOOTER_OUTPUT_MISSING, True)
        elif p.discovered == 0:
            self._set_status(S.NO_PRESETS, True)
        elif p.collisions:
            self._set_status(S.collisions_line(len(p.collisions)), True)
            list_kind = "collisions"
        elif p.renderable == 0:
            self._set_status(S.NOTHING_RENDERABLE, True)
        elif p.to_render == 0:
            self._set_status(S.all_exist(p.renderable), True)
        else:
            parts, warn = [], False
            if p.missing_plugin:
                fmt, n = next(iter(p.missing_plugin.items()))
                parts.append(S.filtered(p.renderable, n, S.synth_word(fmt.value)))
                warn = True
            elif not p.existing:
                parts.append(S.ready(p.discovered, p.per_format.get(PresetFormat.SERUM1, 0),
                                     p.per_format.get(PresetFormat.SERUM2, 0)))
            if p.existing and self.skip_existing.isChecked():
                parts.append(S.will_skip(p.renderable, p.existing) if not p.missing_plugin
                             else f"{p.existing} already rendered, will be skipped")
            elif p.existing:
                parts.append(S.will_overwrite(p.renderable, p.existing) if not p.missing_plugin
                             else f"{p.existing} will be overwritten")
                warn = True
            self._set_status(S.SEP.join(parts), warn)
        if p.to_render and (p.missing_plugin or p.existing):
            label = S.render_n(p.to_render)
        if not self._footer_frozen:
            self._set_bar_visible(False)
            self.reveal_done.setVisible(False)
            self._show_list_button(list_kind)
        self.primary.setText(label)
        self.primary.setEnabled(not p.blocked)

    def _show_list_button(self, kind: str | None) -> None:
        self._list_kind = kind
        self.list_btn.setVisible(kind is not None)
        self.list_btn.setText(S.COLLISIONS if kind == "collisions" else S.FAILURES)

    # ---- lifecycle -------------------------------------------------------------

    def _primary_clicked(self) -> None:
        if self._batch is not None:
            self.primary.setEnabled(False)
            self.runner.stop()
            return
        p = self.params()
        if p is None or self._plan.blocked:
            return
        self._launch(p, self._plan.to_render, retry=False)

    def _launch(self, p: RenderParams, total: int, retry: bool) -> None:
        self._batch = {
            "params": p, "total": total, "ok": 0, "failed": 0, "no_plugin": 0,
            "failures": [], "t0": time.monotonic(), "first": None, "retry": retry,
            "strangers": self._plan.existing, "skip_on": p.skip_existing,
            "output_for": dict(zip(self._plan.preset_paths, self._plan.output_paths)),
            "ended": False,
        }
        self._lock(True)
        self._footer_frozen = True
        self.primary.setText(S.STOP)
        self.primary.setObjectName("stop")
        set_state(self.primary, "kind", "stop")
        self.primary.setEnabled(True)
        set_state(self.bar, "stopped", False)
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(0)
        self._set_bar_visible(True)
        self.reveal_done.setVisible(False)
        self._show_list_button(None)
        self._set_status(S.progress(0, total, 0))
        self.eta.setText(S.STARTING)
        self.runner.start(p)

    def _lock(self, locked: bool) -> None:
        keep = (self.reveal_presets, self.reveal_output)
        for sec in (self.folders, self.sound, self.audio, self.files):
            sec.set_locked(locked, keep)
        for w in (self.combo, self.save_btn, self.gear):
            w.setEnabled(not locked)
        self.revert_btn.setEnabled(not locked and self.combo.modified)

    def _on_started(self, _total: int, _workers: int) -> None:
        pass  # the denominator is the plan's, not the CLI's (see CORRECTIONS §5)

    def _on_result(self, ev: dict) -> None:
        b = self._batch
        if b is None:
            return
        st = ev.get("status")
        if st == "ok":
            b["ok"] += 1
        elif st == "error":
            b["failed"] += 1
            b["failures"].append((ev.get("path", ""), ev.get("error", "")))
        elif ev.get("reason") == "no_plugin":
            b["no_plugin"] += 1
            return
        else:
            return  # reason "exists": not part of this batch's denominator
        done = b["ok"] + b["failed"]
        now = time.monotonic()
        if b["first"] is None:
            b["first"] = now
        self.bar.setValue(done)
        self._set_status(S.progress(done, b["total"], b["failed"]))
        elapsed = now - b["t0"]
        rate = done / elapsed if elapsed > 0 else 0
        self.eta.setText(S.eta((b["total"] - done) / rate) if rate > 0 else S.STARTING)

    def _end_batch(self) -> None:
        b = self._batch
        b["ended"] = True
        self._batch = None
        self._lock(False)
        self.primary.setObjectName("primary")
        set_state(self.primary, "kind", "primary")
        self.eta.setVisible(False)
        self.eta.setText("")
        self._last = b
        self._refresh()  # existing counts changed; footer stays frozen

    def _on_done(self, ev: dict) -> None:
        b = self._batch
        if b is None:
            return
        t = S.elapsed(ev.get("elapsed", time.monotonic() - b["t0"]))
        ok, failed = ev.get("ok", b["ok"]), ev.get("failed", b["failed"])
        self._end_batch()
        self._set_bar_visible(False)
        self.reveal_done.setVisible(True)
        if failed:
            self._set_status(S.done_failed(ok, failed, t), True)
            self._show_list_button("failures")
        elif b["no_plugin"]:
            fmt = next(iter(self._plan.missing_plugin), PresetFormat.SERUM2)
            self._set_status(S.done_filtered(ok, b["no_plugin"], S.synth_word(fmt.value), t))
        else:
            self._set_status(S.done_clean(ok, t))

    def _on_failed(self, message: str) -> None:
        b = self._batch
        if b is None:
            return
        done = b["ok"] + b["failed"]
        self._end_batch()
        self._set_bar_visible(False)
        if done:
            b["broken"] = message
            self._set_status(S.executor_broken(b["ok"], b["total"] - done), True)
            self._show_list_button("failures")
        else:
            self._set_status(message.strip().splitlines()[0] if message.strip() else message, True)
            self.status.setToolTip(message)

    def _on_stopped(self) -> None:
        b = self._batch
        if b is None:
            return
        done = b["ok"] + b["failed"]
        self._end_batch()
        set_state(self.bar, "stopped", True)
        self.bar.setVisible(True)
        skip_on = self.skip_existing.isChecked()
        self._set_status(S.stopped(done, b["total"], skip_on, b["strangers"]), not skip_on)
        if b["failed"]:
            self._show_list_button("failures")

    # ---- dialogs ---------------------------------------------------------------

    def _open_list(self) -> None:
        if self._list_kind == "collisions":
            rows = [(c.stem, S.SEP.join(Path(p).name for p in c.presets), "")
                    for c in self._plan.collisions]
            text = "\n".join(f"{c.stem}\t{', '.join(c.presets)}" for c in self._plan.collisions)
            TableDialog(self, S.collisions_title(len(rows)), (S.COL_FILE, S.COL_CLAIMED_BY),
                        rows, S.COLLISIONS_HINT, copy_text=text, col1_mono=True).exec()
            return
        b = self._last
        if b.get("broken"):
            abandoned = b["total"] - b["ok"] - b["failed"]
            rows = [(S.executor_row(abandoned), b["broken"].strip().splitlines()[-1], "amber")]
            TableDialog(self, S.batch_stopped_title(b["ok"]), (S.COL_PRESET, S.COL_ERROR),
                        rows, S.executor_hint(abandoned), copy_text=b["broken"]).exec()
            return
        rows = [(Path(p).name, e, "") for p, e in b["failures"]]
        text = "\n".join(f"{p}\t{e}" for p, e in b["failures"])
        changed = self._params_differ(b["params"])
        dlg = TableDialog(self, S.failures_title(len(rows)), (S.COL_PRESET, S.COL_ERROR), rows,
                          S.FAILURES_HINT_CHANGED if changed else S.failures_hint(len(rows)),
                          retry_count=len(rows), copy_text=text)
        dlg.retry.connect(self._retry)
        dlg.exec()

    def _params_differ(self, launched: RenderParams) -> bool:
        now = self.params()
        if now is None:
            return True
        strip = {"skip_existing": False}
        return dataclasses.replace(now, **strip) != dataclasses.replace(launched, **strip)

    def _retry(self) -> None:
        """Delete the failed presets' outputs, then re-run the original
        parameters with --skip-existing. See CORRECTIONS.md section 5."""
        b = self._last
        if self._batch is not None:
            return
        for preset, _err in b["failures"]:
            out = b["output_for"].get(preset)
            if out and Path(out).exists():
                Path(out).unlink()
        p = dataclasses.replace(b["params"], skip_existing=True)
        self._launch(p, len(b["failures"]), retry=True)
        self._batch["output_for"] = b["output_for"]

    def _open_setup(self, first_run: bool = False) -> None:
        if self._batch is not None:
            return
        v = self.machine()
        if first_run:
            v.update({"presets": self.presets.path(), "output": self.output.path()})
        dlg = SetupSheet(self, v, first_run)
        accepted = dlg.exec()
        self.settings.setValue("ui/first_run_done", True)
        if not accepted:
            return
        r = dlg.result_values()
        self._save_machine(r)
        if first_run:
            self.presets.set_path(r.get("presets", ""))
            self.output.set_path(r.get("output", ""))
        self._changed()

    def _browse_dir(self, field: PathField, title: str) -> None:
        p = QFileDialog.getExistingDirectory(self, title, field.path() or str(Path.home()))
        if p:
            field.set_path(p)

    def _browse_midi(self) -> None:
        start = str(Path(self.midi.path()).parent) if self.midi.path() else str(Path.home())
        p, _f = QFileDialog.getOpenFileName(self, S.LABEL_MIDI, start, "MIDI (*.mid *.midi)")
        if p:
            self.midi.set_path(p)

    @staticmethod
    def _reveal(path: str) -> None:
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ---- profiles ----------------------------------------------------------------

    def _refresh_combo(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for name in self.store.names():
            self.combo.addItem(name)
        self.combo.insertSeparator(self.combo.count())
        self.combo.addItem(S.MANAGE_PROFILES)
        self.combo.setCurrentIndex(self.store.names().index(self._profile) if self._profile else -1)
        self.combo.display = self._profile or S.NO_PROFILE
        self.combo.blockSignals(False)
        self.combo.update()

    def _set_profile(self, name: str | None, load: bool) -> None:
        self._profile = name
        self.settings.setValue("ui/profile", name or "")
        if name is not None:
            self._baseline = self.store.get(name)
            if load:
                self._apply_values(self._baseline)
        else:
            self._baseline = self.profile_values()
        self._refresh_combo()
        self._changed()

    def _combo_activated(self, index: int) -> None:
        names = self.store.names()
        if index >= len(names):  # the separator or Manage profiles…
            self._refresh_combo()
            self._open_manager()
            return
        name = names[index]
        if name == self._profile:
            return
        if self.combo.modified and not UnsavedDialog(self, self._profile).exec():
            self._refresh_combo()
            return
        self._set_profile(name, load=True)

    def _revert_all(self) -> None:
        self._apply_values(self._baseline)

    def _revert_field(self, key: str) -> None:
        v = self.profile_values()
        v[key] = self._baseline[key]
        self._apply_values(v)

    def _save_profile(self) -> None:
        dlg = SaveProfileDialog(self, self.store, self._profile)
        if dlg.exec():
            name = dlg.profile_name()
            self.store.save(name, self.profile_values())
            self._set_profile(name, load=False)

    def _open_manager(self) -> None:
        def summary(v: dict) -> str:
            midi = Path(v["midi_path"]).name if v["midi_path"] else None
            return S.sound_summary(note_name(v["note"]), v["velocity"], v["duration"], v["tail"], midi)

        dlg = ProfileManager(self, self.store, summary)
        dlg.renamed.connect(self._profile_renamed)
        dlg.deleted.connect(self._profile_deleted)
        dlg.exec()
        self._refresh_combo()

    def _profile_renamed(self, old: str, new: str) -> None:
        if self._profile == old:
            self._profile = new
            self.settings.setValue("ui/profile", new)

    def _profile_deleted(self, name: str) -> None:
        if self._profile == name:
            self._set_profile(None, load=False)

    # ---- shutdown -------------------------------------------------------------------

    def closeEvent(self, ev) -> None:
        self.runner.stop()
        super().closeEvent(ev)


def _revert_icon(lit: bool):
    return icon("revert", style.WARNING if lit else style.OFF_TEXT, 12)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("serum-render-gui")
    app.setOrganizationName("wiillownet")
    app.setStyleSheet(style.QSS)
    app.setFont(style.sans(11.5))
    settings = QSettings()
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    store = ProfileStore(data_dir / "profiles.json")
    win = MainWindow(settings, store)
    app.aboutToQuit.connect(win.runner.stop)
    win.show()
    if not settings.value("ui/first_run_done", False, bool):
        QTimer.singleShot(0, lambda: win._open_setup(first_run=True))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
