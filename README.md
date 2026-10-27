<p align="center">
  <img src="assets/banner.png" alt="serum-render-gui">
</p>

Desktop front end for [serum-render](https://github.com/wiillownet/serum-render):
batch-render Serum 1 (`.fxp`) and Serum 2 (`.SerumPreset`) presets to audio.

<p align="center">
  <img src="assets/screenshot.png" alt="Main window" width="640">
</p>

## Features

- Counts presets, checks which synth each needs and flags filename collisions
  before rendering.
- Skip existing files resumes a stopped batch. Failed presets can be retried
  with the settings the batch used.
- Profiles save sound, audio and filename settings under a name.
- WAV, FLAC, OGG Vorbis or NPY output. Single note or a MIDI file.
- Filename templates with `{preset}`, `{subdir}`, `{folder}`, `{format}`,
  `{note}` and `{velocity}`.
- Log window (View > Log): launch command, each preset as it starts and
  finishes, stderr.

## Requirements

- macOS, Windows or Linux with Python 3.11 or 3.12
- Serum 1 and/or Serum 2

## Install

**macOS app:** download `Serum Render` from the
[latest release](https://github.com/wiillownet/serum-render-gui/releases/latest).
It is not signed yet, so the first launch is right-click > Open.

**From source:**

```bash
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/serum-render-gui
```

**Build the app yourself:**

```bash
sh packaging/build-macos.sh
```

This downloads a standalone Python, installs the package into it and wraps
the result in `dist/Serum Render.app`.

First launch opens a setup sheet that detects the plugins and the Xfer preset
folder. Confirm them and choose an output folder.

## How it works

Rendering runs as `python -m serum_render ... --json` in a child process. Its
NDJSON event stream drives the progress bar, the failure list and the log.
Planning (discovery, counting, collision detection) runs in-process on every
change and never loads a plugin.

## Development

```bash
.venv/bin/pytest tests/ -q
```

Tests use Qt's offscreen platform and need no plugins.

## Licence

GPL-3.0-or-later, matching serum-render. PySide6 is used under the LGPL.
