# UAST Limitations

This document describes what is **NOT** supported in the Universal AST (UAST) layer.

## Per-Language Limitations

### Python

| Construct | Status | Workaround |
|-----------|--------|------------|
| Decorators with arguments | Opaque | Not mutated |
| Metaclasses | Opaque | Not mutated |
| Async/await | Not implemented | Future enhancement |
| Complex comprehensions | Partial | Simple list/dict comprehensions only |

### Rust

| Construct | Status | Workaround |
|-----------|--------|------------|
| Macros (`println!`, `vec!`, etc.) | Opaque | Preserved as-is |
| `unsafe` blocks | Opaque | Not mutated, security warning |
| Closures | Opaque | Not mutated |
| Generics | Opaque | Not mutated |
| Traits | Opaque | Not mutated |
| Async/await | Opaque | Not mutated |
| Lifetimes | Opaque | Not mutated |

### C++

| Construct | Status | Workaround |
|-----------|--------|------------|
| Templates | Opaque | Not mutated |
| Preprocessor directives (`#include`, `#define`) | Opaque | Preserved as-is |
| Lambdas | Opaque | Not mutated |
| STL containers (beyond simple types) | Partial | Basic support |
| Operator overloading | Opaque | Not mutated |
| Multiple inheritance | Opaque | Not mutated |

## Cross-Language Limitations

| Domain | Status |
|--------|--------|
| CUDA kernels | Not supported |
| GPU code | Not supported |
| Video games/simulations | Opaque |
| Physical simulations | Opaque |

## Known Workarounds

1. **Macro preservation**: Macros in Rust/C++ are captured as Opaque nodes and re-emitted verbatim
2. **Simple vs Complex**: Classes/structs without inheritance/templates are processed; complex ones become Opaque
3. **Fallback behavior**: When a language construct cannot be parsed, it becomes Opaque rather than failing