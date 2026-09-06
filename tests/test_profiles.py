"""Profile store: JSON round trip, built-in protection, duplicate naming."""
import pytest

from serum_render_gui.planner import RenderParams
from serum_render_gui.profiles import BUILT_IN, PROFILE_KEYS, ProfileStore


def test_built_in_is_render_params_defaults(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    p = RenderParams(presets_dir=tmp_path, output_dir=tmp_path)
    assert store.get(BUILT_IN) == {k: getattr(p, k) for k in PROFILE_KEYS}
    assert store.get(BUILT_IN)["tail"] == 0.5


def test_save_and_reload(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    values = {**store.get(BUILT_IN), "duration": 2.0}
    store.save("Long", values)
    again = ProfileStore(tmp_path / "p.json")
    assert again.names() == [BUILT_IN, "Long"]
    assert again.get("Long")["duration"] == 2.0


def test_built_in_cannot_be_changed(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    with pytest.raises(ValueError):
        store.save(BUILT_IN, store.get(BUILT_IN))
    with pytest.raises(ValueError):
        store.delete(BUILT_IN)
    with pytest.raises(ValueError):
        store.rename(BUILT_IN, "x")


def test_duplicate_names_and_orders_below_source(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    store.save("A", store.get(BUILT_IN))
    store.save("B", store.get(BUILT_IN))
    assert store.duplicate("A") == "A copy"
    assert store.duplicate("A") == "A copy 2"
    assert store.names() == [BUILT_IN, "A", "A copy 2", "A copy", "B"]
    assert store.duplicate(BUILT_IN) == f"{BUILT_IN} copy"
    assert store.names()[1] == f"{BUILT_IN} copy"


def test_corrupt_store_names_the_file(tmp_path):
    (tmp_path / "p.json").write_text("{not json")
    with pytest.raises(ValueError, match="p.json"):
        ProfileStore(tmp_path / "p.json")
