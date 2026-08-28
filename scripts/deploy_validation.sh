#!/bin/bash
set -euo pipefail

# Deployment Validation Script
# Validates MutaLambda deployment configuration

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check() {
    local desc="$1"
    local cmd="$2"

    if eval "$cmd" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $desc"
        ((PASS++))
    else
        echo -e "  ${RED}✗${NC} $desc"
        ((FAIL++))
    fi
}

warn_check() {
    local desc="$1"
    local cmd="$2"

    if eval "$cmd" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $desc"
        ((PASS++))
    else
        echo -e "  ${YELLOW}⚠${NC} $desc"
        ((WARN++))
    fi
}

echo "=========================================="
echo "MutaLambda Deployment Validation"
echo "=========================================="
echo ""

echo "1. Core Components"
check "Python 3.10+" "python3 --version | grep -E '3\.(1[0-9]|[2-9][0-9])'"
check "pip3 installed" "command -v pip3"
check "muta_lambda installed" "python3 -c 'import muta_lambda'"
check "Tests runnable" "pytest --version"

echo ""
echo "2. Optional Components"
warn_check "GPU available" "nvidia-smi"
warn_check "Ray installed" "python3 -c 'import ray'"
warn_check "PyTorch CUDA" "python3 -c 'import torch; assert torch.cuda.is_available()'"

echo ""
echo "3. Configuration"
warn_check "config.yaml exists" "test -f config.yaml"
warn_check "mutation_optimizer.yaml exists" "test -f mutation_optimizer.yaml"

echo ""
echo "4. Directories"
check "logs/ directory" "test -d logs"
check "reports/ directory" "test -d reports"
check "tests/ directory" "test -d tests"

echo ""
echo "5. Tests"
warn_check "Unit tests pass" "pytest tests/unit/ -q --tb=no"
warn_check "E2E tests pass" "pytest tests/e2e/ -q --tb=no"
warn_check "Integration tests pass" "pytest tests/integration/ -q --tb=no"

echo ""
echo "6. Coverage"
warn_check "Coverage > 85%" "pytest tests/ --cov=muta_lambda --cov-report=term-missing | grep -q '8[5-9]%\\|9[0-9]%\\|100%'"

echo ""
echo "=========================================="
echo "Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}, ${YELLOW}$WARN warnings${NC}"
echo "=========================================="

if [[ $FAIL -gt 0 ]]; then
    echo -e "${RED}Deployment validation FAILED${NC}"
    exit 1
fi

echo -e "${GREEN}Deployment validation PASSED${NC}"
exit 0
