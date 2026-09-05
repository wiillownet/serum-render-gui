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

**Measured, and it matters:** the real Serum 1 factory library has **253 collisions** under the default `{preset}` template (Splice packs ship the same preset at a folder root and inside a subfolder), so a fresh install would be blocked from rendering anything. `{subdir}/{preset}` brings it to zero on both factory libraries. **Open: whether the GUI's default template should therefore be `{subdir}/{preset}` rather than the CLI's `{preset}`.**

## [2026-09-05] `interpreter()` refuses to guess when frozen

**Decision:** `interpreter()` returns `sys.executable` normally, and raises when `sys.frozen` is set and `BUNDLED_INTERPRETER` has not been configured.

**Reason:** in a PyInstaller bundle `sys.executable` is the GUI binary, so `[sys.executable, "-m", "serum_render"]` re-opens the GUI instead of rendering — silently, and recursively. Written now rather than at packaging time because retrofitting it means re-testing every launch path. No plausible bundled path is guessed, because a wrong path fails at a worse moment than a missing one.
