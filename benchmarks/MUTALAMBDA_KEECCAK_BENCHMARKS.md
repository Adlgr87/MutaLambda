# MutaLambda C++ Hot-Path Benchmarks

Record of the evolutionary optimisation runs driven by `benchmarks/cpp_hotpath.py`
against C++ kernels in external repos (currently **Bot_Crowdintel**).

## Methodology

| dimension | value |
|---|---|
| Harness | `benchmarks/cpp_hotpath.py` |
| Compiler variants | `g++` 13.3.0, `clang++` 22.1.8 |
| Optimisation level | `-O3 -march=native` |
| LLM backend | `--backend openai` (OpenAI-compatible AgnesAI endpoint) |
| Model | `agnes-2.5-flash` (AgnesAI) |
| Engine | NSGA-II, 3 islands, 14 generations, 50 pop/island |
| Timing | ns/op median over 10 samples, subprocess-isolated, 1 000 000 permutations |
| Correctness gate | Known-answer test (KAT): `keccak256("")` and `keccak256("abc")` bit-identical to Ethereum-canonical vectors, validated under both compilers |

## Results

| Target | Compiler | Model | Generations × Islands | Baseline (ns/op) | Optimized (ns/op) | Ratio | Speedup | KAT |
|---|---|---|---|---|---|---|---|---|
| Bot_Crowdintel `keccak_f1600` | clang++ 22.1.8 | agnes-2.5-flash | 14 × 3 | 547.8 | 416.2 | **1.3156×** | +31.6 % | ✅ (g++ + clang++) |
| Bot_Crowdintel `keccak_f1600` | g++ 13.3.0 | gemini-2.5-flash | 14 × 3 | 3318.0 | 3225.1 | 1.0373× | +3.73 % | ✅ (g++) |

Reproduced with:

```bash
MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/cpp_hotpath.py \
    --compiler clang++ --backend openai --model agnes-2.5-flash \
    --generations 14 --islands 3 --population 50 \
    --samples 10 --warmups 2 \
    --out benchmarks/results/results_cpp_keccak.json
```

Results artifacts: `benchmarks/results/results_cpp_keccak.json`.

## Optimised artefacts

- Optimized header: `MutaLambda/benchmarks/targets/keccak256_optimized.hpp`
  (committed copy of the clang×agnes winner)
- Produced at `/tmp/keccak_evolve_uib0wdu0/best_keccak_f1600.hpp`

## Hot-path mutation summary

The clang++ × agnes-2.5-flash run's winning mutation rewrites the ρ+π (rho/pi)
step of `keccak_f1600` from the canonical XKCP rotation-offset table into an
**in-place rotation chain with a `shift==0` guard**:

```cpp
for (int t = 0; t < 24; t++) {
    const int nx = y;
    const int ny = (2 * x + 3 * y) % 5;
    const uint64_t temp = A[nx + ny * 5];
    const int shift = (int)(((t + 1) * (t + 2)) / 2) & 63;
    A[nx + ny * 5] = (shift == 0)
        ? current
        : (current << shift) | (current >> (64 - shift));
    current = temp;
    x = nx;
    y = ny;
}
```

This removes the unconditional rotate idiom; lanes with rotation `0` skip the
barrel-shifter entirely, cutting branch-free rotate instructions on the hot
path. Functional equivalence is preserved (KAT verified).
