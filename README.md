# serum-render-gui

Desktop front end for [serum-render](https://github.com/wiillownet/serum-render):
batch-render Serum 1 (`.fxp`) and Serum 2 (`.SerumPreset`) presets to audio,
without retyping a 25-flag command.

**Status: early. There is no window yet.** The planning and process-launch
layers are written and tested; the Qt UI is not.

## How it works

The GUI never renders in its own process. DawDreamer hangs when driven off the
main thread, so rendering is spawned as `python -m serum_render ... --json` and
the NDJSON event stream drives the progress and failure reporting.

Planning is the exception and stays in-process: discovery, preset counting and
filename-collision detection re-run continuously as you type, which a subprocess
per keystroke cannot do. That path imports only serum-render's discovery layer,
which is main-process-only and never loads a plugin.

## Requirements

- Python 3.11 or 3.12 (matching serum-render's DawDreamer wheel coverage)
- Serum 1 and/or Serum 2 installed

## From source

```bash
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pytest tests/ -q
```

## Licence

GPL-3.0-or-later, matching serum-render. PySide6 is used under the LGPL.
