#!/usr/bin/env bash
# run_tests.sh — Protocolo de ejecución de tests por niveles/fases
#
# Uso:
#   ./run_tests.sh root              # Tests básicos del core
#   ./run_tests.sh scientific        # Tests de extensión científica
#   ./run_tests.sh uast              # Tests UAST
#   ./run_tests.sh benchmarks        # Tests de benchmark
#   ./run_tests.sh e2e               # Tests end-to-end
#   ./run_tests.sh all               # Ejecuta todos
#   ./run_tests.sh --report          # Generar reporte HTML/Markdown
#   ./run_tests.sh --coverage        # Generar cobertura
#   ./run_tests.sh root --report     # Combinar flags

set -euo pipefail

# ── Colores ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'
DIM='\033[2m'

# ── Directorio de trabajo ───────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Configuración ────────────────────────────────────────────────────────────
REPORT_DIR="./test_reports"
COVERAGE_DIR="./coverage"
HTML_REPORT="$REPORT_DIR/report.html"
MD_REPORT="$REPORT_DIR/report.md"
JSON_REPORT="$REPORT_DIR/results.json"
TIMEOUT=120
PYTEST_OPTS=()

# ── Flags de entrada ─────────────────────────────────────────────────────────
MODE=""
GENERATE_REPORT=false
GENERATE_COVERAGE=false
EXTRA_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --report)  GENERATE_REPORT=true ;;
        --coverage) GENERATE_COVERAGE=true ;;
        --timeout) TIMEOUT="${2:-120}" ;;
        -v|--verbose) EXTRA_ARGS+=("-v") ;;
        -q|--quiet) EXTRA_ARGS+=("-q") ;;
        --pdb) EXTRA_ARGS+=("--pdb") ;;
        -*) EXTRA_ARGS+=("$arg") ;;
        *) MODE="$arg" ;;
    esac
done

# ── Funciones de utilidad ────────────────────────────────────────────────────

print_header() {
    local msg="$1"
    local color="${2:-$BLUE}"
    echo ""
    echo -e "${color}${BOLD}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${color}${BOLD}  $msg${NC}"
    echo -e "${color}${BOLD}══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_phase() {
    local phase="$1"
    echo -e "${CYAN}${BOLD}▶ FASE: $phase${NC}"
}

print_result() {
    local status="$1"
    local count="$2"
    local label="$3"
    case "$status" in
        pass) echo -e "  ${GREEN}✓ ${count} ${label}${NC}" ;;
        fail) echo -e "  ${RED}✗ ${count} ${label}${NC}" ;;
        skip) echo -e "  ${YELLOW}○ ${count} ${label}${NC}" ;;
        error) echo -e "  ${MAGENTA}⚠ ${count} ${label}${NC}" ;;
    esac
}

print_summary() {
    local total="$1"
    local passed="$2"
    local failed="$3"
    local skipped="$4"
    local errors="$5"
    local duration="$6"

    echo ""
    echo -e "${BOLD}──────────────────────────────────────────────────────────────${NC}"
    echo -e "${BOLD}  RESUMEN${NC}"
    echo -e "${BOLD}──────────────────────────────────────────────────────────────${NC}"
    echo -e "  ${GREEN}Pasaron:${NC}  ${passed}${DIM}/${total}${NC}"
    if [[ "$failed" -gt 0 ]]; then
        echo -e "  ${RED}Fallaron:${NC} ${failed}"
    fi
    if [[ "$skipped" -gt 0 ]]; then
        echo -e "  ${YELLOW}Saltados:${NC} ${skipped}"
    fi
    if [[ "$errors" -gt 0 ]]; then
        echo -e "  ${MAGENTA}Errores:${NC}  ${errors}"
    fi
    echo -e "  ${DIM}Duración:${NC} ${duration}s"
    echo -e "${BOLD}──────────────────────────────────────────────────────────────${NC}"
}

# ── Configuración de pytest ──────────────────────────────────────────────────

build_pytest_cmd() {
    local cmd=("pytest")
    cmd+=("${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}")
    cmd+=("--tb=short" "--timeout=${TIMEOUT}" "--strict-markers")
    if $GENERATE_REPORT; then
        cmd+=("--junitxml=$JSON_REPORT")
        cmd+=("--html=$HTML_REPORT" "--self-contained-html")
    fi
    if $GENERATE_COVERAGE; then
        cmd+=("--cov=." "--cov-report=term" "--cov-report=html:$COVERAGE_DIR")
    fi
    echo "${cmd[@]}"
}

# ── Definiciones de fases ────────────────────────────────────────────────────

# Fase ROOT: tests básicos del core
run_root() {
    print_phase "ROOT — Tests básicos del core"
    echo -e "  ${DIM}config · fitness · HFC · NSGA-II · archive · lineage${NC}"
    pytest -m root "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" --tb=short --timeout="$TIMEOUT" \
        $(if $GENERATE_REPORT; then echo "--junitxml=$JSON_REPORT"; fi) \
        $(if $GENERATE_COVERAGE; then echo "--cov=. --cov-report=term --cov-report=html:$COVERAGE_DIR"; fi) \
        tests/test_config.py \
        tests/test_fitness_vector.py \
        tests/test_hfc_tiers.py \
        tests/test_nsga2.py \
        tests/test_solution_archive.py \
        tests/test_lineage.py \
        tests/test_convergent_boost.py
}

# Fase SCIENTIFIC: tests de extensión científica
run_scientific() {
    print_phase "SCIENTIFIC — Tests de extensión científica"
    echo -e "  ${DIM}numerical health · tipping detection · invariants · call graph${NC}"
    pytest -m scientific "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" --tb=short --timeout="$TIMEOUT" \
        $(if $GENERATE_REPORT; then echo "--junitxml=$JSON_REPORT"; fi) \
        $(if $GENERATE_COVERAGE; then echo "--cov=. --cov-report=term --cov-report=html:$COVERAGE_DIR"; fi) \
        tests/test_scientific_extension.py \
        tests/scientific/
}

# Fase UAST: tests del sistema UAST
run_uast() {
    print_phase "UAST — Tests del sistema UAST"
    echo -e "  ${DIM}core UAST · roundtrip · LLM generator · CLI · regression${NC}"
    pytest -m uast "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" --tb=short --timeout="$TIMEOUT" \
        $(if $GENERATE_REPORT; then echo "--junitxml=$JSON_REPORT"; fi) \
        $(if $GENERATE_COVERAGE; then echo "--cov=. --cov-report=term --cov-report=html:$COVERAGE_DIR"; fi) \
        tests/uast/
}

# Fase BENCHMARKS: tests de benchmark
run_benchmarks() {
    print_phase "BENCHMARKS — Tests de benchmark"
    echo -e "  ${DIM}benchmark matrix · evolution upgrade${NC}"
    pytest -m benchmarks "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" --tb=short --timeout="$TIMEOUT" \
        $(if $GENERATE_REPORT; then echo "--junitxml=$JSON_REPORT"; fi) \
        $(if $GENERATE_COVERAGE; then echo "--cov=. --cov-report=term --cov-report=html:$COVERAGE_DIR"; fi) \
        tests/benchmarks/
}

# Fase E2E: tests end-to-end
run_e2e() {
    print_phase "E2E — Tests end-to-end"
    echo -e "  ${DIM}pipeline completo · LLM stub · sandbox · migración${NC}"
    pytest -m e2e "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" --tb=short --timeout="$TIMEOUT" \
        $(if $GENERATE_REPORT; then echo "--junitxml=$JSON_REPORT"; fi) \
        $(if $GENERATE_COVERAGE; then echo "--cov=. --cov-report=term --cov-report=html:$COVERAGE_DIR"; fi) \
        tests/e2e_tests.py \
        tests/test_workflow_gates_integration.py
}

# Fase ALL: todos los tests
run_all() {
    echo ""
    run_root
    run_scientific
    run_uast
    run_benchmarks
    run_e2e
}

# ── Parseo de argumentos ─────────────────────────────────────────────────────

show_help() {
    echo -e "${BOLD}MutaLambda — Protocolo de ejecución de tests${NC}"
    echo ""
    echo "Uso: ./run_tests.sh [FASE] [OPCIONES]"
    echo ""
    echo "Fases:"
    echo "  root        Tests básicos del core (config, fitness, HFC, NSGA-II, archive, lineage)"
    echo "  scientific  Tests de extensión científica (numerical health, tipping, invariants)"
    echo "  uast        Tests del sistema UAST (core, roundtrip, LLM generator)"
    echo "  benchmarks  Tests de benchmark (benchmark matrix)"
    echo "  e2e         Tests end-to-end (pipeline, workflow gates)"
    echo "  all         Ejecuta todas las fases"
    echo ""
    echo "Opciones:"
    echo "  --report          Generar reporte HTML y JSON"
    echo "  --coverage        Generar reporte de cobertura"
    echo "  --timeout N       Timeout por prueba (default: 120s)"
    echo "  -v, --verbose     Modo verbose"
    echo "  -q, --quiet       Modo silencioso"
    echo "  --pdb             Abrir pdb en fallos"
    echo "  -h, --help        Mostrar esta ayuda"
    echo ""
    echo "Ejemplos:"
    echo "  ./run_tests.sh root"
    echo "  ./run_tests.sh all --report --coverage"
    echo "  ./run_tests.sh scientific -v"
    echo ""
}

# ── Punto de entrada ─────────────────────────────────────────────────────────

mkdir -p "$REPORT_DIR" "$COVERAGE_DIR"

if [[ -z "$MODE" ]]; then
    show_help
    exit 0
fi

if [[ "$MODE" == "-h" || "$MODE" == "--help" ]]; then
    show_help
    exit 0
fi

START_TIME=$(date +%s)

case "$MODE" in
    root)       run_root ;;
    scientific) run_scientific ;;
    uast)       run_uast ;;
    benchmarks) run_benchmarks ;;
    e2e)        run_e2e ;;
    all)        run_all ;;
    *)
        echo -e "${RED}Error: fase desconocida '$MODE'${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac

EXIT_CODE=$?
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Extraer resultados del último comando ejecutado
if [[ $EXIT_CODE -eq 0 ]]; then
    print_result "pass" "✓" "tests pasaron"
else
    print_result "fail" "✗" "tests fallaron"
fi

print_summary "?" "?" "?" "?" "?" "$DURATION"

if $GENERATE_REPORT; then
    echo ""
    echo -e "${GREEN}Reporte generado en:${NC}"
    echo -e "  ${BOLD}$HTML_REPORT${NC}"
    echo -e "  ${BOLD}$JSON_REPORT${NC}"
fi

if $GENERATE_COVERAGE; then
    echo ""
    echo -e "${GREEN}Cobertura generada en:${NC}"
    echo -e "  ${BOLD}$COVERAGE_DIR/index.html${NC}"
fi

exit $EXIT_CODE
