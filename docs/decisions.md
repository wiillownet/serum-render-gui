<!-- Decisions log. Records the *why* behind non-trivial choices (and what was
     rejected), so they aren't silently re-litigated or reversed. The *what/when*
     lives in git history; this file holds the reasoning git can't. -->

# Decisions

## [2026-09-05] PySide6, because Tkinter is not installed anywhere here

**Decision:** PySide6-Essentials, pinned as that rather than the `PySide6` meta-package.

**Reason:** Not the widget library's ergonomics — the honest reason is availability. Tkinter does not exist on any interpreter this project can run. Measured: homebrew 3.14.6, pyenv 3.12.13 / 3.13.13 / 3.14.3 and both project venvs all raise `No module named '_tkinter'`; the only interpreter on this machine with Tk is `/usr/bin/python3` at 3.9.6, which `requires-python >=3.11` excludes. That is a dependency on how the interpreter was built, which pip cannot fix, and it recurs on every Python bump. `PySide6-Essentials` rather than `PySide6` because the meta-package also resolves `PySide6-Addons`, a 317MB macOS wheel, for modules this app never imports.

**Alternatives considered:** Tkinter — pitched twice as the zero-dependency option before anyone checked whether it was importable; it was not. PyQt6 — smaller wheels, but GPL-or-commercial would lock this repo's licence forever where PySide6's LGPL leaves it open.

**Honest counterweight:** `QProcess` is *worse* than `subprocess.Popen(start_new_session=True)` on the most safety-critical line, because `Popen` makes `pgid == pid` true by construction and needs no guard. PySide6 wins on interpreter availability, not on process handling.

## [2026-09-05] Render behind the CLI; plan in-process

**Decision:** Rendering spawns `python -m serum_render ... --json` and is driven by the NDJSON stream. Planning — discovery, counting, collision detection, resolved output paths — runs in this process against `serum_render.discover`.

**Reason for the split, rendering side:** a frozen PySide6 app must never host loky's spawn workers. `spawn` re-executes `sys.executable`, which in a bundle is the app binary, so the render pool would re-launch the GUI. Shipping an app is committed intent, not a hedge, which is what makes this load-bearing. Notably *not* the reasons first recorded: crash isolation is illusory (dawdreamer only loads inside a worker either way) and loky's own `shutdown(wait=True, kill_workers=True)` is one line against ~40 for process-group killing.

**Reason for the split, planning side:** the design specifies collision detection as continuous, re-run whenever the preset folder, filename template, output format or separate-folders setting changes. A subprocess per keystroke is not a design. This is safe only because `serum_render.discover` is main-process-only and its import graph is stdlib plus mido — nothing reached from the GUI process imports dawdreamer. **That property is the whole justification and must be re-checked before importing anything else from serum-render.**

**Consequence:** `--dry-run --json` as the "count presets" mechanism is dead; counting is in-process, instant, and needed continuously anyway.

**Alternatives considered:** extracting `plan_jobs()` from serum-render's CLI and driving `pool.iter_jobs` from a QThread — roughly 200 lines cheaper and it dissolves the "welded to a private API" objection, but it forecloses the bundled-app path. Parked, not rejected on merit.

## [2026-09-05] Stop kills the process group, with a guard

**Decision:** `QProcess.setUnixProcessParameters(UnixProcessFlag.CreateNewSession)` at launch, then `os.killpg` on Stop — but only after confirming `os.getpgid(pid) == pid`. Windows uses `taskkill /F /T /PID`. Every shutdown path (Stop, window close, app quit) uses the same kill.

**Reason:** the workers are grandchildren, not the direct child, so killing the child alone strands them rendering to disk unwatched — loky has no parent-death watchdog, and workers hold both ends of the call queue so they never see EOF. The `pgid == pid` guard is not defensive padding: without it, a `CreateNewSession` that silently did not take means `killpg` targets the GUI's own process group and takes the app down with the render. Verified: stopping a 3506-preset batch after 10 results left zero `dawdreamer` and zero `serum_render` survivors.

**Alternatives considered:** `setChildProcessModifier` — does not exist in PySide6; shiboken never wrapped the `std::function` overloads (confirmed `False` on 6.11.2). `CREATE_NEW_PROCESS_GROUP` on Windows — its only capability is `GenerateConsoleCtrlEvent`, which a kill-based Stop does not use, and its documented side effect is making the child ignore Ctrl-C.

## [2026-09-05] Collisions are detected on composed stems, not resolved paths

**Decision:** `planner._collisions` groups the stems `compose_filename` produces. It deliberately does not read what `resolve_output_paths` returns.

**Reason:** `resolve_output_paths` disambiguates duplicates to `foo_1`, `foo_2`, so reading its output would report zero collisions every time — the check would silently always pass. The design's stated premise for blocking ("one render is destroyed and nothing records which") is out of date: serum-render fixed that in 0.2.0. The surviving reason to block is the design's second one, which is the stronger argument anyway — `_1` suffixes invent filenames the user never asked for. Empty stems are excluded, because `resolve_output_paths` gives each a distinct `preset_NNNN` fallback and they never actually contend.

**Measured, and it matters:** the real Serum 1 factory library has **253 collisions** under the default `{preset}` template (Splice packs ship the same preset at a folder root and inside a subfolder), so a fresh install would be blocked from rendering anything. `{subdir}/{preset}` brings it to zero on both factory libraries. **Resolved 2026-09-05: the GUI's default template is `{subdir}/{preset}`, not the CLI's `{preset}`.** The CLI keeps its own default — it disambiguates rather than blocking, so it is not broken by collisions the way the GUI would be. `tests/test_planner.py` pins the GUI default so it cannot drift back.

## [2026-09-05] `interpreter()` refuses to guess when frozen

**Decision:** `interpreter()` returns `sys.executable` normally, and raises when `sys.frozen` is set and `BUNDLED_INTERPRETER` has not been configured.

**Reason:** in a PyInstaller bundle `sys.executable` is the GUI binary, so `[sys.executable, "-m", "serum_render"]` re-opens the GUI instead of rendering — silently, and recursively. Written now rather than at packaging time because retrofitting it means re-testing every launch path. No plausible bundled path is guessed, because a wrong path fails at a worse moment than a missing one.

## [2026-09-05] One global focus treatment, derived rather than designed

**Decision:** Every focusable widget gets `border: 1px solid #4A4E57` on focus — the same token the two drawn text fields use. Applied once, globally, in the stylesheet rather than per widget.

**Reason:** the mockups contain exactly one focus treatment, and only on the two `QLineEdit`s that get typed into (the Save-profile name and the profile manager's rename field). Every other widget would otherwise fall through to Qt's default focus rectangle, which is drawn from the platform palette and will not match anything in this app. The design handoff flags this as the single largest gap and offers this derivation; taking it is cheaper than leaving focus visually undefined across most of the UI, and a global rule is what makes it consistent.

**Explicitly not signed off by the design.** It is a derivation from a neighbouring token, and it is recorded here so a later reader knows it was a judgement call rather than a spec. Revisit if it reads wrong against the accent — the risk is that `#4A4E57` is close enough to `#383C44` (the ghost-button border) that focus on a button is hard to see.

**Alternatives considered:** leaving Qt's native focus rectangle — rejected, it is the one thing guaranteed not to match a fully custom dark palette. Using the accent `#A6E04D` for focus — rejected because accent means *go* in this app (Render, progress, a resolved path), and a fourth meaning would dilute it; the design is explicit that nothing else may borrow it.

## [2026-09-05] One built-in profile, 1.5s total

**Decision:** Ship a single built-in profile — duration `1.0`, tail `0.5` (1.5s total), 44100 Hz, 16-bit, WAV, template `{subdir}/{preset}`. These are `RenderParams`' own defaults, so the code default and the shipped profile cannot drift apart. `tail` is therefore `0.5`, not the CLI's `1.0`.

**Reason:** the design names three built-ins — `Quick preview`, `Archival 24-bit`, `Stems 48k` — but specifies no parameters for any of them; the names were placeholders. The owner has one real workflow, the 1.5s preview pass, and does not yet know what the others should be. Shipping three profiles with invented values would put numbers on screen that nobody chose, and the revert tooltip quotes a built-in *by name*, so a made-up profile becomes a made-up sentence in the UI.

**Alternatives considered:** shipping no built-in and opening on `(no profile)` — a state the design already defines, but it leaves a fresh install with an empty strip and a revert arrow pointing at nothing. Shipping all three with guessed values — rejected above.

**Open:** the other two profiles, if they turn out to be real workflows. Adding one later is a row in a JSON file, not a design change.

## [2026-09-05] "Separate folders per synth" edits the template; it is not its own setting

**Decision:** The checkbox is a shortcut for editing the filename template. The template string stays the single source of truth.

```
checked  <=>  the template starts with "{format}/"
check    ->   prepend "{format}/"
uncheck  ->   strip that prefix
```

With the default template that yields `{format}/{subdir}/{preset}` → `serum1/Bass/Punch.wav`.

**Reason:** **Prepend rather than replace**, because `{format}` and `{subdir}` do different jobs — one groups by synth, the other mirrors the preset tree — and both are wanted at once. The design assumed the default was `{preset}`, so it framed the toggle as `{preset}` ⟷ `{format}/{preset}`; that framing does not survive the default changing, but the intent does.

**Why "starts with" and not "contains":** a hand-typed `{preset}-{format}` produces separate *files*, not separate *folders*, so ticking the box there would make the label lie. The narrow rule keeps the checkbox honest, and still auto-ticks when someone types the prefix by hand.

**Alternatives considered:** a separate boolean applied on top of the template — rejected, it creates two sources of truth for the output layout and a user who hand-edits the template gets silently overridden.

## [2026-09-05] The GUI always passes `--skip-missing-format`

**Decision:** `build_argv` emits the flag unconditionally. It is not a parameter.

**Reason:** there is no case where the GUI wants the other behaviour. The design requires it to render what it can and state the split in the footer, so it must never call the CLI path that refuses a whole mixed library. When no plugin is missing the flag is a no-op; when nothing is renderable the GUI has already disabled Render, so the CLI's exit 2 never fires. It also closes a race: a preset landing in the folder between planning and launching would otherwise abort the entire batch over a file the GUI never saw.

**Alternatives considered:** keeping it as a parameter defaulting to `True` — rejected. A flag that must always be one value is not a parameter, it is a footgun with a default; deleting it makes the mistake unmakeable rather than merely unlikely.

## [2026-09-06] Retry deletes the failed outputs and re-runs the whole batch with `--skip-existing`

**Decision:** Retry unlinks each failed preset's output file (mapped through `Plan.preset_paths` / `Plan.output_paths`, snapshotted at launch), then re-submits the batch's original `RenderParams` with `skip_existing=True`. The footer's denominator is the failure count, and `reason: "exists"` results are not counted.

**Reason:** the design's "re-submit the failed preset list" cannot be built: the CLI takes one path, and single-file mode sets `presets_root=None`, which collapses `{subdir}` and lands `Bass/alpha.wav` at `alpha.wav`, potentially over a different preset's render. Re-running the identical job list keeps every `_N` disambiguation suffix on the same preset. Verified against real renders: a failed preset's stale output survives (most failures raise before `write_audio`), so without the unlink `--skip-existing` would skip exactly the file the user asked to fix. Measured overhead on already-rendered presets is under a second per 1500.

**Alternatives considered:** per-preset CLI invocations (wrong output paths, above); ignoring `--skip-existing` on retry and re-rendering everything (re-renders thousands to fix two).

## [2026-09-06] `done` is emitted from the finished slot, not from the stream

**Decision:** `RenderRunner` holds the `done` event until the child process exits, then emits it. A user Stop emits a new `stopped` signal from the same slot.

**Reason:** the `done` line arrives while loky is still shutting workers down. Emitting on the line let the GUI unlock and accept a Render click while `running` was still true, which raised "A render is already running." Emitting on exit makes "the batch is over" and "the process is gone" the same moment. The stopped signal exists because a kill produces no `done` line and the GUI otherwise never learns the tree is down.

## [2026-09-06] QMainWindow with `setFixedSize` in one method

**Decision:** `MainWindow._fit` is the only place the window is sized: `setFixedSize(640, central.sizeHint().height() + menuBar().sizeHint().height())`, called once at construction and on every section toggle.

**Reason:** the menu bar is needed for the Preferences item (the containing `QMenu` is mandatory for ⌘, on macOS), which rules out the plain-`QWidget` alternative. `setFixedSize` on every toggle is what actually pins both dimensions and disables zoom; `setFixedWidth` alone leaves height draggable. Verified heights on cocoa: 289 collapsed, 445 / 410 / 375 / 375 per section, 738 all open, matching the design table exactly. `tests/test_window.py` pins the deltas. Making the window resizable later is this one method plus a width policy.

## [2026-09-06] Fractional font sizes go on QFont, integer ones in QSS

**Decision:** 9.5 / 10.5 / 11.5px faces are set via `style.sans()` / `style.mono()` (`setPointSizeF`, converted with the screen's logical DPI, which is 72 on macOS so px == pt). The stylesheet sets no `font-size` except the 12px button label and 11px tooltip, so a widget font is never overridden by a selector.

**Reason:** QSS parses fractional px inconsistently, and a QSS `font-size` on a selector silently overrides the QFont set on a matching widget. Keeping the two disjoint is what makes the row heights come out exact.

## [2026-09-06] Collisions dialog lists every collision and scrolls

**Decision:** the table is capped at four visible rows and scrolls; there is no `…N more` overflow row.

**Reason:** the cap already keeps the dialog inside a 289px parent, so listing everything costs nothing and is strictly more useful than a count. `Copy` still puts the full list on the clipboard.

## [2026-09-06] The built-in profile is named "Default"

**Decision:** one built-in, `Default`, whose values are `RenderParams`' defaults.

**Reason:** the earlier decision fixed the values but not the name. "Default" is what the values are; a workflow name ("Quick preview") would claim something the owner has not decided.

## [2026-09-06] Force-quit orphans are reaped on the next launch

**Decision:** while a batch runs, the child's pid and process-group id are stored in QSettings (`run/orphan_pid`, `run/orphan_pgid`) and removed when the batch ends. On construction, `MainWindow` checks the marker; if that pid is alive and its command line is a `python -m serum_render`, its group is killed.

**Reason:** nothing in the GUI can run after SIGKILL, and loky workers hold both ends of the call queue so they never notice the parent is gone. Verified: SIGKILL of the GUI at 8 of 4271 left nine processes rendering; the next launch removed all of them. The command-line check is what makes a recycled pid safe. The in-child fix (a parent-liveness thread in serum-render's worker initializer) is still the better one and stays an open thread; this is the GUI-side mitigation available today.

**Also fixed here:** `RenderRunner.stop` is idempotent. Closing the window and quitting both call it, and on macOS a second `killpg` on a group that is already exiting raises EPERM (verified), which would surface as a traceback on quit.

## [2026-09-06] Version numbers: SemVer, and the GUI pins serum-render to one minor

**Decision:** serum-render and serum2-preset-loader follow Semantic Versioning. A fix or a performance change with no observable difference is a patch. A new flag, output format, `--json` event, or changed default is a minor. Before 1.0 a minor may also break; `--json` and the flag set freeze at 1.0. This GUI pins `serum-render>=X.Y,<X.(Y+1)` and moves the pin deliberately with each serum-render minor.

**Reason:** the GUI mirrors serum-render's flags and formats in its own tables, so any minor of serum-render can require a GUI change; a pin to one minor makes that a resolver error rather than a silent mismatch. Concretely: the OGG/FLAC formats make serum-render 0.4.0, not 0.3.2, and this GUI moves to `>=0.4,<0.5` in the same change that adds the formats to its combo. The loader's base64 rewrite changed no bytes and no API, so it is 0.1.3.

## [2026-09-07] Log window shows in-flight presets, and exists-skips with them

**Decision:** serum-render 0.5.0's `job_start` event becomes a faint `started  <name>` line, and each result line gets the seconds since its start. Exists-skips on a resume are now logged too (`skipped  <name>  exists`), reversing the 0.4.0 choice to hide them.

**Reason:** the log is for advanced users asking "what is it doing right now"; a start line per submitted preset answers that without inventing a worker number the parent cannot know. The skip-existing check runs in the worker, so every exists-skip gets a start line; hiding the result would leave a started preset that never finishes, which reads as a hang. Pairing start to result by exact path was verified on a live 3-preset batch and a resume.

**Alternatives considered:** a per-worker slot index (honest only under `--deterministic`, approximate on the warm pool: rejected). Suppressing start lines for presets that turn out to be exists-skips (cannot be known at start time).

## [2026-09-07] Provisional copy settled

**Decision:** every string the copy sweep left flagged is now final, and the separator is a middot everywhere (the three em-dash strings were converted). Per-field revert buttons name the value they go back to ("Revert to 48"); the profile-level button says `Revert all to "{name}"`. Footer: "No presets in this folder", "Output path is a file · choose a folder". Collisions hint names both remedies (default template, Separate folders per synth) because a Serum 1 and Serum 2 preset with the same stem collide even under the default template. Unsaved-changes body tells the user how to keep the changes. Log placeholder describes what the log will contain.

**Reason:** the design's revert tooltip named the value and the profile ("Reset to 1.5s from Quick preview"); the profile is gone but naming the value was the useful half, and the baseline is already in hand. The middot was the approved separator for tooltips and the footer, and CORRECTIONS.md asked for one glyph everywhere. Verified: 68 tests, collisions and unsaved dialogs screenshotted at their new heights (560x236, 440x176).

**Alternatives considered:** per-field "Revert" with no value (less useful, same cost). Keeping em dashes in the three sentence-style strings (two conventions to maintain).

## [2026-09-07] Ship as a .app around an embedded Python, nothing frozen

**Decision:** `packaging/build-macos.sh` builds `dist/Serum Render.app` from a pinned python-build-standalone interpreter with this package and serum-render pip-installed into it. The launcher is a shell script that execs that `python3 -m serum_render_gui`. Fonts (IBM Plex Sans variable, Plex Mono Regular and Medium, OFL) and the app icon ship inside the package and are registered at startup. PySide6 is pruned to QtCore, QtGui, QtWidgets, QtSvg and QtDBus plus the cocoa, offscreen, svg and macstyle plugins. Unsigned for now; `SIGN_IDENTITY` runs codesign, and the notarization steps are in the script header.

**Reason:** the 2026-09-05 rule that a frozen GUI must never host the render workers is moot when nothing is frozen: `sys.executable` is a real interpreter, so loky's spawn and `-m serum_render` work unchanged and `BUNDLED_INTERPRETER` stays unused. One interpreter, one build script, no PyInstaller hooks. Verified: the bundle renders three presets end to end through the GUI's own runner, `open` launches it under the name "Serum Render" with the bundle id, and it quits clean. The prune list comes from `otool -L` on the kept modules and plugins, not from guessing. 572MB before pruning, 338MB after; what remains is dawdreamer at 131MB and Qt at 100MB.

**Alternatives considered:** PyInstaller plus a second embedded interpreter for the renderer (two Pythons, no benefit). pipx only (kept as the developer path in the README, not the user-facing one).

## [2026-09-07] The Default profile targets Petri's one-shot map

**Decision:** the built-in Default stays at duration 1.0 s, tail 0.5 s, 44.1 kHz, 16-bit WAV, `{subdir}/{preset}`. Do not raise the tail to serum-render's own 1.0 s default.

**Reason:** 1.0 + 0.5 writes exactly 66150 frames, 1.500 s, which is Petri's default max length; verified that files at exactly 1.5 s still land on its map. WAV because Petri decodes everything to PCM for analysis and exports WAV itself, and a lossy format alters the transient and high-frequency detail its analysis measures. 16-bit because 24 changes nothing Petri reads.

**Alternatives considered:** FLAC (same audio, half the size; a valid user choice, not the default). OGG (lossy, rejected for this use).
