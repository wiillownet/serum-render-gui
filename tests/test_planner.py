"""Pure-function coverage for the in-process planner. No Qt, no Serum."""
from __future__ import annotations

from pathlib import Path

import pytest

from serum_render.formats import PresetFormat
from serum_render_gui.planner import (
    Library,
    RenderParams,
    build_argv,
    compose_fast,
    plan,
    scan,
)


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


@pytest.fixture
def params(tmp_path: Path) -> RenderParams:
    """Both plugins present, so nothing is filtered unless a test says so."""
    return RenderParams(
        presets_dir=tmp_path / "presets",
        output_dir=tmp_path / "out",
        serum1_plugin_path=tmp_path / "Serum.vst",
        serum2_plugin_path=tmp_path / "Serum2.vst3",
    )


# ---- build_argv -----------------------------------------------------------


def test_argv_leads_with_the_two_positionals(params):
    argv = build_argv(params)
    assert argv[:2] == [str(params.presets_dir), str(params.output_dir)]


def test_argv_always_requests_the_event_stream(params):
    assert build_argv(params)[-1] == "--json"


def test_argv_omits_a_plugin_flag_that_is_unset(tmp_path):
    p = RenderParams(
        presets_dir=tmp_path, output_dir=tmp_path, serum1_plugin_path=tmp_path / "S.vst"
    )
    argv = build_argv(p)
    assert "--serum1" in argv
    assert "--serum2" not in argv


def test_argv_passes_note_and_velocity_without_midi(params):
    argv = build_argv(params)
    assert argv[argv.index("--note") + 1] == "48"
    assert argv[argv.index("--velocity") + 1] == "127"
    assert "--midi" not in argv


def test_argv_drops_note_when_a_midi_file_is_set(params, tmp_path):
    """cli.py exits 2 when --note and --midi are both given, so the GUI must
    not build that command at all."""
    argv = build_argv(
        RenderParams(**{**params.as_dict(), "midi_path": tmp_path / "riff.mid"})
    )
    assert "--midi" in argv
    assert "--note" not in argv
    assert "--velocity" not in argv


def test_argv_booleans_appear_only_when_true(params):
    assert "--skip-existing" not in build_argv(params)
    on = RenderParams(**{**params.as_dict(), "skip_existing": True})
    assert "--skip-existing" in build_argv(on)


def test_argv_always_filters_a_mixed_library(params):
    """Not a parameter: the GUI states the renderable split in its footer, so
    it must never call the CLI path that refuses a whole mixed library."""
    assert "--skip-missing-format" in build_argv(params)


def test_argv_automatic_workers_becomes_the_cli_sentinel(params):
    """The GUI shows an Automatic checkbox; the CLI wants -1."""
    argv = build_argv(params)
    assert argv[argv.index("--workers") + 1] == "-1"
    manual = RenderParams(**{**params.as_dict(), "workers_auto": False, "workers": 3})
    argv = build_argv(manual)
    assert argv[argv.index("--workers") + 1] == "3"


# ---- scan and plan --------------------------------------------------------


def test_scan_of_a_missing_directory_is_empty(tmp_path):
    assert len(scan(tmp_path / "nope")) == 0


def test_plan_counts_each_format(params):
    _touch(params.presets_dir / "a.fxp")
    _touch(params.presets_dir / "b.fxp")
    _touch(params.presets_dir / "c.SerumPreset")
    result = plan(scan(params.presets_dir), params)
    assert result.discovered == 3
    assert result.per_format == {PresetFormat.SERUM1: 2, PresetFormat.SERUM2: 1}
    assert result.renderable == 3
    assert result.missing_plugin == {}


def test_plan_filters_presets_whose_plugin_is_absent(params):
    """The single-synth install: the count line has to split renderable from
    skipped, which means the planner must know both numbers."""
    _touch(params.presets_dir / "a.fxp")
    _touch(params.presets_dir / "c.SerumPreset")
    one_synth = RenderParams(**{**params.as_dict(), "serum2_plugin_path": None})
    result = plan(scan(params.presets_dir), one_synth)
    assert result.discovered == 2
    assert result.renderable == 1
    assert result.missing_plugin == {PresetFormat.SERUM2: 1}


def test_empty_scan_plans_to_nothing(params):
    result = plan(Library(), params)
    assert result.discovered == 0 and result.to_render == 0
    assert result.blocked  # a batch of zero would show 0/0 and finish instantly


# ---- collisions -----------------------------------------------------------


def test_same_name_in_two_folders_collides_under_a_flat_template(params):
    _touch(params.presets_dir / "Bass" / "Punch.fxp")
    _touch(params.presets_dir / "Lead" / "Punch.fxp")
    flat = RenderParams(**{**params.as_dict(), "filename_template": "{preset}"})
    result = plan(scan(params.presets_dir), flat)
    assert len(result.collisions) == 1
    assert result.collisions[0].stem == "Punch"
    assert len(result.collisions[0].presets) == 2
    assert result.blocked


def test_subdir_token_resolves_the_collision(params):
    _touch(params.presets_dir / "Bass" / "Punch.fxp")
    _touch(params.presets_dir / "Lead" / "Punch.fxp")
    nested = RenderParams(
        **{**params.as_dict(), "filename_template": "{subdir}/{preset}"}
    )
    result = plan(scan(params.presets_dir), nested)
    assert result.collisions == ()
    assert not result.blocked


def test_format_token_separates_the_two_synths(params):
    """The design's `Separate folders per synth` checkbox is this token."""
    _touch(params.presets_dir / "Punch.fxp")
    _touch(params.presets_dir / "Punch.SerumPreset")
    assert plan(scan(params.presets_dir), params).collisions  # same stem
    split = RenderParams(
        **{**params.as_dict(), "filename_template": "{format}/{preset}"}
    )
    assert plan(scan(params.presets_dir), split).collisions == ()


def test_collision_detection_reads_stems_not_resolved_paths(params):
    """resolve_output_paths disambiguates duplicates to `foo_1`, which is the
    outcome the design refuses — reading its output would report zero
    collisions every time."""
    _touch(params.presets_dir / "Bass" / "Punch.fxp")
    _touch(params.presets_dir / "Lead" / "Punch.fxp")
    flat = RenderParams(**{**params.as_dict(), "filename_template": "{preset}"})
    result = plan(scan(params.presets_dir), flat)
    assert result.collisions
    # The CLI would still write both files, under disambiguated names.
    assert len({Path(p).name for p in result.output_paths}) == 2


def test_presets_that_sanitize_to_nothing_do_not_collide(params):
    """They get distinct `preset_NNNN` fallbacks, so they never contend."""
    _touch(params.presets_dir / "!!!.fxp")
    _touch(params.presets_dir / "???.fxp")
    result = plan(scan(params.presets_dir), params)
    assert result.collisions == ()


# ---- existing output ------------------------------------------------------


def test_existing_outputs_are_counted(params):
    _touch(params.presets_dir / "a.fxp")
    _touch(params.presets_dir / "b.fxp")
    _touch(params.output_dir / "a.wav")
    result = plan(scan(params.presets_dir), params)
    assert result.existing == 1
    assert result.to_render == 2  # skip_existing off: both are re-rendered


def test_skip_existing_shrinks_the_denominator(params):
    _touch(params.presets_dir / "a.fxp")
    _touch(params.presets_dir / "b.fxp")
    _touch(params.output_dir / "a.wav")
    resuming = RenderParams(**{**params.as_dict(), "skip_existing": True})
    result = plan(scan(params.presets_dir), resuming)
    assert result.existing == 1
    assert result.to_render == 1


def test_everything_already_rendered_blocks_the_button(params):
    _touch(params.presets_dir / "a.fxp")
    _touch(params.output_dir / "a.wav")
    resuming = RenderParams(**{**params.as_dict(), "skip_existing": True})
    result = plan(scan(params.presets_dir), resuming)
    assert result.to_render == 0
    assert result.blocked


def test_npy_format_changes_which_outputs_count_as_existing(params):
    _touch(params.presets_dir / "a.fxp")
    _touch(params.output_dir / "a.wav")
    as_npy = RenderParams(**{**params.as_dict(), "output_format": "npy"})
    assert plan(scan(params.presets_dir), as_npy).existing == 0


def test_the_default_template_is_collision_free_on_a_nested_tree(params):
    """Regression guard for the default. The CLI's `{preset}` collides 253
    times on the real Serum 1 factory library, and the design blocks on
    collisions — so that default would render nothing on a fresh install."""
    assert params.filename_template == "{subdir}/{preset}"
    _touch(params.presets_dir / "Bass" / "Punch.fxp")
    _touch(params.presets_dir / "Lead" / "Punch.fxp")
    result = plan(scan(params.presets_dir), params)
    assert result.collisions == ()
    assert not result.blocked


# ---- compose_fast parity ---------------------------------------------------
#
# compose_fast replicates the tail of serum_render.discover.compose_filename and
# imports two of its private constants, so the two can drift silently and take
# collision detection with them. These pin them together. Do not delete.


@pytest.mark.parametrize("template", [
    "{preset}",
    "{subdir}/{preset}",
    "{format}/{subdir}/{preset}",
    "{subpath}_{preset}",
    "{folder}/{preset}_{note}_{velocity}",
    "{format}/{subpath}_{preset}_{note}",
    "{preset}",           # no tokens that vary
    "static",             # no tokens at all
])
def test_compose_fast_matches_compose_filename(tmp_path, template):
    from serum_render.discover import compose_filename
    from serum_render_gui.planner import _tokens_for

    root = tmp_path / "presets"
    paths = [
        root / "a.fxp",
        root / "Bass" / "Deep Sub 01.fxp",
        root / "Bass" / "nested" / "Wide  Detune!!.SerumPreset",
        root / "!!!.fxp",
    ]
    for p in paths:
        _touch(p)
    for path, fmt in ((paths[0], PresetFormat.SERUM1),
                      (paths[1], PresetFormat.SERUM1),
                      (paths[2], PresetFormat.SERUM2),
                      (paths[3], PresetFormat.SERUM1)):
        slow = compose_filename(template, path, root, 48, 127, fmt)
        fast = compose_fast(template, _tokens_for(path, fmt, root), 48, 127)
        assert fast == slow, f"{template!r} on {path.name}: {fast!r} != {slow!r}"


def test_compose_fast_matches_in_single_file_mode(tmp_path):
    """root=None collapses {subdir}/{subpath}, and the empty component is
    dropped — the divergence that makes per-file retry write to the wrong path."""
    from serum_render.discover import compose_filename
    from serum_render_gui.planner import _tokens_for

    path = tmp_path / "Bass" / "x.fxp"
    _touch(path)
    slow = compose_filename("{subdir}/{preset}", path, None, 48, 127, PresetFormat.SERUM1)
    fast = compose_fast("{subdir}/{preset}", _tokens_for(path, PresetFormat.SERUM1, None), 48, 127)
    assert fast == slow == "x"
