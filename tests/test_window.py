"""The main window, offscreen. Heights per the design's table (as deltas,
since the offscreen platform draws a menu bar cocoa does not), the lock set,
and the footer's pre-batch wording against a small library."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from serum_render_gui import style  # noqa: E402
from serum_render_gui.main import MainWindow  # noqa: E402
from serum_render_gui.profiles import ProfileStore  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(style.QSS)
    app.setFont(style.sans(11.5))
    return app


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


@pytest.fixture
def win(app, tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.setValue("machine/serum1", str(tmp_path / "Serum.vst"))
    (tmp_path / "Serum.vst").mkdir()
    for name in ("Bass/a.fxp", "Lead/b.fxp", "c.SerumPreset"):
        _touch(tmp_path / "presets" / name)
    settings.setValue("run/presets", str(tmp_path / "presets"))
    settings.setValue("run/output", str(tmp_path / "out"))
    w = MainWindow(settings, ProfileStore(tmp_path / "p.json"))
    w.show()
    app.processEvents()
    yield w
    w.close()


def _height(app, win):
    app.processEvents()
    return win.height()


def test_section_heights_match_the_design_table(app, win):
    secs = win._sections()
    for s in secs.values():
        s.set_expanded(False)
    base = _height(app, win)
    assert win.width() == 640
    assert [s.height() for s in secs.values()] == [26, 26, 26, 26]
    assert win.profile_sec.height() == 77
    for name, delta in (("folders", 156), ("sound", 121), ("audio", 86), ("files", 86)):
        secs[name].set_expanded(True)
        assert _height(app, win) == base + delta, name
        secs[name].set_expanded(False)
        assert _height(app, win) == base, f"{name} collapse"
    for s in secs.values():
        s.set_expanded(True)
    assert _height(app, win) == base + 156 + 121 + 86 + 86
    assert win.maximumHeight() == win.height()  # not user-resizable


def test_footer_reads_the_plan(app, win):
    assert win.status.full_text() == "2 will render · 1 need Serum 2, skipped"
    assert win.primary.text() == "Render 2"
    win.template.setText("{preset}")
    assert win.primary.isEnabled()
    _touch(Path(win.presets.path()) / "Lead/a.fxp")
    win._presets_changed()
    assert win.status.full_text() == "1 filename collisions · nothing will render"
    assert not win.primary.isEnabled()
    assert win.list_btn.isVisible() and win.list_btn.text() == "Collisions"


def test_separate_folders_edits_the_template(app, win):
    win.separate.setChecked(True)
    assert win.template.text() == "{format}/{subdir}/{preset}"
    win.separate.setChecked(False)
    assert win.template.text() == "{subdir}/{preset}"
    win.template.setText("{format}/x")
    assert win.separate.isChecked()
    win.template.setText("{preset}-{format}")
    assert not win.separate.isChecked()


def test_midi_locks_note_and_velocity_but_keeps_values(app, win):
    win.spins["note"].setValue(60)
    win.midi.set_path(str(Path(win.presets.path()) / "riff.mid"))
    assert not win.spins["note"].isEnabled() and not win.spins["velocity"].isEnabled()
    assert win.spins["note"].value() == 60
    assert win.sound.summary.full_text() == "riff.mid · 1.0s + 0.5s"
    win.midi.set_path("")
    assert win.spins["note"].isEnabled()
    assert win.sound.summary.full_text() == "C4 · 127 · 1.0s + 0.5s"


def test_lock_keeps_reveal_and_collapse_alive(app, win):
    win._lock(True)
    assert not win.presets.isEnabled() and not win.template.isEnabled()
    assert not win.gear.isEnabled() and not win.combo.isEnabled()
    assert win.reveal_presets.isEnabled()
    win.sound.set_expanded(False)
    assert not win.sound.expanded()
    win._lock(False)
    assert win.presets.isEnabled() and win.template.isEnabled()


def test_modified_marker_and_revert(app, win):
    assert not win.combo.modified
    win.spins["duration"].setValue(2.0)
    assert win.combo.modified and win.sound.dot.isVisible()
    win._revert_all()
    assert not win.combo.modified and win.spins["duration"].value() == 1.0


def test_profile_manager_grows_when_a_row_is_added(app, tmp_path):
    """Layout-added rows are invisible until the event loop runs, so a naive
    fit() shrank the dialog under them and the rows overlapped."""
    from serum_render_gui.dialogs import ProfileManager, _ProfileRow

    dlg = ProfileManager(None, ProfileStore(tmp_path / "p.json"), lambda v: "summary")
    dlg.show()
    app.processEvents()
    before = dlg.height()
    dlg.findChildren(_ProfileRow)[0]._duplicate()
    app.processEvents()
    rows = dlg.findChildren(_ProfileRow)
    assert len(rows) == 2
    assert dlg.height() > before
    assert len({r.geometry().y() for r in rows}) == 2
    dlg.close()


def test_detected_presets_dir_covers_both_libraries(monkeypatch, tmp_path):
    from serum_render_gui import dialogs
    from serum_render.formats import PresetFormat

    s1, s2 = tmp_path / "Xfer" / "Serum Presets", tmp_path / "Xfer" / "Serum 2 Presets"
    monkeypatch.setattr(dialogs, "default_preset_dir",
                        lambda f: s1 if f == PresetFormat.SERUM1 else s2)
    assert dialogs.detected_presets_dir() == tmp_path / "Xfer"
    monkeypatch.setattr(dialogs, "default_preset_dir",
                        lambda f: s1 if f == PresetFormat.SERUM1 else None)
    assert dialogs.detected_presets_dir() == s1
    monkeypatch.setattr(dialogs, "default_preset_dir",
                        lambda f: s1 if f == PresetFormat.SERUM1 else tmp_path / "elsewhere")
    assert dialogs.detected_presets_dir() == s1
