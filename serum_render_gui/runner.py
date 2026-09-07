"""Launch serum-render as a subprocess and turn its NDJSON stream into signals.

Boundary A: the render never runs in this process. DawDreamer hangs when driven
off the main thread, and a frozen PySide6 app must never host loky's spawn
workers — `spawn` re-executes sys.executable, which in a bundle is the app
itself. See the GUI plan and serum-render's docs/decisions.md.

`parse_event`, `build_argv` (in planner) and `interpreter` are pure and carry the
tests; the QProcess machinery around them is not unit-testable without an event
loop and is deliberately thin.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from .planner import RenderParams, build_argv

# The --json stream version this GUI understands. serum-render bumps it only on
# an incompatible shape change, so a mismatch is a hard stop rather than a guess.
JSON_SCHEMA = 1

# How much of the child's stderr to keep. A broken executor emits one FAIL line
# per abandoned job — thousands — and only the tail is diagnostic.
_STDERR_TAIL = 200

# Set at packaging time to the bundled interpreter inside sys._MEIPASS.
# Deliberately None until packaging exists: see `interpreter`.
BUNDLED_INTERPRETER: str | None = None


class SchemaMismatch(RuntimeError):
    """The child announced an event-stream version this GUI cannot read."""


def interpreter() -> str:
    """The interpreter to run `-m serum_render` with.

    Not `sys.executable` unconditionally. In a PyInstaller bundle that is the
    GUI binary, so launching it re-opens the GUI instead of rendering — silently,
    and recursively. Failing loudly is the only safe behaviour until a bundled
    interpreter is actually configured.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    if BUNDLED_INTERPRETER is None:
        raise RuntimeError(
            "Running frozen with no bundled interpreter configured. "
            "sys.executable is the GUI binary here, so launching it would "
            "re-open the GUI instead of rendering. Set "
            "serum_render_gui.runner.BUNDLED_INTERPRETER at packaging time."
        )
    return BUNDLED_INTERPRETER


# serum-render reports each render's peak. Below -60 dBFS a 1.5 s one-shot is
# silence for any practical purpose (a real preset measured -75 dBFS: nothing
# audible); the engine's own warning threshold is far lower.
SILENT_PEAK = 1e-3


def is_silent(ev: dict) -> bool:
    """True for an ok result whose render never rose above SILENT_PEAK."""
    peak = ev.get("peak")
    return peak is not None and peak < SILENT_PEAK


def parse_event(line: str) -> dict | None:
    """One NDJSON line to an event, or None if it is not one.

    Unparseable lines are skipped rather than fatal: loky workers inherit the
    parent's stdout, so a plugin printing from C could in principle split a line.
    That has never been observed, but the consumer-side mitigation is free, and
    `done`'s counts are trusted over a local tally for the same reason.
    """
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or "event" not in event:
        return None
    if event["event"] == "start" and event.get("schema") != JSON_SCHEMA:
        raise SchemaMismatch(
            f"serum-render emitted event schema {event.get('schema')!r}; "
            f"this GUI understands {JSON_SCHEMA}. Update serum-render-gui."
        )
    return event


class RenderRunner(QObject):
    """One batch. Owns the child process and its lifetime."""

    started = Signal(int, int)  # total, workers
    # The child's pid and process-group id, once known. The GUI records them
    # so a later launch can reap a tree orphaned by a force-quit.
    launched = Signal(int, int)  # pid, pgid
    job_started = Signal(dict)  # {"path"}: a worker took this preset (serum-render >= 0.5)
    result = Signal(dict)
    done = Signal(dict)
    failed = Signal(str)
    # A user Stop finished tearing the tree down. Carries nothing: the GUI
    # already has its own tally, and the child never gets to emit `done`.
    stopped = Signal()
    # One line of the child's stderr, as it arrives. For the log window.
    stderr_line = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._pgid: int | None = None
        self._stopping = False
        self._saw_done = False
        self._done_event: dict | None = None
        self._stderr: deque[str] = deque(maxlen=_STDERR_TAIL)
        # The parameters this batch actually ran with. Retry re-submits these
        # rather than re-reading the widgets, which may have changed since.
        self.launched_with: dict | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None

    def start(self, params: RenderParams) -> None:
        if self._proc is not None:
            raise RuntimeError("A render is already running.")

        self._pgid = None
        self._stopping = False
        self._saw_done = False
        self._done_event = None
        self._stderr.clear()
        self.launched_with = params.as_dict()

        proc = QProcess(self)
        # New session, so Stop can kill the whole tree. Qt calls setsid(2) in its
        # own C++ child path; PySide6 has no setChildProcessModifier (shiboken
        # never wrapped the std::function overloads), and this is better anyway.
        if sys.platform != "win32":
            proc.setUnixProcessParameters(
                QProcess.UnixProcessFlag.CreateNewSession
            )
        proc.setProgram(interpreter())
        proc.setArguments(["-m", "serum_render", *build_argv(params)])
        proc.setReadChannel(QProcess.ProcessChannel.StandardOutput)
        proc.started.connect(self._on_started)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        proc.start()

    def stop(self) -> None:
        """Kill the whole process group. Workers are not the direct child, so
        killing only that strands them rendering to disk unwatched.

        Idempotent: closing the window and quitting the app both call this,
        and a second killpg on a group that is already exiting raises EPERM
        on macOS (verified) rather than ESRCH."""
        if self._stopping:
            return
        self._stopping = True
        self._kill_tree()

    def _on_started(self) -> None:
        if self._proc is None or sys.platform == "win32":
            return
        pid = int(self._proc.processId())
        # Only killpg a group this process leads. Without the guard, a
        # CreateNewSession that silently did not take means killpg targets the
        # GUI's own process group and takes the app down with the render.
        try:
            self._pgid = pid if os.getpgid(pid) == pid else None
        except OSError:
            self._pgid = None
        self.launched.emit(pid, self._pgid or 0)

    def _on_stdout(self) -> None:
        proc = self._proc
        if proc is None:
            return
        # Qt owns the line buffer, so there is no partial-line splitter here.
        while proc.canReadLine():
            line = bytes(proc.readLine()).decode("utf-8", "replace")
            try:
                event = parse_event(line)
            except SchemaMismatch as exc:
                self._stopping = True
                self._kill_tree()
                self.failed.emit(str(exc))
                return
            if event is None:
                continue
            kind = event["event"]
            if kind == "start":
                self.started.emit(event.get("total", 0), event.get("workers", 0))
            elif kind == "job_start":
                self.job_started.emit(event)
            elif kind == "result":
                self.result.emit(event)
            elif kind == "done":
                # Held until the child exits, so `running` is False by the
                # time a consumer reacts and can start the next batch.
                self._saw_done = True
                self._done_event = event

    def _on_stderr(self) -> None:
        proc = self._proc
        if proc is None:
            return
        # Draining is mandatory, not diagnostic: an undrained pipe fills and
        # deadlocks the child, and a broken executor writes thousands of lines.
        text = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
        for line in text.splitlines():
            if line.strip():
                self._stderr.append(line)
                self.stderr_line.emit(line)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._proc = None
            self.failed.emit(
                f"Could not start serum-render: {interpreter()} -m serum_render"
            )

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self._proc = None
        if self._saw_done:
            self.done.emit(self._done_event or {})
            return
        if self._stopping:
            self.stopped.emit()
            return
        tail = "\n".join(self._stderr)
        if exit_code == 2:
            # Validation refusal. The message names the missing flag or path and
            # is more useful verbatim than "exit code 2" ever is.
            self.failed.emit(tail or "serum-render rejected the arguments.")
        else:
            self.failed.emit(
                f"serum-render exited unexpectedly (code {exit_code})."
                + (f"\n{tail}" if tail else "")
            )

    def _kill_tree(self) -> None:
        proc = self._proc
        if proc is None:
            return
        pid = int(proc.processId())
        if pid <= 0:
            return
        if sys.platform == "win32":
            # taskkill walks parent-PID links; loky's workers are grandchildren.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        elif self._pgid is not None:
            try:
                kill_group(self._pgid)
            except OSError:
                proc.kill()
        else:
            proc.kill()


def kill_group(pgid: int) -> None:
    os.killpg(pgid, signal.SIGKILL)


def looks_like_render(pid: int) -> bool:
    """True if `pid` is alive and is a `python -m serum_render` process.
    Guards the orphan reaper against a recycled pid."""
    if sys.platform == "win32":
        cmd = ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
    else:
        cmd = ["ps", "-o", "command=", "-p", str(pid)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False).stdout
    return "serum_render" in out


def reap_orphan(pid: int, pgid: int) -> bool:
    """Kill a render tree a previous GUI process left behind (it was
    force-quit, so its own Stop never ran). Returns True if something was
    killed. Workers hold both ends of loky's queue and never notice the
    parent is gone, so nothing in the tree exits on its own."""
    if pid <= 0 or not looks_like_render(pid):
        return False
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
        return True
    try:
        kill_group(pgid if pgid > 0 else pid)
    except OSError:
        return False
    return True
