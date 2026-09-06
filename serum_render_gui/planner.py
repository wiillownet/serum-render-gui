"""In-process render planning: discovery, counting, collision detection.

Boundary A puts *rendering* behind the serum-render CLI, but planning has to
happen here. The design specifies collision detection as continuous — re-run
whenever the preset folder, filename template, output format or separate-folders
setting changes — and a subprocess per keystroke is not a design.

Safe by import graph, which is the only reason this is allowed: `serum_render`'s
discovery layer is main-process-only and pulls stdlib plus mido. Nothing reached
from this module imports dawdreamer, so the GUI process never loads a plugin.
"""
from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from serum_render.discover import (
    compose_filename,
    discover_presets,
    resolve_output_paths,
)
from serum_render.formats import PresetFormat

# Container -> the extension the CLI derives from it (cli.py's `extension`).
_EXTENSION_FOR = {"wav": ".wav", "npy": ".npy"}


@dataclass(frozen=True)
class RenderParams:
    """Every value that becomes a CLI flag, flat.

    The GUI splits these across three stores — profile (travels), machine
    settings (never travels) and per-run fields — but that split is a
    persistence concern. argv needs all of them at once, so they are one object
    here. See docs/decisions.md on why the stores are not three preset types.
    """

    presets_dir: Path
    output_dir: Path

    # Machine
    serum1_plugin_path: Path | None = None
    serum2_plugin_path: Path | None = None
    workers: int = 7
    workers_auto: bool = True

    # Profile
    note: int = 48
    velocity: int = 127
    duration: float = 1.0
    tail: float = 1.0
    midi_path: Path | None = None
    sample_rate: int = 44100
    bit_depth: str = "16"
    output_format: str = "wav"
    # Not the CLI's "{preset}". Measured on the real factory libraries: that
    # template collides 253 times on the Serum 1 tree (Splice packs ship the
    # same preset at a folder root and inside a subfolder), and the design
    # blocks on collisions — so a fresh install would render nothing at all.
    # "{subdir}/{preset}" mirrors the preset tree and is collision-free on both
    # factory libraries. See docs/decisions.md.
    filename_template: str = "{subdir}/{preset}"
    deterministic: bool = False
    no_recurse: bool = False

    # Per-run
    skip_existing: bool = False

    def plugin_for(self, fmt: PresetFormat) -> Path | None:
        return {
            PresetFormat.SERUM1: self.serum1_plugin_path,
            PresetFormat.SERUM2: self.serum2_plugin_path,
        }[fmt]

    def as_dict(self) -> dict:
        """Flat dict, for the profile store and for the parameter set a running
        batch must carry — Retry re-submits this rather than re-reading widgets."""
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Collision:
    """Two or more presets resolving to one output filename. The design's two
    table columns are exactly these fields."""

    stem: str
    presets: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """Everything the footer, the Render button and the two dialogs need."""

    discovered: int = 0
    per_format: dict[PresetFormat, int] = field(default_factory=dict)
    missing_plugin: dict[PresetFormat, int] = field(default_factory=dict)
    renderable: int = 0
    collisions: tuple[Collision, ...] = ()
    existing: int = 0
    to_render: int = 0
    output_paths: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        """True when Render must be disabled. Collisions destroy information;
        an empty batch would show `0 / 0` and finish instantly."""
        return bool(self.collisions) or self.to_render == 0


def scan(presets_dir: Path, recurse: bool = True) -> list[tuple[Path, PresetFormat]]:
    """Discover presets under a directory. Separated from `plan` because this is
    the expensive half (a factory tree is thousands of files) and only needs
    re-running when the folder itself changes."""
    presets_dir = Path(presets_dir)
    if not presets_dir.exists():
        return []
    return discover_presets(presets_dir, recurse=recurse)


def plan(preset_files: list[tuple[Path, PresetFormat]], params: RenderParams) -> Plan:
    """Resolve a scan against the current parameters. Cheap enough to run on
    every keystroke, which is what continuous collision detection requires."""
    if not preset_files:
        return Plan()

    per_format = Counter(fmt for _, fmt in preset_files)
    missing = {
        fmt: n for fmt, n in per_format.items() if params.plugin_for(fmt) is None
    }
    renderable_files = [
        (p, fmt) for p, fmt in preset_files if params.plugin_for(fmt) is not None
    ]

    # `presets_root` must be absolute to match discover_presets' output, and is
    # None in single-file mode so {subpath} collapses out. Mirrors cli.py.
    presets_dir = Path(params.presets_dir)
    root = presets_dir.resolve() if presets_dir.is_dir() else None

    stems = [
        compose_filename(
            params.filename_template, p, root, params.note, params.velocity, fmt
        )
        for p, fmt in renderable_files
    ]

    extension = _EXTENSION_FOR[params.output_format]
    output_paths = resolve_output_paths(stems, Path(params.output_dir), extension)
    existing = sum(1 for path in output_paths if Path(path).exists())

    return Plan(
        discovered=len(preset_files),
        per_format=dict(per_format),
        missing_plugin=missing,
        renderable=len(renderable_files),
        collisions=_collisions(stems, renderable_files),
        existing=existing,
        to_render=(
            len(renderable_files) - existing
            if params.skip_existing
            else len(renderable_files)
        ),
        output_paths=tuple(output_paths),
    )


def _collisions(
    stems: list[str], preset_files: list[tuple[Path, PresetFormat]]
) -> tuple[Collision, ...]:
    """Presets whose composed stems are equal.

    Detection runs on the *composed* stems, deliberately not on the paths
    `resolve_output_paths` returns: that function disambiguates duplicates to
    `foo_1`, `foo_2`, which is precisely the outcome the design refuses. Reading
    its output would report zero collisions every time.

    An empty stem is not a collision. `resolve_output_paths` gives each one a
    distinct `preset_NNNN` fallback, so they never actually contend.
    """
    by_stem: dict[str, list[str]] = defaultdict(list)
    for stem, (path, _) in zip(stems, preset_files):
        if stem:
            by_stem[stem].append(str(path))
    return tuple(
        Collision(stem=stem, presets=tuple(paths))
        for stem, paths in sorted(by_stem.items())
        if len(paths) > 1
    )


def build_argv(params: RenderParams, skip_missing_format: bool = False) -> list[str]:
    """Flags for `python -m serum_render`, without the interpreter or `-m`.

    Every value is passed explicitly rather than relying on the CLI's defaults:
    a launcher that omits a flag inherits whatever that default becomes in a
    later release, which would silently change what the GUI renders.
    """
    argv: list[str] = [str(Path(params.presets_dir)), str(Path(params.output_dir))]

    if params.serum1_plugin_path is not None:
        argv += ["--serum1", str(Path(params.serum1_plugin_path))]
    if params.serum2_plugin_path is not None:
        argv += ["--serum2", str(Path(params.serum2_plugin_path))]

    # MIDI wins, one-directionally: cli.py exits 2 if --note and --midi are both
    # given, so the GUI must not build that command at all.
    if params.midi_path is not None:
        argv += ["--midi", str(Path(params.midi_path))]
    else:
        argv += ["--note", str(params.note), "--velocity", str(params.velocity)]

    argv += [
        "--duration", str(params.duration),
        "--tail", str(params.tail),
        "--sample-rate", str(params.sample_rate),
        "--bit-depth", params.bit_depth,
        "--format", params.output_format,
        "--filename-template", params.filename_template,
        "--workers", str(-1 if params.workers_auto else params.workers),
    ]

    if params.skip_existing:
        argv.append("--skip-existing")
    if params.deterministic:
        argv.append("--deterministic")
    if params.no_recurse:
        argv.append("--no-recurse")
    if skip_missing_format:
        argv.append("--skip-missing-format")

    argv.append("--json")
    return argv
