"""Tranche-4: MASSIVE adapter + operator bandit."""

from __future__ import annotations

from pathlib import Path

from massive_adapter import MassiveTargetAdapter
from operator_bandit import OperatorBandit, compute_operator_reward
from muta_ext.mutation.stepper_protocol import ASTStepper, MutationComposer

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "massive"


def test_massive_adapter_local_target_promotable():
    adapter = MassiveTargetAdapter(
        source_file=str(EX / "group_cohesion_target.py"),
        entrypoint="calculate_group_cohesion",
        tests_file=str(EX / "group_cohesion_tests.json"),
        api_policy="strict",
        timeout_sec=5.0,
    )
    src = adapter.load_source()
    assert "calculate_group_cohesion" in src
    corr = adapter.evaluate(src)
    assert corr.ok, corr.message
    # Self-equivalence
    eq = adapter.equivalence(src)
    assert eq.ok
    # Equivalent rewrite should pass
    rewrite = '''
def calculate_group_cohesion(opinions):
    vals = [float(x) for x in opinions]
    n = len(vals)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0
    total = 0.0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += abs(vals[i] - vals[j])
            pairs += 1
    mean_diff = total / pairs
    c = 1.0 - mean_diff / 2.0
    return max(0.0, min(1.0, c))
'''
    pkg = adapter.promotion_package(rewrite)
    assert pkg["promotable"] is True
    assert "--- original" in pkg["patch"] or "+++" in pkg["patch"] or pkg["patch"] == "" or "calculate_group_cohesion" in pkg["patch"]


def test_massive_adapter_rejects_api_break():
    adapter = MassiveTargetAdapter(
        source_file=str(EX / "group_cohesion_target.py"),
        entrypoint="calculate_group_cohesion",
        tests_file=str(EX / "group_cohesion_tests.json"),
    )
    bad = "def calculate_group_cohesion(opinions, extra):\n    return 0.0\n"
    eq = adapter.equivalence(bad)
    assert not eq.ok


def test_operator_bandit_prefers_rewarded_arm():
    bandit = OperatorBandit(
        operators=["ast", "llm", "crossover"],
        strategy="ucb1",
        epsilon=0.0,
        rng=__import__("random").Random(0),
    )
    # Pull all once
    for _ in range(3):
        op = bandit.select()
        bandit.update(op, 0.0)
    # Reward llm heavily
    for _ in range(20):
        bandit.update("llm", 1.0, valid=True, improved=True, gain=0.5)
        bandit.update("ast", -1.0, valid=False)
        bandit.update("crossover", 0.2, valid=True)
    picks = [bandit.select() for _ in range(30)]
    assert picks.count("llm") > picks.count("ast")


def test_compute_operator_reward_scheme():
    assert compute_operator_reward(syntax_or_security_failure=True) == -0.5
    assert compute_operator_reward(correct=False) == -1.0
    assert compute_operator_reward(correct=True, improved=False) == 0.2
    assert compute_operator_reward(correct=True, improved=True, gain=0.5) >= 1.0


def test_mutation_composer_with_bandit():
    bandit = OperatorBandit(operators=["ast"], strategy="epsilon_greedy", epsilon=0.0)
    composer = MutationComposer([ASTStepper(weight=1.0)], bandit=bandit)
    code = "def f(x):\n    return x + 1\n"
    result = composer.step(code, {})
    assert result.success
    assert result.metadata.get("operator") == "ast"
    composer.report_outcome("ast", correct=True, improved=True, gain=0.1)
    assert bandit.stats["ast"].attempts >= 1
