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
