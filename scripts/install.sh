#!/bin/bash
set -euo pipefail

# MutaLambda Installation Script
# Supports CPU-only and GPU-accelerated installations

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

LOG_FILE="logs/install.log"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}ERROR: $1${NC}" | tee -a "$LOG_FILE"
    exit 1
}

warn() {
    echo -e "${YELLOW}WARNING: $1${NC}" | tee -a "$LOG_FILE"
}

info() {
    echo -e "${GREEN}INFO: $1${NC}" | tee -a "$LOG_FILE"
}

# ============================================
# Dependency Check
# ============================================
check_dependencies() {
    log "Checking dependencies..."

    # Python version
    if ! command -v python3 &>/dev/null; then
        error "Python 3 is required but not installed"
    fi

    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
    MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

    if [[ "$MAJOR" -lt 3 ]] || [[ "$MAJOR" -eq 3 && "$MINOR" -lt 10 ]]; then
        error "Python 3.10+ required (found $PYTHON_VERSION)"
    fi

    info "Python $PYTHON_VERSION OK"

    # pip
    if ! command -v pip3 &>/dev/null; then
        error "pip3 is required but not installed"
    fi

    info "pip3 OK"
}

# ============================================
# GPU Detection
# ============================================
detect_gpu() {
    if ! command -v nvidia-smi &>/dev/null; then
        warn "nvidia-smi not found - GPU mode will be disabled"
        return 1
    fi

    if ! python3 -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
        warn "PyTorch CUDA not available - GPU mode will be disabled"
        return 1
    fi

    GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l)
    info "GPU detected: $GPU_COUNT device(s)"
    return 0
}

# ============================================
# Install Dependencies
# ============================================
install_dependencies() {
    local gpu_mode="$1"

    log "Installing core dependencies..."
    pip3 install -q numpy scipy plotly pytest pytest-cov ray[default]

    if [[ "$gpu_mode" == "true" ]]; then
        log "Installing GPU dependencies..."
        pip3 install -q torch --index-url https://download.pytorch.org/whl/cu121
    fi

    log "Installing project in development mode..."
    pip3 install -q -e ".[dev]"
}

# ============================================
# CI Configuration
# ============================================
configure_ci() {
    log "Configuring CI/CD..."

    if [[ -d ".github/workflows" ]]; then
        info "GitHub Actions workflows already present"
    else
        warn "No .github/workflows directory found"
    fi
}

# ============================================
# Validate Installation
# ============================================
validate_installation() {
    log "Validating installation..."

    # Test imports
    python3 -c "from muta_lambda import __version__; print(f'MutaLambda v$__version__ OK')" || \
        error "Core import failed"

    # Test tests
    pytest tests/ -q --tb=no 2>/dev/null || warn "Some tests failed"

    # Test CLI
    mutalambda --version 2>/dev/null || warn "CLI not in PATH"

    info "Installation validated!"
}

# ============================================
# Main
# ============================================
main() {
    local gpu_mode="${1:-false}"

    log "=========================================="
    log "MutaLambda Installation"
    log "=========================================="

    check_dependencies
    detect_gpu && gpu_mode="true"

    install_dependencies "$gpu_mode"
    configure_ci
    validate_installation

    log ""
    log "=========================================="
    log "Installation complete!"
    log "=========================================="
    log ""
    log "Next steps:"
    log "  1. Configure: cp config.example.yaml config.yaml"
    log "  2. Initialize: mutalambda init --name my_project"
    log "  3. Run: mutalambda run --config config.yaml"
    log ""
    log "GPU mode: $gpu_mode"
    log "Log file: $LOG_FILE"
}

main "$@"
