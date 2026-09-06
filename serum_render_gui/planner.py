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
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from serum_render.discover import (
    _STEM_MAX_LEN,
    _UNDERSCORE_RUN_RE,
    compose_filename,
    discover_presets,
    resolve_output_paths,
)
from serum_render.formats import PresetFormat, format_or_none

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
    # 0.5, not the CLI's 1.0: 1.0 duration + 0.5 tail is the 1.5s total the
    # default profile is specified as. See docs/decisions.md.
    tail: float = 0.5
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
    # Parallel tuples, renderable presets only, in job order. `preset_paths`
    # are resolved absolute strings, exactly what the CLI's `result` events
    # report as `path`, so Retry can map a failed preset to the file to delete.
    preset_paths: tuple[str, ...] = ()
    output_paths: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        """True when Render must be disabled. Collisions destroy information;
        an empty batch would show `0 / 0` and finish instantly."""
        return bool(self.collisions) or self.to_render == 0


@dataclass(frozen=True)
class Library:
    """A scan plus the per-preset template tokens it determines.

    The tokens exist so `plan` can re-run on every keystroke. Composing 3506
    filenames with `compose_filename` costs ~103ms because each call re-derives
    `{preset}`, `{folder}`, `{subpath}` and `{subdir}` from the path — but those
    depend only on the scan, never on the template. Precomputing them once here
    takes `plan` from ~137ms to ~26ms, which is the difference between a field
    that lags as you type and one that does not.
    """

    presets: tuple[tuple[Path, PresetFormat], ...] = ()
    root: Path | None = None
    # Per preset, in `presets` order: the token values fixed by the scan.
    tokens: tuple[dict[str, str], ...] = ()
    # Per preset, `str(p.resolve())`: what the CLI reports as `path`. Resolved
    # here once; doing it in `plan` cost 200ms per keystroke on 4271 presets.
    resolved: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.presets)


def scan(presets_dir: Path, recurse: bool = True) -> Library:
    """Discover presets under a directory and precompute their tokens.

    Separated from `plan` because this is the expensive half (a factory tree is
    thousands of files) and only needs re-running when the folder changes.
    """
    presets_dir = Path(presets_dir)
    if not presets_dir.exists():
        return Library()
    presets = tuple(discover_presets(presets_dir, recurse=recurse))
    # Matches cli.py: absolute so `relative_to` works, None in single-file mode
    # so {subpath} and {subdir} collapse out.
    root = presets_dir.resolve() if presets_dir.is_dir() else None
    return Library(presets=presets, root=root,
                   tokens=tuple(_tokens_for(p, fmt, root) for p, fmt in presets),
                   resolved=tuple(os.path.realpath(p) for p, _ in presets))


def _tokens_for(
    preset_path: Path, fmt: PresetFormat, root: Path | None
) -> dict[str, str]:
    """The token values a preset's path determines. Mirrors `compose_filename`'s
    derivation exactly; `test_planner.py` pins the two against each other."""
    from serum_render.discover import sanitize

    if root is not None:
        try:
            rel = preset_path.parent.relative_to(root)
        except ValueError:
            subpath = subdir = ""
        else:
            subpath = sanitize("_".join(rel.parts)) if rel.parts else ""
            subdir = "/".join(filter(None, (sanitize(part) for part in rel.parts)))
    else:
        subpath = subdir = ""
    return {
        "{preset}": sanitize(preset_path.stem),
        "{folder}": sanitize(preset_path.parent.name),
        "{subpath}": subpath,
        "{subdir}": subdir,
        "{format}": fmt.value,
    }


def compose_fast(template: str, tokens: dict[str, str], note: int, velocity: int) -> str:
    """`compose_filename` with the path-derived work already done.

    COUPLING: replicates the tail of `serum_render.discover.compose_filename`
    (underscore collapse, strip, per-component truncation) and imports its two
    private constants. If those drift, the GUI's collision detection and the
    CLI's actual output silently disagree — so `test_compose_fast_matches_*`
    asserts parity across templates and must never be deleted.
    """
    result = template
    for token, value in tokens.items():
        result = result.replace(token, value)
    result = result.replace("{note}", str(note)).replace("{velocity}", str(velocity))
    result = _UNDERSCORE_RUN_RE.sub("_", result).strip("_")
    return "/".join(part[:_STEM_MAX_LEN] for part in result.split("/") if part)


def plan(library: Library, params: RenderParams) -> Plan:
    """Resolve a scan against the current parameters. Cheap enough to run on
    every keystroke, which is what continuous collision detection requires."""
    if not library.presets:
        return Plan()

    per_format = Counter(fmt for _, fmt in library.presets)
    missing = {
        fmt: n for fmt, n in per_format.items() if params.plugin_for(fmt) is None
    }
    keep = [params.plugin_for(fmt) is not None for _, fmt in library.presets]
    renderable_files = [pf for pf, k in zip(library.presets, keep) if k]
    preset_paths = tuple(r for r, k in zip(library.resolved, keep) if k)

    stems = [
        compose_fast(params.filename_template, tok, params.note, params.velocity)
        for tok, k in zip(library.tokens, keep)
        if k
    ]

    extension = _EXTENSION_FOR[params.output_format]
    output_paths = resolve_output_paths(stems, Path(params.output_dir), extension)
    on_disk = _files_under(Path(params.output_dir))
    existing = sum(1 for path in output_paths if path in on_disk)

    return Plan(
        discovered=len(library.presets),
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
        preset_paths=preset_paths,
        output_paths=tuple(output_paths),
    )


def _files_under(output_dir: Path) -> set[str]:
    """Every file below the output folder, as the strings
    `resolve_output_paths` produces. One directory walk replaces one stat per
    preset: on 4271 presets that is ~5ms against ~100ms, and `plan` runs on
    every keystroke."""
    found: set[str] = set()
    for dirpath, _dirs, files in os.walk(output_dir):
        for name in files:
            found.add(os.path.join(dirpath, name))
    return found


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


def build_argv(params: RenderParams) -> list[str]:
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
    # Always, and deliberately not a parameter. The GUI filters the batch
    # itself and states the split in the footer, so it must never call the CLI
    # path that refuses a whole mixed library. It is a no-op when no plugin is
    # missing, and when nothing is renderable the GUI has already disabled
    # Render. It also closes a race: a preset landing in the folder between
    # planning and launching would otherwise abort the entire batch over a file
    # the GUI never saw. A flag that must always be set is not a parameter.
    argv.append("--skip-missing-format")

    argv.append("--json")
    return argv
