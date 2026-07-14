"""Adaptive operator selection via multi-armed bandit (ML-M04).

Reward scheme (workflow):
  +1.0  correct and improves fitness
  +0.2  correct without improvement
  -1.0  incorrect
  -0.5  syntax / security failure
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class OperatorStats:
    attempts: int = 0
    valid: int = 0
    improved: int = 0
    total_reward: float = 0.0
    mean_gain: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "attempts": float(self.attempts),
            "valid": float(self.valid),
            "improved": float(self.improved),
            "total_reward": self.total_reward,
            "mean_reward": self.mean_reward,
            "mean_gain": self.mean_gain,
            "success_rate": self.success_rate,
        }

    @property
    def mean_reward(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.total_reward / self.attempts

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.valid / self.attempts


def compute_operator_reward(
    *,
    syntax_or_security_failure: bool = False,
    correct: bool = False,
    improved: bool = False,
    gain: float = 0.0,
) -> float:
    if syntax_or_security_failure:
        return -0.5
    if not correct:
        return -1.0
    if improved:
        return 1.0 + max(0.0, min(1.0, gain))
    return 0.2


class OperatorBandit:
    """Epsilon-greedy / UCB1 hybrid bandit over named operators."""

    def __init__(
        self,
        operators: Optional[List[str]] = None,
        *,
        epsilon: float = 0.15,
        strategy: str = "ucb1",  # ucb1 | epsilon_greedy
        rng: Optional[random.Random] = None,
    ):
        self.operators = list(operators or ["ast", "llm", "crossover", "redesign"])
        self.epsilon = float(epsilon)
        self.strategy = strategy
        self.rng = rng or random.Random()
        self.stats: Dict[str, OperatorStats] = {
            name: OperatorStats() for name in self.operators
        }
        self._total_pulls = 0

    def register(self, name: str) -> None:
        if name not in self.stats:
            self.operators.append(name)
            self.stats[name] = OperatorStats()

    def select(self) -> str:
        if not self.operators:
            raise RuntimeError("no operators registered")
        # Explore unseen first.
        for name in self.operators:
            if self.stats[name].attempts == 0:
                return name
        if self.strategy == "epsilon_greedy" or self.rng.random() < self.epsilon:
            return self.rng.choice(self.operators)
        # UCB1
        best_name = self.operators[0]
        best_score = float("-inf")
        for name in self.operators:
            s = self.stats[name]
            exploit = s.mean_reward
            explore = math.sqrt(2.0 * math.log(max(1, self._total_pulls)) / s.attempts)
            score = exploit + explore
            if score > best_score:
                best_score = score
                best_name = name
        return best_name

    def update(
        self,
        operator: str,
        reward: float,
        *,
        valid: bool = False,
        improved: bool = False,
        gain: float = 0.0,
    ) -> None:
        self.register(operator)
        s = self.stats[operator]
        s.attempts += 1
        self._total_pulls += 1
        s.total_reward += float(reward)
        if valid:
            s.valid += 1
        if improved:
            s.improved += 1
            # running mean of positive gains
            n = s.improved
            s.mean_gain = s.mean_gain + (gain - s.mean_gain) / max(1, n)

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        return {name: st.to_dict() for name, st in self.stats.items()}
