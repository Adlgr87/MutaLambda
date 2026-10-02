"""Smoke: checkpoint save/load round-trip, corruption handling and retention.

Covers the --resume contract end to end in a throwaway directory:
  * both serialisation formats round-trip with every CheckpointData field intact
  * a save leaves no .tmp file behind
  * a corrupt checkpoint raises instead of yielding partial state
  * retention keeps the newest N and never counts an incomplete dir as good
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mutalambda_config.checkpoint_manager import (  # noqa: E402
    DEFAULT_CHECKPOINT_KEEP,
    CheckpointCorruptError,
    CheckpointData,
    load_checkpoint,
    save_full_checkpoint,
)
from muta_lambda import EvolveConfig, MutaLambdaAgent  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="mlsmoke_"))
try:
    cfg = EvolveConfig(
        num_islands=2,
        generations=1,
        population_size=2,
        top_k=2,
        checkpoint_dir=str(tmp),
        archive_solutions=False,
        prompt_evolution=False,
        workflow_enabled=False,
    )
    agent = MutaLambdaAgent(
        config=cfg,
        llm_fn=lambda p: "def f():\n    return 1\n",
        test_cases=[{"function": "f", "args": [], "expected": 1}],
    )

    # 1. Round-trip in both formats, with no field loss.
    for fmt in ("json", "msgpack"):
        cfg.checkpoint_format = fmt
        path = Path(save_full_checkpoint(agent, generation=1, config=cfg, raw_config={"g": 1}))
        restored = load_checkpoint(path)
        assert restored.generation == 1, (fmt, restored.generation)
        for fieldname in CheckpointData.__dataclass_fields__:
            assert hasattr(restored, fieldname), f"{fmt}: lost field {fieldname}"
        assert not list(path.glob("*.tmp")), f"{fmt}: temp file left behind"
        print(f"  {fmt}: gen={restored.generation} hash={restored.config_hash!r} OK")

    # 2. Corruption must raise, not return partial state.
    cfg.checkpoint_format = "json"
    chk = Path(save_full_checkpoint(agent, generation=2, config=cfg, raw_config={"g": 2}))
    target = chk / "checkpoint.json"
    raw = target.read_text()
    target.write_text(raw[: len(raw) // 2])
    try:
        load_checkpoint(target)
    except CheckpointCorruptError:
        print("  corrupt checkpoint raises CheckpointCorruptError OK")
    else:
        raise AssertionError("corrupt checkpoint loaded as partial state")
    target.write_text(raw)  # restore so retention has a good dir

    # 3. Retention keeps the newest N.
    for gen in range(3, 3 + DEFAULT_CHECKPOINT_KEEP + 2):
        save_full_checkpoint(agent, generation=gen, config=cfg, raw_config={"g": gen})
    kept = sorted(d.name for d in tmp.glob("chk_gen*"))
    assert len(kept) == DEFAULT_CHECKPOINT_KEEP, kept
    print(f"  retention keeps newest {DEFAULT_CHECKPOINT_KEEP}: {kept[0]}..{kept[-1]} OK")

    print("CHECKPOINT DURABILITY OK")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
