# Phase 8: Package Reorganization Plan

## Phase 8a: Prepare (this commit)
- Create new package directories: mutalambda_core, mutalambda_engines, etc.
- Create __init__.py for each
- Document migration plan

## Phase 8b: Execute Migration (next commit)
- Move 37 modules to their new packages
- Update all internal imports
- Create backward-compatible shims
- Update pyproject.toml to include new packages
- Update test imports
- Verify all 771 tests pass

## Phase 8c: Verification
- Full test suite run
- CI verification
- Documentation updates

## Risk Mitigation
- All changes will be backward-compatible via shims
- Shims will have deprecation warnings
- Tests will catch any missed imports
