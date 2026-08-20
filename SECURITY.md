# Security Model & Threat Boundaries

This document states **exactly** what MutaLambda's safety machinery does and
does not guarantee. If a claim is not on this page, do not assume it.

## TL;DR

| Scenario | Supported? |
|---|---|
| Optimizing **your own code** with an LLM backend you trust | ✅ designed for this |
| Optimizing third-party/untrusted code on a developer machine | ⚠️ acceptable risk for most teams; read below |
| Running MutaLambda as a **multi-tenant service** on untrusted input | ❌ **not** without container-level isolation (Docker/gVisor/Firecracker) |

## Defense layers (what each one actually is)

### Layer 1 — Static filters (`mutation_filters.py` + `runners.SecurityVisitor`)

Regex patterns **plus** an AST structural scan that catches the evasions the
regexes miss (`import os as _o`, `f = exec` aliasing, `getattr(__builtins__,
...)`, `chr()`-assembled strings, `pickle.loads`). Profiles: `strict` /
`balanced` / `self` (the `self` profile waives *only* introspection findings
for first-party code — every execution primitive stays blocked).

**What it is:** a cheap, fast *pre-filter* that rejects the overwhelming
majority of dangerous candidates before any execution.
**What it is NOT:** a security boundary. Static analysis of Python can always
be evaded by sufficiently creative code. We treat it as a quality gate, not a
sandbox.

### Layer 2 — Subprocess sandbox (`sandbox.py`, `runners.py`)

Candidates execute in a **separate OS process** with hard `rlimit` caps
(CPU timeout, address-space/memory limit), a minimal namespace, and no
inherited file handles.

**What it is:** strong protection against the *accidental* failure modes of
evolved code — infinite loops, memory bombs, runaway recursion — and honest
crash isolation.
**What it is NOT:** kernel-level isolation. A subprocess shares the kernel,
filesystem view, and network namespace of its parent. A *deliberately*
malicious candidate that survived Layer 1 could attempt filesystem or network
access from within the subprocess.

### Layer 3 — Your isolation (required for untrusted input)

For production use on code you do not control, run the whole evaluation loop
inside a container or microVM:

```bash
# Minimal hardened example (no network, read-only rootfs, dropped caps)
docker run --rm --network none --read-only --cap-drop ALL \
  --memory 2g --cpus 2 --pids-limit 256 \
  -v "$PWD:/work:ro" -v /tmp/mutalambda-out:/out \
  python:3.11-slim \
  bash -c "pip install -e /work && python /work/muta_lambda.py --optimize /work/target.py"
```

Recommended hardening for service deployments, in increasing order of
strength: Docker with seccomp/AppArmor profiles → gVisor (`runsc`) →
Firecracker/Kata microVMs. WASM-based execution (e.g. wasmtime + WASI) is on
the roadmap for fully untrusted multi-tenant evaluation.

## Additional guarantees

- **Nothing is applied silently.** The pipeline output is a diff + report;
  applying it is a human decision.
- **LLM output is never trusted.** Every generated candidate goes through
  Layers 1–2 plus the correctness oracle regardless of which backend
  produced it.
- **`self` profile scope.** Used only for self-evolution experiments on
  MutaLambda's own source; it never applies to user-supplied code paths.

## Reporting a vulnerability

Open a private security advisory on GitHub
(https://github.com/Adlgr87/MutaLambda/security/advisories) or contact the
author directly. Please do not open public issues for exploitable findings.
