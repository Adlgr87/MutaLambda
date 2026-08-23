"""``eoh`` — Tier 3. Heuristic discovery, the AlphaEvolve-shaped comparison.

Different metric, on purpose: here nothing gets "faster". The optimizer must
invent a *better heuristic*, and the score is solution quality under a fixed
evaluation budget. That is the terrain EoH / FunSearch / AlphaEvolve occupy,
and the only honest way to say "open-weight model at 1/10 the cost gets X% of
the result" is to run the same problems with the cost meter on.

Two problems ship natively so the tier runs without any download:

* **online bin packing** — the classic EoH problem: score a bin for an
  incoming item; fewer bins is better.
* **circle packing** — pack n non-overlapping circles in the unit square,
  maximise the sum of radii. This is the AlphaEvolve headline problem.

Each task carries a ``quality_probe`` that re-validates the solution
*independently of the task code*: an optimizer that weakens the feasibility
check inside the task cannot fake a score, because the probe recomputes
overlap and capacity from scratch.
"""

from __future__ import annotations

from typing import List, Optional

from bench.spec import BenchTask, Workload
from bench.suites._common import limited

SUITE = "eoh"
TIER = "tier3"
DATASET = ""

# ── online bin packing ─────────────────────────────────────────────────────

_BINPACK = '''
def bin_score(item, bin_remaining):
    """Score a candidate bin for an incoming item. Highest score wins.

    Baseline heuristic: first fit (prefer the earliest usable bin).
    """
    if bin_remaining < item:
        return -1e18
    return -bin_remaining


def pack(items, capacity):
    """Fixed driver: the heuristic is what evolves, not the loop."""
    bins = []
    for item in items:
        best_index = -1
        best_score = -1e17
        for index, remaining in enumerate(bins):
            score = bin_score(item, remaining)
            if score > best_score and remaining >= item:
                best_score = score
                best_index = index
        if best_index < 0:
            bins.append(capacity - item)
        else:
            bins[best_index] -= item
    return bins
'''

_BINPACK_PROBE = '''
def _muta_instances():
    out = []
    for seed in (7, 13, 29):
        items = []
        state = seed
        for _ in range(220):
            state = (state * 1103515245 + 12345) % 2147483648
            items.append(1 + state % 60)
        out.append((items, 100))
    return out


def _muta_quality():
    """Bins used, averaged over three fixed instances. Lower is better.

    Feasibility is recomputed here from the returned bin states, so a heuristic
    that "wins" by overfilling bins scores infinity.
    """
    totals = []
    for items, capacity in _muta_instances():
        bins = pack(list(items), capacity)
        if any(r < -1e-9 or r > capacity for r in bins):
            return float("inf")
        packed = sum(capacity - r for r in bins)
        if abs(packed - sum(items)) > 1e-6:
            return float("inf")
        totals.append(len(bins))
    return sum(totals) / len(totals)
'''

# ── circle packing ─────────────────────────────────────────────────────────

_CIRCLES = '''
def pack_circles(n):
    """Place n non-overlapping circles in the unit square.

    Baseline: a uniform grid with the largest radius that fits. Returns a list
    of (x, y, r).
    """
    import math

    side = int(math.ceil(math.sqrt(n)))
    r = 0.5 / side
    out = []
    for i in range(n):
        row, col = divmod(i, side)
        out.append(((col + 0.5) / side, (row + 0.5) / side, r))
    return out
'''

_CIRCLES_PROBE = '''
def _muta_quality():
    """Sum of radii for n=26, or -inf if the packing is infeasible.

    Overlap and containment are recomputed here; the task code cannot vouch
    for itself.
    """
    n = 26
    circles = pack_circles(n)
    if not isinstance(circles, (list, tuple)) or len(circles) != n:
        return float("-inf")
    pts = []
    for c in circles:
        try:
            x, y, r = float(c[0]), float(c[1]), float(c[2])
        except Exception:
            return float("-inf")
        if r <= 0:
            return float("-inf")
        if x - r < -1e-9 or x + r > 1 + 1e-9 or y - r < -1e-9 or y + r > 1 + 1e-9:
            return float("-inf")
        pts.append((x, y, r))
    for i in range(n):
        for j in range(i + 1, n):
            xi, yi, ri = pts[i]
            xj, yj, rj = pts[j]
            d2 = (xi - xj) ** 2 + (yi - yj) ** 2
            if d2 < (ri + rj) ** 2 - 1e-9:
                return float("-inf")
    return sum(r for _, _, r in pts)
'''


# Feasibility is the correctness contract for these tasks: a "better" heuristic
# is supposed to return a different answer, so there is no fixed expected value
# to hold out. These predicates are recomputed from scratch inside the sandbox.

FEASIBLE_BINPACK = """
    for items, capacity in (([7, 41, 23, 55, 12], 100), ([90, 90, 20], 100),
                            ([1] * 50, 10)):
        bins = pack(list(items), capacity)
        if any((r < -1e-9 or r > capacity) for r in bins):
            return False
        if abs(sum(capacity - r for r in bins) - sum(items)) > 1e-6:
            return False
    return True
"""

FEASIBLE_CIRCLES = """
    for n in (4, 9, 26):
        circles = pack_circles(n)
        if not isinstance(circles, (list, tuple)) or len(circles) != n:
            return False
        pts = []
        for c in circles:
            x, y, r = float(c[0]), float(c[1]), float(c[2])
            if r <= 0:
                return False
            if x - r < -1e-9 or x + r > 1 + 1e-9:
                return False
            if y - r < -1e-9 or y + r > 1 + 1e-9:
                return False
            pts.append((x, y, r))
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                xi, yi, ri = pts[i]
                xj, yj, rj = pts[j]
                if (xi - xj) ** 2 + (yi - yj) ** 2 < (ri + rj) ** 2 - 1e-9:
                    return False
    return True
"""


def load_tasks(limit: Optional[int] = None) -> List[BenchTask]:
    tasks = [
        BenchTask(
            task_id="eoh/online_bin_packing",
            suite=SUITE, tier=TIER,
            source_code=_BINPACK,
            entrypoint="pack",
            workload=Workload(
                calls=[[[[1 + (i * 37) % 60 for i in range(220)], 100], {}]],
                warmups=1, samples=5, timeout_sec=120.0,
            ),
            visible_tests=[
                {"function": "pack", "args": [[], 100], "expected": [],
                 "comparison": "equal"},
            ],
            holdout_tests=[
                {"function": "pack", "args": [[100, 100], 100], "expected": [0, 0],
                 "comparison": "sequence_close"},
            ],
            invariants=["custom", "determinism"],
            metadata={
                "objective": "bins_used",
                "correctness_via": "invariants",
                "invariant_params": {
                    "custom": {"code": FEASIBLE_BINPACK},
                    "determinism": {"probes": [[[[7, 41, 23, 55, 12], 100], {}]]},
                },
                "quality_probe": _BINPACK_PROBE,
                "quality_higher_is_better": False,
                "reference_point": "EoH / FunSearch online bin packing",
                "note": "speedup is meaningless here; report quality and cost",
            },
        ),
        BenchTask(
            task_id="eoh/circle_packing",
            suite=SUITE, tier=TIER,
            source_code=_CIRCLES,
            entrypoint="pack_circles",
            workload=Workload(calls=[[[26], {}]], warmups=1, samples=5, timeout_sec=120.0),
            visible_tests=[],
            holdout_tests=[],
            invariants=["custom", "determinism"],
            metadata={
                "objective": "sum_of_radii",
                "correctness_via": "invariants",
                "invariant_params": {
                    "custom": {"code": FEASIBLE_CIRCLES},
                    "determinism": {"probes": [[[8], {}]]},
                },
                "quality_probe": _CIRCLES_PROBE,
                "quality_higher_is_better": True,
                "reference_point": "AlphaEvolve circle packing (n=26)",
                "note": "AlphaEvolve reports sum-of-radii for n=26; publish the same n "
                        "and the same feasibility tolerance or the comparison is void",
            },
        ),
    ]
    return limited(tasks, limit)
