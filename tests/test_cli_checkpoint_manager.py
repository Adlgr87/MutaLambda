"""Tests for cli.checkpoint_manager (JSON/gzip checkpoint artifacts)."""

import gzip
import json
import os
import time
from pathlib import Path

import pytest

from cli.checkpoint_manager import CheckpointManager


@pytest.fixture
def manager(tmp_path) -> CheckpointManager:
    return CheckpointManager(checkpoint_dir=str(tmp_path / "checkpoints"))


@pytest.mark.root
class TestSave:
    def test_creates_directory_on_init(self, tmp_path):
        target = tmp_path / "nested" / "checkpoints"
        CheckpointManager(checkpoint_dir=str(target))
        assert target.is_dir()

    def test_compressed_save_writes_gzip(self, manager):
        path = manager.save({"best_score": 0.5}, generation=3)
        assert path.endswith(".json.gz")
        with gzip.open(path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["generation"] == 3
        assert payload["version"] == "4.0.0"
        assert payload["state"] == {"best_score": 0.5}

    def test_uncompressed_save_writes_plain_json(self, manager, tmp_path):
        path = manager.save({"best_score": 0.5}, generation=1, compress=False)
        assert path.endswith(".json")
        assert json.loads(Path(path).read_text(encoding="utf-8"))["generation"] == 1

    def test_filename_encodes_zero_padded_generation(self, manager):
        path = manager.save({}, generation=7, compress=False)
        assert os.path.basename(path).startswith("gen_0007_")

    def test_explicit_score_overrides_state_score(self, manager):
        path = manager.save({"best_score": 0.1}, generation=1, score=0.9, compress=False)
        assert json.loads(Path(path).read_text(encoding="utf-8"))["best_score"] == 0.9

    def test_score_falls_back_to_state(self, manager):
        path = manager.save({"best_score": 0.42}, generation=1, compress=False)
        assert json.loads(Path(path).read_text(encoding="utf-8"))["best_score"] == 0.42

    def test_metadata_is_persisted(self, manager):
        path = manager.save({}, generation=1, metadata={"run": "abc"}, compress=False)
        assert json.loads(Path(path).read_text(encoding="utf-8"))["metadata"] == {"run": "abc"}

    def test_non_serializable_state_is_stringified(self, manager):
        path = manager.save({"obj": object()}, generation=1, compress=False)
        stored = json.loads(Path(path).read_text(encoding="utf-8"))["state"]["obj"]
        assert isinstance(stored, str)

    def test_save_failure_returns_empty_string(self, manager):
        manager.checkpoint_dir = manager.checkpoint_dir / "gone"
        assert manager.save({}, generation=1, compress=False) == ""


@pytest.mark.root
class TestLoad:
    def test_roundtrip_compressed(self, manager):
        path = manager.save({"best_score": 0.75, "population": [1, 2]}, generation=5)
        loaded = manager.load(path)
        assert loaded["generation"] == 5
        assert loaded["state"]["population"] == [1, 2]

    def test_roundtrip_uncompressed(self, manager):
        path = manager.save({"best_score": 0.25}, generation=2, compress=False)
        assert manager.load(path)["best_score"] == 0.25

    def test_missing_file_returns_none(self, manager, tmp_path):
        assert manager.load(str(tmp_path / "nope.json")) is None

    def test_invalid_json_returns_none(self, manager, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert manager.load(str(path)) is None

    def test_non_dict_payload_returns_none(self, manager, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert manager.load(str(path)) is None

    def test_pickle_payload_is_rejected(self, manager, tmp_path):
        path = tmp_path / "evil.json"
        path.write_text("\x80\x04\x95payload", encoding="utf-8")
        assert manager.load(str(path)) is None

    def test_best_score_backfilled_from_state(self, manager, tmp_path):
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps({"generation": 1, "state": {"best_score": 0.6}}), encoding="utf-8")
        assert manager.load(str(path))["best_score"] == 0.6

    def test_best_score_defaults_to_zero_without_state_score(self, manager, tmp_path):
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps({"generation": 1, "state": {}}), encoding="utf-8")
        assert manager.load(str(path))["best_score"] == 0.0


@pytest.mark.root
class TestListCheckpoints:
    def test_empty_directory(self, manager):
        assert manager.list_checkpoints() == []

    def test_lists_both_formats(self, manager):
        manager.save({}, generation=1, compress=False)
        manager.save({}, generation=2, compress=True)
        items = manager.list_checkpoints()
        assert len(items) == 2
        assert {i["generation"] for i in items} == {1, 2}
        assert all(i["size"] > 0 for i in items)

    def test_sort_by_generation(self, manager):
        for generation in (1, 5, 3):
            manager.save({}, generation=generation, compress=False)
        items = manager.list_checkpoints(sort_by="generation")
        assert [i["generation"] for i in items] == [5, 3, 1]

    def test_sort_by_size(self, manager):
        manager.save({}, generation=1, compress=False)
        manager.save({"payload": "x" * 5000}, generation=2, compress=False)
        items = manager.list_checkpoints(sort_by="size")
        assert items[0]["generation"] == 2

    def test_sort_by_time_is_newest_first(self, manager):
        first = manager.save({}, generation=1, compress=False)
        os.utime(first, (1_000_000, 1_000_000))
        manager.save({}, generation=2, compress=False)
        items = manager.list_checkpoints(sort_by="time")
        assert items[0]["generation"] == 2

    def test_unreadable_checkpoint_is_listed_with_placeholders(self, manager):
        (manager.checkpoint_dir / "corrupt.json").write_text("{oops", encoding="utf-8")
        (item,) = manager.list_checkpoints()
        assert item["generation"] == "?"
        assert item["timestamp"] == "?"
        assert item["metadata"] == {}


@pytest.mark.root
class TestCleanup:
    def test_keeps_only_newest_n(self, manager):
        for generation in range(5):
            path = manager.save({}, generation=generation, compress=False)
            os.utime(path, (1_000_000 + generation, 1_000_000 + generation))
        removed = manager.cleanup(keep_last=2)
        assert removed == 3
        assert [i["generation"] for i in manager.list_checkpoints()] == [4, 3]

    def test_cleanup_noop_when_under_limit(self, manager):
        manager.save({}, generation=1, compress=False)
        assert manager.cleanup(keep_last=10) == 0
        assert len(manager.list_checkpoints()) == 1

    def test_clean_old_checkpoints_removes_stale_files(self, manager):
        old = manager.save({}, generation=1, compress=False)
        manager.save({}, generation=2, compress=False)
        ancient = time.time() - 40 * 86400
        os.utime(old, (ancient, ancient))
        assert manager.clean_old_checkpoints(max_age_days=30) == 1
        assert [i["generation"] for i in manager.list_checkpoints()] == [2]

    def test_clean_old_checkpoints_keeps_fresh_files(self, manager):
        manager.save({}, generation=1, compress=False)
        assert manager.clean_old_checkpoints(max_age_days=1) == 0


@pytest.mark.root
class TestDisplay:
    """Display helpers render to the console; assert they stay exception-free."""

    def test_display_list_empty(self, manager):
        manager.display_list()

    def test_display_checkpoints_with_items(self, manager):
        manager.save({}, generation=1, compress=False)
        manager.display_checkpoints()
        manager.display_checkpoints(manager.list_checkpoints())
