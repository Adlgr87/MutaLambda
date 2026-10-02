"""A checkpoint is either complete and loadable, or it fails loudly.

`--resume` is the one feature where a silent failure costs hours of compute:
the run restarts from whatever state was recovered and reports success. Three
properties are defended here.

1. **Atomicity.** The save used `open(path, "w")` straight onto the canonical
   name, so an interruption (Ctrl-C, OOM, a full disk) left a truncated file
   exactly where `--resume` looks. Writes now go to a temp sibling and are
   renamed, so a reader sees the old file or the complete new one.
2. **Loud failure.** A corrupt checkpoint raises `CheckpointCorruptError`
   naming the newest intact alternative, rather than being half-parsed.
3. **Retention.** Older good checkpoints survive, so one bad save is not fatal.

Plus schema versioning: the `version` field was written on every save and
never read back, so a checkpoint from any other schema loaded silently and
quietly dropped whatever fields the reader did not recognise.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from mutalambda_config.checkpoint_manager import (
    DEFAULT_CHECKPOINT_KEEP,
    CheckpointCorruptError,
    CheckpointSaveError,
    _atomic_write,
    load_checkpoint,
    prune_checkpoints,
    save_full_checkpoint,
)
from muta_lambda import EvolveConfig, MutaLambdaAgent


@pytest.fixture
def run_dir():
    d = Path(tempfile.mkdtemp(prefix="ckpt_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def agent_and_config(run_dir):
    cfg = EvolveConfig(
        num_islands=2,
        generations=1,
        population_size=2,
        top_k=2,
        checkpoint_dir=str(run_dir),
        archive_solutions=False,
        prompt_evolution=False,
        workflow_enabled=False,
    )
    agent = MutaLambdaAgent(
        config=cfg,
        llm_fn=lambda p: "def f():\n    return 1\n",
        test_cases=[{"function": "f", "args": [], "expected": 1}],
    )
    return agent, cfg


def _save(agent, cfg, gen):
    return Path(save_full_checkpoint(agent, generation=gen, config=cfg, raw_config={"g": gen}))


# ── 1. Atomic writes ───────────────────────────────────────────────────────


def test_atomic_write_leaves_no_temp_file(run_dir):
    target = run_dir / "x.bin"
    _atomic_write(target, b"payload")
    assert target.read_bytes() == b"payload"
    assert list(run_dir.glob("*.tmp")) == [], "temp file was left behind"


def test_atomic_write_preserves_the_old_file_when_it_fails(run_dir, monkeypatch):
    """A failed write must not destroy what was already there."""
    target = run_dir / "x.bin"
    _atomic_write(target, b"original")

    def boom(*_a, **_k):
        raise OSError("No space left on device")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(CheckpointSaveError, match="No space left on device"):
        _atomic_write(target, b"replacement")

    assert target.read_bytes() == b"original", "a failed save clobbered the good file"
    assert list(run_dir.glob("*.tmp")) == [], "temp file leaked after a failed write"


def test_save_never_leaves_a_partial_file_at_the_canonical_path(agent_and_config, run_dir):
    """Regression: the old code wrote directly to checkpoint.json."""
    agent, cfg = agent_and_config
    chk = _save(agent, cfg, 1)
    assert (chk / "checkpoint.json").exists()
    assert list(chk.glob("*.tmp")) == []
    # And the file that exists is complete.
    assert load_checkpoint(chk / "checkpoint.json").generation == 1


def test_interrupted_save_does_not_replace_a_good_checkpoint(
    agent_and_config, run_dir, monkeypatch
):
    agent, cfg = agent_and_config
    _save(agent, cfg, 1)
    good = run_dir / "chk_gen0001" / "checkpoint.json"
    original = good.read_bytes()

    # Fail at the flush-to-disk step, i.e. after bytes have been written to the
    # temp file but before the rename. This is the window that used to leave a
    # truncated file at the canonical name.
    def die_before_rename(fd):
        raise OSError("No space left on device")

    monkeypatch.setattr(os, "fsync", die_before_rename)
    with pytest.raises((CheckpointSaveError, OSError)):
        save_full_checkpoint(agent, generation=1, config=cfg, raw_config={"g": 1})
    monkeypatch.undo()

    assert good.read_bytes() == original, "an interrupted save corrupted the good checkpoint"
    assert load_checkpoint(good).generation == 1
    assert list((run_dir / "chk_gen0001").glob("*.tmp")) == [], "temp file leaked"


# ── 2. Corruption is loud ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(lambda raw: raw[: len(raw) // 2], id="truncated"),
        pytest.param(lambda raw: b"", id="empty"),
        pytest.param(lambda raw: b"\x00\x01\x02not json", id="garbage"),
        pytest.param(lambda raw: b'{"not_a_checkpoint": true}', id="wrong-shape"),
    ],
)
def test_corrupt_checkpoint_raises_instead_of_returning_partial_state(
    agent_and_config, run_dir, mangle
):
    agent, cfg = agent_and_config
    _save(agent, cfg, 1)
    target = run_dir / "chk_gen0001" / "checkpoint.json"
    target.write_bytes(mangle(target.read_bytes()))

    with pytest.raises(CheckpointCorruptError) as excinfo:
        load_checkpoint(target)
    assert "corrupt" in str(excinfo.value).lower()
    assert "NOT repaired" in str(excinfo.value)


def test_corrupt_checkpoint_points_at_the_previous_good_one(agent_and_config, run_dir):
    """The operator should not have to go hunting for a usable checkpoint."""
    agent, cfg = agent_and_config
    _save(agent, cfg, 1)
    _save(agent, cfg, 2)
    bad = run_dir / "chk_gen0002" / "checkpoint.json"
    bad.write_text("{ truncated")

    with pytest.raises(CheckpointCorruptError, match=r"chk_gen0001"):
        load_checkpoint(bad)


def test_corrupt_msgpack_also_fails_loudly(agent_and_config, run_dir):
    pytest.importorskip("msgpack")
    agent, cfg = agent_and_config
    cfg.checkpoint_format = "msgpack"
    _save(agent, cfg, 1)
    target = run_dir / "chk_gen0001" / "checkpoint.msgpack"
    target.write_bytes(b"not-valid-zlib")

    with pytest.raises(CheckpointCorruptError):
        load_checkpoint(target)


def test_a_healthy_checkpoint_still_round_trips_in_both_formats(agent_and_config, run_dir):
    """The inverse guard: none of the hardening broke the happy path."""
    agent, cfg = agent_and_config
    for fmt in ("json", "msgpack"):
        if fmt == "msgpack":
            pytest.importorskip("msgpack")
        cfg.checkpoint_format = fmt
        chk = _save(agent, cfg, 3)
        restored = load_checkpoint(chk)
        assert restored.generation == 3
        from mutalambda_config.checkpoint_manager import CheckpointData

        for fieldname in CheckpointData.__dataclass_fields__:
            assert hasattr(restored, fieldname), f"{fmt} lost field {fieldname}"


# ── 3. Schema version is actually checked ──────────────────────────────────


def test_incompatible_schema_version_is_rejected(agent_and_config, run_dir):
    """Regression: 'version' was written on every save and never read back."""
    agent, cfg = agent_and_config
    _save(agent, cfg, 1)
    target = run_dir / "chk_gen0001" / "checkpoint.json"
    data = json.loads(target.read_text())
    data["version"] = "99.0.0"
    target.write_text(json.dumps(data))

    with pytest.raises(CheckpointCorruptError) as excinfo:
        load_checkpoint(target)
    assert "99.0.0" in str(excinfo.value)
    assert "migrate-checkpoints" in str(excinfo.value), "error should name the migration command"


def test_version_is_written_from_the_canonical_constant(agent_and_config, run_dir):
    from mutalambda_core.constants import CORE_CHECKPOINT_FORMAT, CORE_CHECKPOINT_VERSION

    agent, cfg = agent_and_config
    _save(agent, cfg, 1)
    data = json.loads((run_dir / "chk_gen0001" / "checkpoint.json").read_text())
    assert data["version"] == CORE_CHECKPOINT_VERSION
    assert data["format"] == CORE_CHECKPOINT_FORMAT


def test_unversioned_legacy_checkpoint_still_loads(agent_and_config, run_dir, caplog):
    """Checkpoints predating versioning must not be locked out."""
    agent, cfg = agent_and_config
    _save(agent, cfg, 1)
    target = run_dir / "chk_gen0001" / "checkpoint.json"
    data = json.loads(target.read_text())
    data.pop("version", None)
    target.write_text(json.dumps(data))

    assert load_checkpoint(target).generation == 1


# ── 4. Retention ───────────────────────────────────────────────────────────


def test_prune_keeps_the_newest_n(agent_and_config, run_dir):
    agent, cfg = agent_and_config
    for gen in range(1, 9):
        _save(agent, cfg, gen)

    remaining = sorted(d.name for d in run_dir.glob("chk_gen*"))
    assert len(remaining) == DEFAULT_CHECKPOINT_KEEP
    assert remaining[-1] == "chk_gen0008", "newest checkpoint was pruned"
    assert remaining[0] == "chk_gen0004"


def test_prune_never_counts_an_incomplete_directory_as_good(agent_and_config, run_dir):
    """A corrupt save must not be able to evict a good checkpoint."""
    agent, cfg = agent_and_config
    for gen in range(1, 4):
        _save(agent, cfg, gen)
    # A directory with no checkpoint file at all (an aborted save).
    (run_dir / "chk_gen0099").mkdir()

    prune_checkpoints(run_dir, keep=2)
    remaining = sorted(d.name for d in run_dir.glob("chk_gen*"))

    assert "chk_gen0099" in remaining, "empty dir should be ignored, not counted"
    assert "chk_gen0003" in remaining and "chk_gen0002" in remaining
    assert "chk_gen0001" not in remaining


def test_prune_disabled_when_keep_is_zero(agent_and_config, run_dir):
    agent, cfg = agent_and_config
    for gen in range(1, 4):
        _save(agent, cfg, gen)
    assert prune_checkpoints(run_dir, keep=0) == []
    assert len(list(run_dir.glob("chk_gen*"))) == 3
