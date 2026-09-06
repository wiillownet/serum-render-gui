"""Named render profiles: the parameter set that travels.

One JSON file, `{"version": 1, "profiles": {name: {...}}}`, at the platform
app-data location. One built-in profile, whose values are RenderParams' own
defaults so the two cannot drift (docs/decisions.md).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .planner import RenderParams

PROFILE_KEYS = (
    "note", "velocity", "duration", "tail", "midi_path", "sample_rate",
    "bit_depth", "output_format", "filename_template", "deterministic", "no_recurse",
)
BUILT_IN = "Default"
_DEFAULTS = {
    f.name: f.default for f in dataclasses.fields(RenderParams) if f.name in PROFILE_KEYS
}


def built_in_values() -> dict:
    return dict(_DEFAULTS)


class ProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._user: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except ValueError as exc:
            raise ValueError(
                f"Unreadable profile file {self.path}: {exc}. Move it aside to start fresh."
            ) from exc
        if data.get("version") != 1 or not isinstance(data.get("profiles"), dict):
            raise ValueError(f"Unreadable profile file {self.path}: expected version 1.")
        self._user = {
            name: {k: v for k, v in values.items() if k in PROFILE_KEYS}
            for name, values in data["profiles"].items()
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": 1, "profiles": self._user}, indent=2), encoding="utf-8"
        )

    def names(self) -> list[str]:
        return [BUILT_IN, *self._user]

    def is_built_in(self, name: str) -> bool:
        return name == BUILT_IN

    def get(self, name: str) -> dict:
        if name == BUILT_IN:
            return built_in_values()
        return {**_DEFAULTS, **self._user[name]}

    def save(self, name: str, values: dict) -> None:
        if name == BUILT_IN:
            raise ValueError("The built-in profile cannot be overwritten.")
        self._user[name] = {k: values[k] for k in PROFILE_KEYS}
        self._save()

    def rename(self, old: str, new: str) -> None:
        if old == BUILT_IN:
            raise ValueError("The built-in profile cannot be renamed.")
        values = self._user.pop(old)
        self._user[new] = values
        self._save()

    def delete(self, name: str) -> None:
        if name == BUILT_IN:
            raise ValueError("The built-in profile cannot be deleted.")
        del self._user[name]
        self._save()

    def duplicate(self, name: str) -> str:
        """Copy `name` to `name copy` (then `copy 2`, ...) directly after it."""
        base = f"{name} copy"
        new, n = base, 2
        while new in self.names():
            new, n = f"{base} {n}", n + 1
        values = self.get(name)
        if name == BUILT_IN:
            self._user = {new: values, **self._user}
        else:
            items = list(self._user.items())
            i = next(i for i, (k, _) in enumerate(items) if k == name)
            items.insert(i + 1, (new, values))
            self._user = dict(items)
        self._save()
        return new
