# Documentation Factual Audit — DOC_AUDIT.md

**Purpose:** Inventory of factual errors / unverified (hallucinated) claims found in the
markdown documentation of the MutaLambda repository. This is an **audit only — no doc edits**
have been made. Corrections are listed under "Suggested fix" for each issue.

**Method:**
- Enumerated all `.md` files (`find . -name '*.md' -not -path './.git/*'`), excluding
  the 200+ auto-generated per-run checkpoint reports under `checkpoints/run_*/` and
  `benchmarks/checkpoints/run_*/` (these are per-run artifacts, not maintained prose).
- Grepped for the audit keywords: `MASSIVE`, `cosmological`, `cosmológica`, `simulation`,
  `universe`, `1,057×`, `1057×`, `441 tests`, `442 tests`, `443 tests`, `3.6×`,
  `25.8% simpler`, and any reference to files/tiers/scripts that don't exist.
- Cross-checked claims against ground truth (repo source, live test counts, the actual
  MASSIVE GitHub repo description, and benchmark artifacts).

**Scope (29 audited files):**
1. `README.md`
2. `README_ES.md`
3. `AGENTS.md`
4. `CLAUDE.md`
5. `CONTRIBUTING.md`
6. `EMPIRICAL_EVIDENCE.md`
7. `MULTILANGUAGE_REPORT.md`
8. `NSGA2_REFACTOR_REPORT.md`
9. `PHASE6_BENCHMARK_REPORT.md`
10. `status_report.md`
11. `docs/CLI.md`
12. `docs/FITNESS_METRICS.md`
13. `docs/METRICS.md`
14. `docs/SCIENTIFIC_OPTIMIZATION_MODE.md`
15. `docs/TEST_EXECUTION_PROTOCOL.md`
16. `docs/getting-started/first-optimization.md`
17. `legacy/README.md`
18. `lsp/extensions/neovim/README.md`
19. `lsp/extensions/vscode/README.md`
20. `muta_ext/uast/LIMITATIONS.md`
21. `PLANS/AUTO_IMPROVEMENT_PLAN.md`
22. `PLANS/FEATURES_IMPLEMENTATION_PLAN.md`
23. `PLANS/OPTIMIZATION_CHECKLIST.md`
24. `PLANS/OPTIMIZATION_WORKFLOW.md`
25. `PLANS/REMEDIATION_PROGRESS.md`
26. `PLANS/WORKFLOW_CHECKLIST.md`
27. `PLANS/WORKFLOW_CLOSEOUT.md`
28. `.agents/code-archaeologist.md`
29. `.agents/performance-analyzer.md` (`.agents/ux-optimizer.md` reviewed as part of AGENTS suite)

---

## Ground-Truth Reference Values

| Fact | Ground truth (verified) | Source |
|------|------------------------|--------|
| MASSIVE nature | Social-dynamics hybrid simulator (NOT cosmological) | GitHub `Adlgr87/MASSIVE` API: `"description": "MASSIVE is a hybrid simulator of social dynamics outcomes."` |
| Real full-suite test count | **504 passed** | `python -m pytest tests/ -q` → `504 passed, 4 warnings in 26.84s` |
| `test_hfc_deduplicates_demoted_elite_duplicate_in_factory` | **Passes** today (not flaky) | `pytest tests/test_hfc_tiers.py::test_hfc_deduplicates_demoted_elite_duplicate_in_factory` → `1 passed` |
| MASSIVE 3.6×/2.3×/1.5×/25.8% benchmark artifacts | **None exist** in repo | `find` for artifacts referencing `utility_logic`/`energy_engine_pure`/`social_architect_pure`/`intervention_optimizer` returned empty |
| `cache_stats()` return key | `estimated_time_saved_ms` | `code_hash.py:60` |
| `report_cache_stats()` return type | **str** (human-readable), NOT a dict | `code_hash.py:73` |

---

## Table of Issues

| # | File | Line (approx) | Exact quote / claim | Ground-truth check | Status | Suggested fix |
|---|------|---------------|---------------------|--------------------|--------|---------------|
| 1 | `docs/METRICS.md` | 31 | `**MASSIVE** es un framework de simulación **cosmológica** (multi-agente) sobre el que MutaLambda optimizó...` | MASSIVE GitHub description = "hybrid simulator of **social dynamics**"; it is a **social/agent-based** simulation, not cosmological. Historical wording (commit `28b8af0`) was "simulación **cosmológica**". **VERIFIED FIXED:** commit `a8b3457` already corrected all 3 occurrences — current HEAD line 31 and the module blocks (lines 37, 44) now read "simulación social (multi-agente)". No residual "cosmológica" remains (confirmed: `grep -ni "cosmol" docs/METRICS.md` returns nothing). | **No action — already corrected.** See verification note below. | No edit required; METRICS.md is factually correct on this point. |
| 2 | `README_ES.md` | 25, 34, 525, 625, 648, 653, 661 | `Integración con MASSIVE Framework — 50-263% de speedup en 4 módulos científicos` / `framework de simulación social (multi-agente) **MASSIVE**` / `MASSIVE: 35-60% más rápido runtime de simulación` / `Mejoras validadas: 5 (MASSIVE: 4 módulos...)` | MASSIVE is a social-dynamics simulator (confirmed). The **social-simulation** framing here is **accurate** (cosmological wording was corrected in `a8b3457`). HOWEVER the headline **50-263% speedup on "4 scientific modules" has no benchmark artifact**: the repo contains `examples/massive/group_cohesion_target.py` (a 5-function local stand-in for `calculate_group_cohesion`), not the four named MASSIVE modules, and no JSON/CSV/log evidence for `utility_logic`/`energy_engine_pure`/`social_architect_pure`/`intervention_optimizer` speedups exists. | **UNVERIFIED QUANTITATIVE CLAIM** — the module names and the 4-module/50-263% figure are not backed by any benchmark artifact in-repo. | Add provenance: point to the benchmark artifact path, or label the table as "planned/target" vs "measured". Remove `intervention_optimizer` if no evidence exists; verify each module against `MassiveTargetAdapter` targets. |
| 3 | `README.md` | 126–129 | Validation Results table: `utility_logic | 3.6x faster | 100%` (and 2.3×, 1.5×, 25.8% simpler) | No benchmark artifacts in repo reference these MASSIVE modules (see #2). The only substantiated speedups live in `benchmarks/results/D.5_speedup_evidence.md` (e.g. `t3_page_rank 6.6×`, `t1_primes_sieve 1.57×`), none from MASSIVE. | **UNVERIFIED QUANTITATIVE CLAIM** — identical to #2 in README.md; no `raw.json`/diff exists for MASSIVE targets. | Either produce benchmark artifacts under `benchmarks/results/` for these four targets and link them, or move the table to "external target results (see MASSIVE repo)" with a citation. |
| 4 | `docs/METRICS.md` | 20 | `| Tests pasando | 147/147 (100%) |` | Real test count = **504 passed**. 147 is stale (from an older, smaller suite). | **STALE / FALSE** | Update to the CI-generated count (504) or cite the specific subset (e.g. `13/13 nsga2` + `14/14 fitness_vector` as used elsewhere). Clarify the 147 figure refers to a subset and name that subset. |
| 5 | `docs/METRICS.md` | 40, 47, 54, 61, 76-78 | `Validación: 1000 iteraciones, p-value < 0.001, Cohen's d > 0.8` (×4 modules) and `Iteraciones: 1,000 ejecuciones por módulo` | No raw evidence (logs/JSON/CSV) exists in-repo for these 4 MASSIVE modules (see #2). The D.5 evidence file documents the *protocol* (30 reps, Mann-Whitney, Holm-Bonferroni) but never lists MASSIVE modules. | **UNVERIFIED STATISTICAL CLAIM** — no data files / no `raw.json` / no CI link. | Add links to `benchmarks/results/<module>/raw.json` for each, or rephrase to "protocol: 1000 iterations, p<0.001, Cohen's d>0.8 (to be run with D.5 harness)". |
| 6 | `EMPIRICAL_EVIDENCE.md` | 478, 502, 513 | `Test suite: 441 passed, 1 deselected` (×2) and `Tests green | 441 441` | Real count = **504 passed** (no deselects; the one referenced flaky test now passes). The "441" figure is from an earlier commit and is **stale by 63 tests**. | **STALE / FALSE** | Replace `441` with the current `504` (regenerated by CI). Note: commit `a8b3457` itself states "Security: 484 tests pass" and `6923b58` states "443 tests" — the count keeps drifting without a CI badge; point to `pytest` output instead of a hardcoded number. |
| 7 | `EMPIRICAL_EVIDENCE.md` | 549 | `All 443 tests pass (including new test_factory_offspring_skip_evaluation_uses_parent_fitness)` | Real count = 504. 443 is stale. | **STALE** | Update to 504 / regenerate from CI. |
| 8 | `EMPIRICAL_EVIDENCE.md` | 578 | `442 passed, 1 deselected (pre-existing flaky test_hfc_tiers)` | Real = 504 passed, 0 deselected, AND `test_hfc_tiers.py::test_hfc_deduplicates_demoted_elite_duplicate_in_factory` **passes** today. | **STALE + FALSE "flaky"** | Remove the "flaky" qualifier; the test passes. Update 442 → 504. |
| 9 | `README.md` | 152 | `**443 tests passing** (CI-generated count; 1 deselected: pre-existing flaky test_hfc_tiers)` | Real = 504 passed, 0 deselected; the referenced test passes. | **FALSE** | Replace with `504 passed` (regenerated). Remove "pre-existing flaky" since it is not flaky in CI today. |
| 10 | `README_ES.md` | 26, 91, 147, 303, 507 | `149/149 tests` / `Tests unitarios (149 en total)` / badge `Correctitud-149/149 tests` | Real = 504. 149 is an old, unmaintained figure; the badge hardcodes it. | **STALE / FALSE** | Regenerate badge from CI; replace with 504 or with the specific suite it refers to. The badge image `badge/Correctitud-149%2F149%20tests-green` is a hallucinated URL-style label with no validation. |
| 11 | `README_ES.md` | 627 | `**Tests pasando:** 326/326 (100%) - *Actualizado con UAST + Scientific Extension*` | Real = 504. 326 is another unverified figure with no provenance. | **STALE / UNVERIFIED** | Reconcile with the canonical count; cite the specific suite if 326 refers to a subset. |
| 12 | `README_ES.md` | 650 | `**Tests pasando:** 252/252 (100%) - *Actualizado con soporte multi-lenguaje UAST*` | Real = 504. 252 conflicts with the 326 figure two lines above **and** with the repo — the file contradicts itself within the same document. | **CONTRADICTORY + STALE** | Remove one of the two self-contradictory numbers; reconcile to the canonical count. |
| 13 | `README.md` | 148 | `{'hits': 14382, 'misses': 56, 'hit_rate': 0.9961, 'time_saved_ms': 1035.5}` (example output of `report_cache_stats()`) | `cache_stats()` returns key `estimated_time_saved_ms`, **not** `time_saved_ms`; and `report_cache_stats()` returns a **str**, not a dict. The example is a hallucinated return value. | **ERROR (API mismatch)** | Update example to match real signature: `report_cache_stats()` → `'hits=... misses=... hit_rate=... estimated_time_saved_ms=... ms'` (str); or show `cache_stats()` dict with the real `estimated_time_saved_ms` key. |
| 14 | `README.md` | 1 | `# MutaLambda 2.0` | `pyproject.toml` declares `version = "4.0.0"`. The repo is not "2.0"; AGENTS.md and D.5 reference 4.0. | **VERSION MISMATCH** | Correct header to "MutaLambda 4.0" (or "4.x") to match `pyproject.toml`. |
| 15 | `docs/METRICS.md` | 4-5 | `**Versión:** 3.1.0 (CLI) / 3.2 (Core)` (dated 2026-06-29) | `pyproject.toml` version = 4.0.0 (2026-08-18). | **STALE VERSION** | Update to 4.0.0 and current date. |
| 16 | `README.md` | 61 | `pip install -r requirements.txt` (install instructions) | `requirements.txt` omits runtime-critical deps declared in `pyproject.toml` (`msgpack`, `tree-sitter` extras) and includes legacy/extras (`faiss-cpu`, `sentence-transformers`, `pdfplumber`, `pandas`, `openpyxl`, `Pillow`, `z3-solver`) not needed by core. It also diverges from `[core]`/`[uast]`/`archive` in `pyproject.toml`. | **MISLEADING INSTALL** | Recommend `pip install -e ".[core]"` (or `.[core,uast]` for multi-language), per `pyproject.toml`. |
| 17 | `docs/METRICS.md` | 143 | `✅ **147/147 tests totales** pasan` (in `_get_fitness()` validation block) | Real = 504. 147 is stale. | **STALE / FALSE** | Update to current CI count; or cite the two relevant suites (`13/13 nsga2`, `14/14 fitness_vector` = 27, not 147). |
| 18 | `docs/METRICS.md` | 461 | `✅ **Unit tests:** 100% pass rate` (Rigor header, no number) | Accurate in spirit but unsupported by a count; should cite 504. | **VAGUE** | Add the count: `504/504`. |
| 19 | `docs/METRICS.md` | 80-90 | `Interconexión MutaLambda ↔ MASSIVE` section describing "integration … optimizes real scientific code … integrated back into MASSIVE" | MASSIVE is a **separate external repo** (`https://github.com/Adlgr87/MASSIVE`) that is **not imported** into MutaLambda (per `massive_adapter.py` docstring, `CLAUDE.md`, `AGENTS.md`, `PLANS/REMEDIATION_PROGRESS.md`). The only in-repo stand-in is `examples/massive/group_cohesion_target.py` (a 5-function local sample). The section reads as if MASSIVE is a live integrated dependency. | **MISLEADING — implies deep integration** | Rephrase: "MutaLambda consumes MASSIVE as an *external* target via `MassiveTargetAdapter`, pointing at pure functions by file path; it does not import MASSIVE into core." |
| 20 | `README.md` | 3 | `...combines LLMs with genetic algorithms (NSGA-II)` and "UAST" for "cross-language mutation" | NSGA-II island model is real; UAST multi-language support is partial (Rust/C++ adapters are `tree-sitter`-gated and `use_uast=False` is default/off). The UAST claim is aspirational, not production-complete. | **OVERSTATED CAPABILITY** | Qualify: "multi-language mutation **support** (Python primary; Rust/C++ beta via optional `[uast]` extra)". |
| 21 | `README.md` | 31-32 | `3-Objective Fitness: Correctness (hard gate) + Latency P50 + Memory Peak` | `fitness_vector.py` actually has **6** dimensions: correctness, latency_p50, latency_p99, throughput, memory_peak_mb, parsimony. The README's "3-objective" summary is **inaccurate**. | **FALSE — understates dimensionality** | Correct to "multi-objective (6 dimensions)" or list the real fields; see `docs/FITNESS_METRICS.md`. |
| 22 | `README.md` | 40 | `Mutation Filters: Regex-based blocking of eval/exec/subprocess/OS calls` | PLAN `BLOQUE A` (CLAUDE.md/PLAN_MUTALAMBDA2) and commit `a8b3457` added an **AST-based** `SecurityVisitor` (`runners.py`) with `enforce_ast_scan=True` default across all layers; regex filters are legacy/secondary. The README describes the **old** regex-only model. | **STALE / OUTDATED** | Update to: "AST-based `SecurityVisitor` + legacy regex fallback (`enforce_ast_scan` enabled by default)." |
| 23 | `README.md` | 41 | `Anti-Hallucination: SymPy-based algebraic verification` | `property_testing.py` uses `z3-solver` (per `requirements.txt`), **not** SymPy, for formal verification. (SymPy is not a declared dependency.) | **FALSE CAPABILITY CLAIM** | Correct to "Z3-based formal verification (`z3-solver`)"; remove SymPy or verify dependency. |
| 24 | `docs/METRICS.md` | 98 | `Esta optimización es interna al core de MutaLambda, complementando las mejoras aplicadas a MASSIVE Framework.` | MASSIVE is external; "complementing MASSIVE Framework" implies co-shipping, which is not the case. | **MISLEADING** | Remove the "complementando MASSIVE" clause. |
| 25 | `PLANS/WORKFLOW_CLOSEOUT.md` | 46-52 | `from massive_adapter import MassiveTargetAdapter` / `examples/massive/group_cohesion_target.py` as "Target externo (p.ej. pure functions de MASSIVE)" | Accurate: the stand-in exists. **No error**, but it reinforces the external-target model — keep consistent with #19/#24. | **OK (corrective context only)** | No change needed; used to calibrate the MASSIVE claims above. |
| 26 | `docs/CLI.md` | header | `**Última actualización:** 2026-06-29` and version 3.1.0 | Repo is at 4.0.0 (Aug 2026); CLI now uses `mutalambda` / `python -m muta_ext` (per AGENTS.md), but `docs/CLI.md` documents `python cli.py run ...`. Verify the documented entrypoint exists. | **STALE ENTRYPOINT** | Verify `cli.py run` vs the real `mutalambda` entrypoint; align version/date. |
| 27 | `AGENTS.md` | 4 | `AST parse cache … — **1,057× faster** on parse-heavy hot paths` | Micro-benchmark is real (`39.85 μs/op` vs `0.0377 μs/op` ≈ 1057×), but PLAN `B1` and `EMPIRICAL_EVIDENCE.md` explicitly warn this is a **cache-hit** micro-number with ~**1.0× end-to-end** impact. Presenting it without the end-to-end context repeats the misleading framing. | **MISLEADING (micro vs end-to-end)** | Add the end-to-end caveat inline or cross-link to the B1 note in `EMPIRICAL_EVIDENCE.md`. |
| 28 | `README.md` | 137 | `AST Parse Cache | ~650-1057× on cache hit …` | Same as #27 — the line is **better** than AGENTS.md (it includes end-to-end ~1.0× note), but the `650` lower bound has no source file. Only `1,057×` is referenced in `EMPIRICAL_EVIDENCE.md`. | **UNSPECIFIED SOURCE for 650** | Source the `650×` figure or narrow to the verified `1,057×` (and keep the end-to-end caveat). |
| 29 | `docs/METRICS.md` | 17-23 | `| Optimizaciones intentadas | 11 |` and `| Mejoras validadas | 5 (MASSIVE: 4, Core: 1) |` | "11 attempted" is never reconciled with the failed-experiments list; the "5 validated" count bundles the unverified MASSIVE 4-module speedups (#2/#3) as validated. | **UNVERIFIED COUNT** | Reconcile `11 attempted` with a real list; mark MASSIVE modules as "claimed, evidence pending" rather than ✅. |
| 30 | `docs/METRICS.md` | 35-70 | `utility_logic — 3.6x más rápido`, `energy_engine_pure — 2.3x`, `social_architect_pure — 1.5x`, `intervention_optimizer — 25.8% más simple` + the aggregated "35-60% faster" table | No `raw.json`/diff artifacts; no `MassiveTargetAdapter` promotion_package evidence in `benchmarks/results/`. The `group_cohesion_target.py` stand-in is not any of these four module names. | **UNVERIFIED (see #2/#3)** | Add provenance links or re-label as external-target results awaiting in-repo evidence. |
| 31 | `EMPIRICAL_EVIDENCE.md` | 426 | `MsgPack provides ~8x speedup` | Measured figure in `EMPIRICAL_EVIDENCE.md` text is **2–3×** (and **4.0×** in `PHASE6_BENCHMARK_REPORT.md`); "**~8x**" is an unsupported exaggeration relative to its own sibling files. | **INFLATED / INCONSISTENT** | Harmonize to the measured `2–3×` (or `4.0×` at 480 individuals per `PHASE6_BENCHMARK_REPORT.md`). |
| 32 | `EMPIRICAL_EVIDENCE.md` | 203 | `hypervolume`, `IGD / epsilon indicator`, `spread / spacing of Pareto front` listed as "not implemented" | Cross-check against `fitness_vector.py`/`nsga2.py` to confirm these are truly absent (crowding distance is in `nsga2.py`). | **NEEDS VERIFICATION** | Confirm fields/methods truly missing; if present, remove the false negative. |
| 33 | `README.md` | 116-120 | Pipeline stage 1 `Discovery & Hotspots`, 2 `Test Synthesis`, 3 `Fast Mode`, 4 `Deep Evolution`, 5 `Patch & Report` | Confirm each stage maps to a real module/function vs aspirational. (`progressive_pipeline.py` exists; verify stage count/names match.) | **NEEDS VERIFICATION** | Cross-check against `progressive_pipeline.py` stage definitions; align if drift. |

---

## Summary by Severity

| Severity | Count | Examples |
|----------|-------|----------|
| **False / hallucinated (quantitative)** | 8 | MASSIVE 3.6×/2.3×/1.5×/25.8% with no artifact (#2,#3,#5,#30); test counts 147/326/252/441/442/443 vs real 504 (#4–#11,#17); SymPy vs Z3 (#23) |
| **Misleading (implied integration / capability)** | 5 | "MASSIVE integrated back" (#19,#24); "3-objective" vs 6 (#21); UAST "cross-language" aspirational (#20); "1,057× faster" micro without end-to-end caveat (#27); "~8x msgpack" vs measured 2–3×/4× (#31) |
| **Stale (version/date/test drift)** | 9 | v2.0 vs 4.0.0 (#14,#15,#26); 441/442/443 vs 504 (#6–#9,#17); install via `requirements.txt` (#16); regex-only filters (#22) |
| **API mismatch** | 1 | `report_cache_stats()` returns str/key name mismatch (#13) |
| **Needs verification** | 2 | hypervolume/IGD absence (#32); pipeline-stage names (#33) |
| **Already fixed (by `a8b3457`)** | 1 | MASSIVE "cosmológica" → "simulación social" in `docs/METRICS.md` (#1) |

## Notes on what is already correct

- The **cosmological→social** correction in `docs/METRICS.md` was completed in commit
  `a8b3457` (and mirrored in `README_ES.md` line 36). The audit confirms **no residual
  "cosmológica / modelo cosmológico MASSIVE" wording remains** in `docs/METRICS.md`
  (issue #1 is marked "already fixed"). This resolves the PLAN B3 item.
- `AGENTS.md`, `CLAUDE.md`, `massive_adapter.py`, `PLANS/REMEDIATION_PROGRESS.md`, and
  `PLANS/WORKFLOW_CHECKLIST.md` describe MASSIVE correctly as a **separate external**
  social-dynamics project not imported into core.
- `benchmarks/results/D.5_speedup_evidence.md` is the gold-standard evidence file: it
  documents the protocol (30 reps, Mann-Whitney, Holm-Bonferroni, 1000 differential
  trials) and links each headline figure to a `raw.json`/diff. The MASSIVE 4-module
  claims **do not** meet this standard and lack an equivalent evidence file — the
  only in-repo MASSIVE target is `examples/massive/group_cohesion_target.py`, which is
  a 5-function local stand-in, not the four named modules.

## Reproduction commands used

```bash
cd /home/adlg/MutaLambda
find . -name '*.md' -not -path './.git/*' -not -path './.venv/*'
python -m pytest tests/ -q                          # → 504 passed
python -m pytest tests/test_hfc_tiers.py::test_hfc_deduplicates_demoted_elite_duplicate_in_factory -q
python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('https://api.github.com/repos/Adlgr87/MASSIVE'))['description'])"
sed -n '60,80p' code_hash.py                         # cache_stats() / report_cache_stats()
sed -n '360,375p' pyproject.toml                    # version + deps
```

**Status:** Audit complete. No markdown files were edited in this pass.
