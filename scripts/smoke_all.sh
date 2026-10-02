#!/usr/bin/env bash
# End-to-end smoke battery: the things a green unit-test suite does not prove.
#
# Every check here corresponds to a defect that shipped past the unit tests at
# some point: the LSP server could not complete a handshake with any real
# editor, dashboard_run.py was unimportable outside a directory with a
# checkpoints/ folder, and a corrupt checkpoint was loadable as partial state.
#
# Usage: scripts/smoke_all.sh [python-bin]      (default: .venv/bin/python)
set -uo pipefail
cd "$(dirname "$0")/.."

PY="${1:-.venv/bin/python}"
FAIL=0
ok(){ echo "  ✓ $1"; }
ko(){ echo "  ✗ $1"; FAIL=1; }

echo "[1] CLI --help on the group and every subcommand"
$PY mutalambda_cli.py --help >/dev/null 2>&1 && ok "mutalambda --help" || ko "mutalambda --help"
for c in $($PY mutalambda_cli.py --help 2>/dev/null | awk '/^Commands:/{f=1;next} f&&NF{print $1}'); do
  $PY mutalambda_cli.py "$c" --help >/dev/null 2>&1 && ok "$c --help" || ko "$c --help"
done

echo "[2] doctor"
# doctor exits 1 when the host lacks bubblewrap/docker. That is a correct
# environment verdict, not a code failure: we only require that it RUNS.
out=$($PY mutalambda_cli.py doctor 2>&1)
if echo "$out" | grep -q "core imports"; then
  ok "doctor runs ($(echo "$out" | grep -c '✓') checks pass, $(echo "$out" | grep -c '✗') env gaps)"
else
  ko "doctor"
fi

echo "[3] Streamlit apps import without side effects"
$PY -c "import dashboard" >/dev/null 2>&1 && ok "import dashboard" || ko "import dashboard"
$PY -c "import dashboard_run" >/dev/null 2>&1 && ok "import dashboard_run" || ko "import dashboard_run"

echo "[4] LSP initialize round-trip (Content-Length framing)"
$PY scripts/smoke_lsp.py >/dev/null 2>&1 && ok "LSP handshake" || ko "LSP handshake"

echo "[5] every shipped config loads, validates and converts"
for y in presets/*.yaml config.scientific.yaml config/optimization.yaml; do
  $PY -c "
from mutalambda_config.muta_config import MutaLambdaConfig
MutaLambdaConfig.from_yaml('$y').to_evolve_config()
" >/dev/null 2>&1 && ok "$y" || ko "$y"
done

echo "[6] checkpoint durability (save/load, both formats, corruption, retention)"
$PY scripts/smoke_checkpoint.py >/dev/null 2>&1 && ok "checkpoint round-trip" || ko "checkpoint round-trip"

echo "[7] BLE001 ratchet"
$PY scripts/check_ble_ratchet.py >/dev/null 2>&1 && ok "ratchet intact" || ko "ratchet violated"

echo
if [ $FAIL -eq 0 ]; then echo "SMOKE: ALL GREEN"; else echo "SMOKE: FAILURES PRESENT"; fi
exit $FAIL
