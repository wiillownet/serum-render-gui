"""Every user-facing string, in one place. Wording is from
docs/design/copy-sweep.md; rows the sweep left unsettled were settled in the
2026-09-07 copy pass (docs/decisions.md).

The separator is a middot everywhere, matching the approved tooltips.
"""
from __future__ import annotations

import sys

SEP = " · "
APP_TITLE = "Serum Render"

# ---- Per-setting tooltips (approved 2026-09-05) ----------------------------

TOOLTIPS = {
    "note": "MIDI note · 0-127 · default 48 (C3)",
    "velocity": "MIDI velocity · 1-127 · default 127",
    "duration": "Note-on length in seconds · default 1.0",
    "tail": "Silence after note-off · default 0.5",
    "midi": "Render a .mid sequence instead of one note · disables Note and Velocity",
    "sample_rate": "Output sample rate · default 44100",
    "bit_depth": "16, 24, or 32-bit float · default 16 · FLAC takes 16 or 24 · ignored for OGG and NPY",  # updated for 0.4.0
    "format": "WAV, FLAC, OGG (Vorbis), or NPY raw float32 arrays · default WAV",  # updated for 0.4.0
    "deterministic": "Fresh process per preset, bit-reproducible · much slower · default off",
    "no_recurse": "Skip subfolders · default off",
}

FILENAME_TOKENS = ("{preset}", "{folder}", "{subpath}", "{subdir}", "{format}", "{note}", "{velocity}")


def filename_tooltip(example: str) -> str:
    """Token list plus a live example that resolves as the template is typed."""
    chips = "".join(
        f'<span style="font-family:\'IBM Plex Mono\',Menlo,monospace;color:#A6E04D;'
        f'background:#111214;border:1px solid #2C2F36;padding:0 5px;">{t}</span> '
        for t in FILENAME_TOKENS
    )
    return (
        '<div style="width:300px;line-height:145%">'
        f"{chips}<br>default {{subdir}}/{{preset}} → {example}</div>"
    )


def reveal_tooltip() -> str:
    if sys.platform == "darwin":
        return "Reveal in Finder"
    if sys.platform == "win32":
        return "Show in Explorer"
    return "Open in file manager"


# ---- Setup sheet ----------------------------------------------------------

SETUP_TITLE = "Setup"
NOT_SET = "Not set"
NOT_FOUND = "Not found"
LABEL_SERUM1 = "Serum 1 (VST2)"
LABEL_SERUM2 = "Serum 2 (VST3)"
LABEL_PRESETS = "Presets"
LABEL_OUTPUT = "Output"
LABEL_WORKERS = "Workers"
AUTOMATIC = "Automatic"


def setup_subtitle(serum1: bool, serum2: bool, presets: bool, output: bool) -> str:
    if not (serum1 or serum2 or presets):
        return "Nothing detected."
    if not presets:
        return "Presets folder not found. Point it at your library."
    if serum1 and not serum2:
        return "Serum 2 not found · leave empty if you don't own it"
    if not serum1 and serum2:
        return "Serum 1 not found · leave empty if you don't own it"
    return "Paths detected." if output else "Paths detected. Choose an output folder."


def setup_footer_wrong_extension(row_label: str, expected: str) -> str:
    return f"{row_label} expects a {expected} bundle"


FOOTER_OUTPUT_MISSING = "Output folder not set"
OUTPUT_NOT_A_FOLDER = "Output path is a file · choose a folder"
FOOTER_NOTHING_SET = "Nothing set yet"


def presets_found(n: int) -> str:
    return f"{n} presets found"


# ---- Main window ----------------------------------------------------------

SECTION_PROFILE = "Profile"
SECTION_FOLDERS = "Folders"
SECTION_SOUND = "Sound"
SECTION_AUDIO = "Audio"
SECTION_FILES = "Files"

SEPARATE_FOLDERS = "Separate folders per synth"
SKIP_EXISTING = "Skip existing files"
LABEL_NOTE = "Note"
LABEL_VELOCITY = "Velocity"
LABEL_DURATION = "Duration"
LABEL_TAIL = "Tail"
LABEL_MIDI = "MIDI file"
MIDI_EMPTY = "None · single note"
LABEL_SAMPLE_RATE = "Sample rate"
LABEL_BIT_DEPTH = "Bit depth"
LABEL_FORMAT = "Format"
DETERMINISTIC = "Deterministic"
LABEL_FILENAME = "Filename"
NO_RECURSE = "Don't recurse"
BROWSE = "Browse"
NO_PROFILE = "(no profile)"
MODIFIED = "(modified)"
MANAGE_PROFILES = "Manage profiles…"
PREFERENCES = "Preferences…"
LOG = "Log"
SAVE_AS = "Save…"
LOG_EMPTY = "Nothing logged yet. Each batch adds its command, every preset as it starts and finishes, and stderr."


def revert_tooltip(profile: str | None) -> str:
    return f'Revert all to "{profile}"' if profile else "Revert all changes"


def revert_field_tooltip(value) -> str:
    """The per-field button names the value it goes back to."""
    if isinstance(value, bool):
        value = "on" if value else "off"
    elif value is None:
        value = "none"
    return f"Revert to {value}"


SAVE_TOOLTIP = "Save as profile…"


def secs(x: float) -> str:
    """1.0 stays 1.0 (the design shows one decimal), 0.25 stays 0.25."""
    return f"{x:.1f}" if round(x, 1) == x else f"{x:g}"


def sound_summary(note_name: str, velocity: int, duration: float, tail: float,
                  midi_name: str | None) -> str:
    head = midi_name if midi_name else f"{note_name}{SEP}{velocity}"
    return f"{head}{SEP}{secs(duration)}s + {secs(tail)}s"


def audio_summary(rate: int, depth: str | None, fmt: str) -> str:
    """`depth` is None when the format ignores it."""
    if depth is None:
        return f"{rate}{SEP}{fmt.upper()}"
    depth_word = "32-bit float" if depth == "32f" else f"{depth}-bit"
    return f"{rate}{SEP}{depth_word}{SEP}{fmt.upper()}"


# ---- Footer, before a batch -----------------------------------------------


def synth_word(fmt_value: str) -> str:
    return "Serum 1" if fmt_value == "serum1" else "Serum 2"


def ready(n: int, s1: int, s2: int) -> str:
    return f"{n} presets{SEP}{s1} Serum 1{SEP}{s2} Serum 2"


def filtered(will: int, missing: int, synth: str) -> str:
    return f"{will} will render{SEP}{missing} need {synth}, skipped"


NOTHING_RENDERABLE = "Nothing renderable · no plugin path set"


def collisions_line(n: int) -> str:
    return f"{n} filename collisions{SEP}nothing will render"


def will_overwrite(n: int, e: int) -> str:
    return f"{n} presets{SEP}{e} will be overwritten"


def will_skip(n: int, e: int) -> str:
    return f"{n} presets{SEP}{e} already rendered, will be skipped"


def all_exist(n: int) -> str:
    return f"Nothing to render{SEP}all {n} already exist"


NO_PRESETS = "No presets in this folder"

# ---- Footer, during and after ---------------------------------------------


def progress(done: int, total: int, failed: int) -> str:
    s = f"{done} / {total}"
    return f"{s}{SEP}{failed} failed" if failed else s


STARTING = "starting…"


def eta(seconds: float) -> str:
    if seconds < 25:
        return "a few seconds left"
    if seconds < 90:
        return "about 1 min left"
    return f"about {round(seconds / 60)} min left"


def elapsed(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def silent(n: int) -> str:
    return f"{n} silent"


def done_clean(n: int, t: str) -> str:
    return f"{n} rendered{SEP}{t}"


def done_filtered(n: int, skipped: int, synth: str, t: str) -> str:
    return f"{n} rendered{SEP}{skipped} skipped, no {synth}{SEP}{t}"


def done_failed(n: int, failed: int, t: str) -> str:
    return f"{n} rendered{SEP}{failed} failed{SEP}{t}"


def executor_broken(n: int, abandoned: int) -> str:
    return f"{n} rendered{SEP}{abandoned} abandoned{SEP}executor broken"


def stopped(done: int, total: int, skip_on: bool, strangers: int) -> str:
    head = f"Stopped{SEP}{done} of {total} done{SEP}"
    if not skip_on:
        return head + "Skip existing is off"
    if strangers:
        return head + f"{strangers} older files will also be skipped"
    return head + "Skip existing will resume"


RENDER = "Render"
STOP = "Stop"
FAILURES = "Failures"
COLLISIONS = "Collisions"


def render_n(n: int) -> str:
    return f"Render {n}"


# ---- Dialogs --------------------------------------------------------------

CANCEL = "Cancel"
DONE = "Done"
COPY = "Copy"
CLOSE = "Close"
RENAME = "Rename"
OVERWRITE = "Overwrite"
DELETE = "Delete"
SAVE = "Save"
DISCARD = "Discard"


def retry_n(n: int) -> str:
    return f"Retry {n}"


def failures_title(n: int) -> str:
    return f"{n} presets failed"


def batch_stopped_title(n: int) -> str:
    return f"Batch stopped after {n} renders"


def failures_hint(n: int) -> str:
    return f"Retry re-renders these {n} with the settings this batch used, whatever the window says now."


FAILURES_HINT_CHANGED = (
    "Settings have changed since this batch. Retry still uses the settings the "
    "batch ran with. Press Render to use the current ones."
)


def executor_hint(n: int) -> str:
    return f"Re-run with Skip existing to render the {n} presets that never started."


def executor_row(n: int) -> str:
    return f"{n} presets abandoned"


def collisions_title(n: int) -> str:
    return f"{n} filename collisions"


COLLISIONS_HINT = (
    "Two presets cannot write the same file. The default Filename {subdir}/{preset} keeps "
    "folders apart; Separate folders per synth keeps a Serum 1 and a Serum 2 preset with "
    "the same name apart."
)
COL_FILE = "File"
COL_CLAIMED_BY = "Claimed by"
COL_PRESET = "Preset"
COL_ERROR = "Error"


def more_rows(n: int) -> str:
    return f"…{n} more"


PROFILES_TITLE = "Profiles"
PROFILE_HEADER = "Profile"
BUILT_IN = "Built in"
MANAGER_HINT = "Built-in profiles can be duplicated, but not renamed or deleted."


def confirm_delete(name: str) -> str:
    return f'Delete "{name}"?'


def confirm_overwrite(name: str) -> str:
    return f'"{name}" already exists. Overwrite it?'


SAVE_PROFILE_TITLE = "Save profile"
LABEL_NAME = "Name"
UNSAVED_TITLE = "Unsaved changes"


def unsaved_body(name: str | None) -> str:
    what = f'your changes to "{name}"' if name else "the current settings"
    return f"Switching profiles discards {what}. Save them as a profile first to keep them."
