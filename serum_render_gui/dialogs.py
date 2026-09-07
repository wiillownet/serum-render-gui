"""The dialogs: Setup (doubles as first run), the failures/collisions table,
Save profile, Unsaved changes, and the Profile manager."""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import html
import re
import time

from PySide6.QtCore import QByteArray, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QScrollArea,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTextEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from serum_render.config import (
    default_plugin_path,
    default_preset_dir,
    plugin_path_looks_valid,
    plugin_suffix_for,
)
from serum_render.formats import PresetFormat
from serum_render.pool import resolve_worker_count

from . import strings as S
from . import style
from .planner import scan
from .profiles import ProfileStore
from .widgets import (
    ElidingLabel,
    PathField,
    check_box,
    field_label,
    push_button,
    set_state,
    spin_box,
    tool_button,
)


class _Dialog(QDialog):
    """Fixed width, content-derived height, the 18/16 padding."""

    def __init__(self, parent: QWidget | None, width: int, title: str, spacing: int) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._width = width
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(18, 16, 18, 16)
        self.vbox.setSpacing(spacing)
        t = QLabel(title)
        t.setFont(style.sans(13, 600))
        t.setFixedHeight(18)
        self.vbox.addWidget(t)

    def hint_label(self, text: str) -> QLabel:
        h = QLabel(text)
        h.setObjectName("hint")
        h.setFont(style.sans(11))
        h.setWordWrap(True)  # the approved hints run past 560px; wrapping beats eliding a sentence
        h.setMinimumHeight(15)
        return h

    def button_row(self, *buttons, leading: QWidget | None = None) -> QWidget:
        row = QWidget()
        row.setFixedHeight(30)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        if leading is not None:
            hl.addWidget(leading, 1)
        else:
            hl.addStretch(1)
        for b in buttons:
            hl.addWidget(b)
        return row

    def fit(self) -> None:
        self.layout().activate()
        self.setFixedSize(self._width, self.sizeHint().height())

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self.fit()


def dialog_button(text: str, kind: str = "dialog") -> QWidget:
    b = push_button(text, 30, kind)
    b.setMinimumWidth(92)
    return b


# ---- Setup ----------------------------------------------------------------


def detected_presets_dir() -> Path | None:
    """One folder covering every detected library. Serum 1 and Serum 2 ship
    as siblings (`Xfer Records/Serum Presets`, `Xfer Records/Serum 2
    Presets`), so their parent scans both; a single library is used as is."""
    found = [d for d in (default_preset_dir(f) for f in PresetFormat) if d is not None]
    if not found:
        return None
    if len(found) > 1 and len({d.parent for d in found}) == 1:
        return found[0].parent
    return found[0]


class SetupSheet(_Dialog):
    """Machine settings. `first_run=True` hoists the two folder rows in,
    adds the subtitle, and runs detection before showing."""

    def __init__(self, parent: QWidget | None, values: dict, first_run: bool) -> None:
        super().__init__(parent, 520, S.SETUP_TITLE, 14)
        self.first_run = first_run
        self.values = dict(values)
        self._library_count: Counter = Counter()

        self.subtitle = QLabel()
        self.subtitle.setObjectName("body")
        self.subtitle.setFont(style.sans(11))
        self.subtitle.setFixedHeight(15)
        self.subtitle.setVisible(first_run)
        self.vbox.addWidget(self.subtitle)

        form = QWidget()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(9)
        self.rows: dict[str, tuple[QLabel, PathField]] = {}
        specs = [("serum1", S.LABEL_SERUM1, S.NOT_FOUND, False),
                 ("serum2", S.LABEL_SERUM2, S.NOT_FOUND, False)]
        if first_run:
            specs += [("presets", S.LABEL_PRESETS, S.NOT_SET, True),
                      ("output", S.LABEL_OUTPUT, S.NOT_SET, True)]
        for key, label, placeholder, folder in specs:
            lab = field_label(label, 104)
            field = PathField(placeholder, folder)
            field.path_changed.connect(lambda _t, k=key: self._changed(k))
            browse = push_button(S.BROWSE)
            browse.clicked.connect(lambda _c, k=key: self._browse(k))
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(lab)
            row.addWidget(field, 1)
            row.addWidget(browse)
            fl.addLayout(row)
            self.rows[key] = (lab, field)

        cpu = os.cpu_count() or 2
        self._auto_workers = resolve_worker_count(-1)
        self.workers, stepper = spin_box(1, max(cpu, 1), self._auto_workers, f"of {cpu}")
        self.workers.setFixedWidth(118 - 5 - 14)
        self.workers.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.auto = check_box(S.AUTOMATIC)
        self.auto.toggled.connect(self._auto_toggled)
        wrow = QHBoxLayout()
        wrow.setSpacing(10)
        wrow.addWidget(field_label(S.LABEL_WORKERS, 104))
        wrow.addWidget(self.workers)
        wrow.addSpacing(-5)
        wrow.addWidget(stepper)
        wrow.addWidget(self.auto, 1)
        fl.addLayout(wrow)
        self.vbox.addWidget(form)

        self.footer = self.hint_label("")
        self.footer.setObjectName("status")
        self.footer.setFont(style.mono(11))
        self.cancel = dialog_button(S.CANCEL)
        self.cancel.clicked.connect(self.reject)
        self.done_btn = dialog_button(S.DONE, "primary")
        self.done_btn.clicked.connect(self.accept)
        self.done_btn.setDefault(True)
        self.vbox.addWidget(self.button_row(self.cancel, self.done_btn, leading=self.footer))

        self._populate()

    # -- state --

    def _populate(self) -> None:
        v = self.values
        if self.first_run:
            for fmt, key in ((PresetFormat.SERUM1, "serum1"), (PresetFormat.SERUM2, "serum2")):
                if not v.get(key):
                    p = default_plugin_path(fmt)
                    v[key] = str(p) if p and Path(p).exists() else ""
            if not v.get("presets"):
                p = detected_presets_dir()
                v["presets"] = str(p) if p else ""
        for key, (_lab, field) in self.rows.items():
            field.setText(v.get(key, ""))
            field.setToolTip(v.get(key, ""))
            field.setCursorPosition(len(field.text()))
        self.auto.setChecked(bool(v.get("workers_auto", True)))
        if not self.auto.isChecked():
            self.workers.setValue(int(v.get("workers", self._auto_workers)))
        self._auto_toggled(self.auto.isChecked())
        self._rescan()
        self._refresh()

    def _auto_toggled(self, on: bool) -> None:
        if on:
            self.workers.setValue(self._auto_workers)
        self.workers.setEnabled(not on)

    def _changed(self, key: str) -> None:
        self.values[key] = self.rows[key][1].path()
        if key == "presets":
            self._rescan()
        self._refresh()

    def _rescan(self) -> None:
        p = self.values.get("presets", "")
        lib = scan(Path(p)) if p else None
        self._library_count = Counter(fmt for _, fmt in lib.presets) if lib else Counter()

    def _plugin_state(self, key: str) -> str:
        """'ok', 'empty', 'missing' (not found) or 'wrong' (extension)."""
        path = self.values.get(key, "")
        if not path:
            return "empty"
        fmt = PresetFormat.SERUM1 if key == "serum1" else PresetFormat.SERUM2
        if plugin_path_looks_valid(path, fmt):
            return "ok"
        return "missing" if not Path(path).exists() else "wrong"

    def _refresh(self) -> None:
        states = {k: self._plugin_state(k) for k in ("serum1", "serum2")}
        for key, (lab, field) in self.rows.items():
            if key in states:
                st = states[key]
                set_state(lab, "state", {"missing": "warning", "wrong": "error"}.get(st, ""))
                field.set_resolved(st == "ok")
            else:
                field.set_resolved(bool(self.values.get(key)) and Path(self.values[key]).is_dir())
        any_plugin = "ok" in states.values()
        presets_ok = not self.first_run or bool(self.values.get("presets"))
        output_ok = not self.first_run or bool(self.values.get("output"))
        wrong = [k for k, st in states.items() if st == "wrong"]

        tone = "warning"
        if wrong:
            key = wrong[0]
            fmt = PresetFormat.SERUM1 if key == "serum1" else PresetFormat.SERUM2
            text = S.setup_footer_wrong_extension(
                S.LABEL_SERUM1 if key == "serum1" else S.LABEL_SERUM2, plugin_suffix_for(fmt) or "")
        elif not any_plugin and not (self.values.get("presets") or self.values.get("output")):
            text = S.FOOTER_NOTHING_SET
        elif self.first_run and not output_ok:
            text = S.FOOTER_OUTPUT_MISSING
        else:
            text, tone = self._count_line(states)
        self.footer.setText(text)
        set_state(self.footer, "tone", tone)
        self.done_btn.setEnabled(any_plugin and presets_ok and output_ok and not wrong)
        if self.first_run:
            self.subtitle.setText(S.setup_subtitle(
                states["serum1"] == "ok", states["serum2"] == "ok",
                bool(self._library_count), output_ok))

    def _count_line(self, states: dict) -> tuple[str, str]:
        total = sum(self._library_count.values())
        missing = {fmt: n for fmt, n in self._library_count.items()
                   if states["serum1" if fmt == PresetFormat.SERUM1 else "serum2"] != "ok"}
        if missing and sum(missing.values()) < total:
            fmt, n = next(iter(missing.items()))
            return S.filtered(total - sum(missing.values()), n, S.synth_word(fmt.value)), "warning"
        return S.presets_found(total), ""

    def _browse(self, key: str) -> None:
        lab, field = self.rows[key]
        start = field.path() or str(Path.home())
        if key in ("serum1", "serum2"):
            fmt = PresetFormat.SERUM1 if key == "serum1" else PresetFormat.SERUM2
            suffix = plugin_suffix_for(fmt) or ""
            # macOS plugins are bundles: a file dialog with the suffix filter
            # lets the user pick the bundle as a file.
            dlg = QFileDialog(self, lab.text(), start, f"Plugin (*{suffix})")
            dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
            dlg.setOption(QFileDialog.Option.DontUseNativeDialog, False)
            if dlg.exec():
                field.set_path(dlg.selectedFiles()[0])
        else:
            p = QFileDialog.getExistingDirectory(self, lab.text(), start)
            if p:
                field.set_path(p)

    def result_values(self) -> dict:
        v = dict(self.values)
        v["workers_auto"] = self.auto.isChecked()
        v["workers"] = self.workers.value()
        return v


# ---- Failures / collisions table -----------------------------------------


class TableDialog(_Dialog):
    """560px table dialog. `rows` are (col1, col2, kind); kind is "", "amber"
    or "more". Capped at four visible rows, then scrolls, so it never grows
    past a 289px parent."""

    retry = Signal()

    def __init__(self, parent, title: str, headers: tuple[str, str],
                 rows: list[tuple[str, str, str]], hint: str, retry_count: int = 0,
                 copy_text: str = "", col1_mono: bool = False) -> None:
        super().__init__(parent, 560, title, 12)
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(list(headers))
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.setWordWrap(False)
        table.setColumnWidth(0, 170)
        hh = table.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setFixedHeight(26)
        hh.setFont(style.mono(9.5, 500, spacing=1.1))
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.setHorizontalHeaderLabels([h.upper() for h in headers])
        table.verticalHeader().setDefaultSectionSize(32)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        from PySide6.QtGui import QBrush, QColor

        for r, (a, b, kind) in enumerate(rows):
            ia, ib = QTableWidgetItem(a), QTableWidgetItem(b)
            ia.setToolTip(a)
            ib.setToolTip(b)
            ia.setFont(style.mono(11) if col1_mono else style.sans(11))
            ib.setFont(style.sans(11) if col1_mono else style.mono(11))
            if kind == "amber":
                ia.setForeground(QBrush(QColor(style.WARNING)))
                ib.setForeground(QBrush(QColor(style.WARNING_DIM)))
                ib.setFont(style.mono(11))
                for it in (ia, ib):
                    it.setBackground(QBrush(QColor(232, 163, 61, 23)))
            elif kind == "more":
                ia.setForeground(QBrush(QColor(style.TEXT_FAINT)))
            else:
                ib.setForeground(QBrush(QColor(style.TEXT_DIM)))
            table.setItem(r, 0, ia)
            table.setItem(r, 1, ib)
        visible = min(len(rows), 4)
        table.setFixedHeight(26 + 32 * visible + 2)
        self.vbox.addWidget(table)
        self.vbox.addWidget(self.hint_label(hint))

        buttons = []
        if retry_count:
            rb = dialog_button(S.retry_n(retry_count))
            rb.clicked.connect(self._retry)
            buttons.append(rb)
        cp = dialog_button(S.COPY)
        cp.clicked.connect(lambda: QApplication.clipboard().setText(copy_text))
        cl = dialog_button(S.CLOSE)
        cl.clicked.connect(self.reject)
        cl.setDefault(True)
        self.vbox.addWidget(self.button_row(*buttons, cp, cl))

    def _retry(self) -> None:
        self.accept()
        self.retry.emit()


# ---- Save profile / unsaved changes --------------------------------------


class SaveProfileDialog(_Dialog):
    def __init__(self, parent, store: ProfileStore, current: str | None) -> None:
        super().__init__(parent, 440, S.SAVE_PROFILE_TITLE, 14)
        self._store = store
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(field_label(S.LABEL_NAME, 44))
        self.name = QLineEdit()
        self.name.setFixedHeight(26)
        self.name.setFont(style.mono(11.5, 500))
        if current and not store.is_built_in(current):
            self.name.setText(current)
            self.name.selectAll()
        row.addWidget(self.name, 1)
        self.vbox.addLayout(row)
        self.warn = self.hint_label("")
        self.warn.setObjectName("status")
        set_state(self.warn, "tone", "warning")
        self.vbox.addWidget(self.warn)
        cancel = dialog_button(S.CANCEL)
        cancel.clicked.connect(self.reject)
        self.save = dialog_button(S.SAVE, "primary")
        self.save.clicked.connect(self.accept)
        self.save.setDefault(True)
        self.vbox.addWidget(self.button_row(cancel, self.save))
        self.name.textChanged.connect(self._check)
        self._check(self.name.text())

    def _check(self, text: str) -> None:
        name = text.strip()
        exists = name in self._store.names()
        built_in = self._store.is_built_in(name)
        self.warn.setText(S.confirm_overwrite(name) if exists and not built_in else "")
        self.save.setText(S.OVERWRITE if exists and not built_in else S.SAVE)
        self.save.setEnabled(bool(name) and not built_in)

    def profile_name(self) -> str:
        return self.name.text().strip()


class UnsavedDialog(_Dialog):
    def __init__(self, parent, current: str | None) -> None:
        super().__init__(parent, 440, S.UNSAVED_TITLE, 14)
        row = QHBoxLayout()
        row.setSpacing(12)
        badge = QLabel("!")
        badge.setObjectName("badge")
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFont(style.sans(15, 600))
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        body = QLabel(f'<div style="line-height:150%">{S.unsaved_body(current)}</div>')
        body.setObjectName("body")
        body.setFont(style.sans(11.5))
        body.setWordWrap(True)
        row.addWidget(body, 1)
        self.vbox.addLayout(row)
        cancel = dialog_button(S.CANCEL)
        cancel.clicked.connect(self.reject)
        cancel.setDefault(True)
        discard = dialog_button(S.DISCARD, "stop")
        discard.clicked.connect(self.accept)
        self.vbox.addWidget(self.button_row(cancel, discard))


# ---- Profile manager ------------------------------------------------------


class _ProfileRow(QFrame):
    """One profile. Swaps its contents in place for rename and for the two
    confirmations; min-height 46 keeps the dialog still while deciding."""

    changed = Signal()

    def __init__(self, manager: "ProfileManager", name: str, summary: str) -> None:
        super().__init__()
        self.setObjectName("profileRow")
        self.manager = manager
        self.name = name
        self.setMinimumHeight(47)
        self.stack = QStackedWidget()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.addWidget(self.stack)

        # Normal
        normal = QWidget()
        hl = QHBoxLayout(normal)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        text = QWidget()
        tl = QVBoxLayout(text)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(2)
        n = ElidingLabel(name)
        n.setFont(style.mono(11.5, 500))
        n.setFixedHeight(16)
        s = ElidingLabel(summary)
        s.setObjectName("hint")
        s.setFont(style.mono(10.5))
        s.setFixedHeight(14)
        tl.addWidget(n)
        tl.addWidget(s)
        hl.addWidget(text, 1)
        store = manager.store
        if store.is_built_in(name):
            b = QLabel(S.BUILT_IN)
            b.setObjectName("hint")
            b.setFont(style.sans(11))
            b.setFixedHeight(26)
            hl.addWidget(b)
        dup = tool_button("duplicate")
        dup.setToolTip("Duplicate")
        dup.clicked.connect(self._duplicate)
        hl.addWidget(dup)
        if not store.is_built_in(name):
            rn = tool_button("rename")
            rn.setToolTip(S.RENAME)
            rn.clicked.connect(lambda: self.stack.setCurrentIndex(1))
            de = tool_button("delete")
            de.setToolTip(S.DELETE)
            de.clicked.connect(lambda: self.stack.setCurrentIndex(2))
            hl.addWidget(rn)
            hl.addWidget(de)
        self.stack.addWidget(normal)

        # Rename
        ren = QWidget()
        rl = QHBoxLayout(ren)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        self.edit = QLineEdit(name)
        self.edit.setFixedHeight(26)
        self.edit.setFont(style.mono(11.5, 500))
        self.edit.returnPressed.connect(self._rename)
        ok = push_button(S.RENAME)
        ok.clicked.connect(self._rename)
        cancel = push_button(S.CANCEL)
        cancel.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        rl.addWidget(self.edit, 1)
        rl.addWidget(ok)
        rl.addWidget(cancel)
        self.stack.addWidget(ren)

        # Confirm delete
        self.stack.addWidget(self._confirm(S.confirm_delete(name), S.DELETE, self._delete))
        # Confirm overwrite (label filled at rename time)
        self.overwrite_label = None
        self.stack.addWidget(self._confirm("", S.OVERWRITE, self._overwrite))

    def _confirm(self, text: str, verb: str, fn) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        lab = ElidingLabel(text)
        lab.setObjectName("status")
        set_state(lab, "tone", "warning")
        lab.setFont(style.sans(11.5))
        lab.setFixedHeight(26)
        if verb == S.OVERWRITE:
            self.overwrite_label = lab
        go = push_button(verb, 26, "stop")
        go.clicked.connect(fn)
        cancel = push_button(S.CANCEL)
        cancel.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        hl.addWidget(lab, 1)
        hl.addWidget(go)
        hl.addWidget(cancel)
        return w

    def _duplicate(self) -> None:
        self.manager.store.duplicate(self.name)
        self.changed.emit()

    def _rename(self) -> None:
        new = self.edit.text().strip()
        if not new or new == self.name:
            self.stack.setCurrentIndex(0)
            return
        if new in self.manager.store.names():
            if self.manager.store.is_built_in(new):
                return
            self.overwrite_label.setText(S.confirm_overwrite(new))
            self.stack.setCurrentIndex(3)
            return
        self.manager.store.rename(self.name, new)
        self.manager.renamed.emit(self.name, new)
        self.changed.emit()

    def _overwrite(self) -> None:
        new = self.edit.text().strip()
        self.manager.store.delete(new)
        self.manager.store.rename(self.name, new)
        self.manager.renamed.emit(self.name, new)
        self.changed.emit()

    def _delete(self) -> None:
        self.manager.store.delete(self.name)
        self.manager.deleted.emit(self.name)
        self.changed.emit()


class ProfileManager(_Dialog):
    renamed = Signal(str, str)
    deleted = Signal(str)

    def __init__(self, parent, store: ProfileStore, summary_for) -> None:
        super().__init__(parent, 440, S.PROFILES_TITLE, 14)
        self.store = store
        self._summary_for = summary_for
        self.list = QFrame()
        self.list.setObjectName("list")
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        # Past five rows the dialog would outgrow a 445px parent, so the list
        # scrolls inside a fixed height from there on.
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.list)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.vbox.addWidget(self.scroll)
        self.vbox.addWidget(self.hint_label(S.MANAGER_HINT))
        close = dialog_button(S.CLOSE)
        close.clicked.connect(self.accept)
        close.setDefault(True)
        self.vbox.addWidget(self.button_row(close))
        self._rebuild()

    def _rebuild(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                # Detach now, not on deleteLater: a lingering child keeps
                # painting at its old spot until the event loop runs.
                w.setParent(None)
                w.deleteLater()
        header = QWidget()
        header.setObjectName("listHeader")
        header.setFixedHeight(26)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 7, 12, 7)
        h = QLabel(S.PROFILE_HEADER.upper())
        h.setObjectName("sectionTitle")
        h.setFont(style.mono(9.5, 500, spacing=1.1))
        hl.addWidget(h, 1)
        self.list_layout.addWidget(header)
        for name in self.store.names():
            row = _ProfileRow(self, name, self._summary_for(self.store.get(name)))
            row.changed.connect(self._rebuild)
            self.list_layout.addWidget(row)
        # Layout-added children are shown on the next event pass; an unshown
        # widget contributes nothing to sizeHint, so fit() would shrink the
        # dialog under the new rows. Show them now.
        if self.isVisible():
            for i in range(self.list_layout.count()):
                self.list_layout.itemAt(i).widget().show()
        rows = len(self.store.names())
        self.scroll.setFixedHeight(26 + 47 * min(rows, 5) + 2)
        # AlwaysOn rather than AsNeeded: macOS's transient bar paints over
        # the row buttons; a permanent bar reserves its own column.
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn if rows > 5 else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fit()


# ---- Log window -----------------------------------------------------------


class LogWindow(QWidget):
    """The advanced view: one line per event, plus the child's stderr.

    A separate, resizable window rather than a pane, because the main window
    must never change height. Shows completions only: serum-render 0.4.0 has
    no per-job start event, so "what is worker 3 on" is not knowable yet.
    """

    def __init__(self, parent: QWidget | None, settings: QSettings) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(S.LOG)
        self._settings = settings
        self._lines: list[str] = []
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(16, 14, 16, 14)
        vbox.setSpacing(10)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(style.mono(11))
        self.view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.view.setStyleSheet(
            f"QTextEdit {{ background: {style.WELL}; border: 1px solid {style.LINE};"
            f" border-radius: 6px; padding: 8px; color: {style.TEXT_DIM}; }}"
        )
        self.view.setPlaceholderText(S.LOG_EMPTY)
        vbox.addWidget(self.view, 1)
        copy = push_button(S.COPY, 30, "dialog")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text()))
        save = push_button(S.SAVE_AS, 30, "dialog")
        save.clicked.connect(self._save)
        row = QWidget()
        row.setFixedHeight(30)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        hl.addStretch(1)
        hl.addWidget(copy)
        hl.addWidget(save)
        vbox.addWidget(row)
        self.resize(640, 360)
        geo = settings.value("ui/log_geometry")
        if isinstance(geo, QByteArray) and not geo.isEmpty():
            self.restoreGeometry(geo)

    # -- content --

    def text(self) -> str:
        return "\n".join(self._lines)

    def _add(self, line: str, color: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._lines.append(f"{stamp}  {line}")
        # Rich text collapses runs of spaces; the status column relies on them.
        body = re.sub(r" {2,}", lambda m: "&nbsp;" * len(m.group()), html.escape(line))
        self.view.append(
            f'<span style="color:{style.TEXT_FAINT}">{stamp}</span>&nbsp;&nbsp;'
            f'<span style="color:{color}">{body}</span>'
        )

    def batch_started(self, command: list[str], total: int) -> None:
        if self._lines:
            self._add("", style.TEXT_FAINT)
        self._add(" ".join(command), style.TEXT)
        self._add(f"{total} to render", style.TEXT_DIM)

    def result(self, ev: dict) -> None:
        status = ev.get("status", "?")
        path = Path(str(ev.get("path", ""))).name
        if status == "ok":
            self._add(f"ok       {path}", style.TEXT_DIM)
        elif status == "error":
            self._add(f"error    {path}  {ev.get('error', '')}", style.WARNING)
        else:
            self._add(f"skipped  {path}  {ev.get('reason', '')}", style.TEXT_FAINT)

    def stderr(self, line: str) -> None:
        self._add(f"stderr   {line}", style.TEXT_FAINT)

    def note(self, line: str, warning: bool = False) -> None:
        self._add(line, style.WARNING if warning else style.TEXT)

    # -- window --

    def _save(self) -> None:
        path, _f = QFileDialog.getSaveFileName(self, S.SAVE_AS, str(Path.home() / "serum-render.log"), "Log (*.log *.txt)")
        if path:
            Path(path).write_text(self.text() + "\n", encoding="utf-8")

    def closeEvent(self, ev) -> None:
        self._settings.setValue("ui/log_geometry", self.saveGeometry())
        super().closeEvent(ev)
