"""Pure-function coverage for the subprocess runner. No Qt event loop."""
from __future__ import annotations

import sys

import pytest

from serum_render_gui.runner import (
    JSON_SCHEMA,
    SchemaMismatch,
    interpreter,
    parse_event,
)


# ---- parse_event ----------------------------------------------------------


def test_parses_each_event_kind():
    assert parse_event('{"event":"start","schema":1,"total":9,"workers":7}')["total"] == 9
    assert parse_event('{"event":"result","status":"ok","path":"/a.fxp"}')["status"] == "ok"
    assert parse_event('{"event":"done","ok":9,"skipped":0,"failed":0}')["ok"] == 9


@pytest.mark.parametrize(
    "line",
    ["", "   ", "not json at all", "[1,2,3]", '"a string"', '{"no":"event key"}'],
)
def test_unparseable_lines_are_skipped_not_fatal(line):
    """loky workers inherit the parent's stdout, so a C-level write could in
    principle split a line. Never observed, but skipping is free."""
    assert parse_event(line) is None


def test_a_wrong_schema_is_a_hard_stop():
    """Mis-parsing a changed shape silently is the failure this prevents."""
    with pytest.raises(SchemaMismatch) as exc:
        parse_event('{"event":"start","schema":2,"total":1}')
    assert "2" in str(exc.value) and str(JSON_SCHEMA) in str(exc.value)


def test_a_start_event_without_a_schema_is_rejected():
    with pytest.raises(SchemaMismatch):
        parse_event('{"event":"start","total":1}')


def test_schema_is_only_checked_on_start():
    """Only `start` carries it; demanding it everywhere would reject every
    result line."""
    assert parse_event('{"event":"result","status":"ok"}') is not None


def test_a_skipped_result_carries_its_reason():
    """serum-render 0.3.1 distinguishes 'already rendered' from 'no plugin',
    which the GUI must word differently."""
    event = parse_event('{"event":"result","status":"skipped","reason":"no_plugin"}')
    assert event["reason"] == "no_plugin"


# ---- interpreter ----------------------------------------------------------


def test_interpreter_is_this_python_when_not_frozen():
    assert interpreter() == sys.executable


def test_frozen_without_a_bundled_interpreter_refuses_loudly(monkeypatch):
    """sys.executable is the GUI binary in a bundle, so launching it would
    re-open the GUI instead of rendering — silently, and recursively."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(RuntimeError, match="bundled interpreter"):
        interpreter()


def test_frozen_uses_the_configured_interpreter(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "serum_render_gui.runner.BUNDLED_INTERPRETER", "/app/python3"
    )
    assert interpreter() == "/app/python3"


# ---- orphan reaper --------------------------------------------------------


def test_reaper_refuses_a_pid_that_is_not_a_render(monkeypatch):
    """A recycled pid must never be killed. This process is a pytest run."""
    import os

    from serum_render_gui.runner import looks_like_render, reap_orphan

    assert looks_like_render(os.getpid()) is False
    assert reap_orphan(os.getpid(), os.getpgid(0)) is False
    assert reap_orphan(0, 0) is False


def test_reaper_kills_a_render_group(monkeypatch):
    killed = []
    monkeypatch.setattr("serum_render_gui.runner.looks_like_render", lambda pid: True)
    monkeypatch.setattr("serum_render_gui.runner.kill_group", killed.append)
    from serum_render_gui.runner import reap_orphan

    assert reap_orphan(1234, 1234) is True
    assert killed == [1234]
