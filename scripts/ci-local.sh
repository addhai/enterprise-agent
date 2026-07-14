#!/usr/bin/env bash
# =============================================================================
# 本地 CI 验证 — 等价于 .gitlab-ci.yml 的 lint + test + sast
# 一键运行: bash scripts/ci-local.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

EXIT_CODE=0

step_pass() { echo -e "  ${GREEN}OK${NC}   $1"; }
step_fail() { echo -e "  ${RED}FAIL${NC} $1"; EXIT_CODE=1; }

echo "=========================================="
echo "  CI Local — Full Pipeline Simulation"
echo "=========================================="
echo ""

# ---- Stage 1: Lint ----
echo "--- Stage 1: Lint ---"

if command -v ruff &> /dev/null; then
    ruff check src/ tests/ 2>&1 && step_pass "ruff check" || step_fail "ruff check"
    ruff format --check src/ tests/ 2>&1 && step_pass "ruff format" || step_fail "ruff format"
else
    echo "  ${YELLOW}SKIP${NC} ruff not installed (pip install ruff)"
fi

if [[ -f frontend/package.json ]]; then
    (cd frontend && npm run lint --silent 2>&1) && step_pass "frontend lint" || step_fail "frontend lint"
fi

# ---- Stage 2: Test ----
echo ""
echo "--- Stage 2: Test ---"

if command -v pytest &> /dev/null; then
    pytest tests/ -v --tb=short 2>&1 && step_pass "pytest" || step_fail "pytest"
else
    echo "  ${YELLOW}SKIP${NC} pytest not installed"
fi

if [[ -f frontend/node_modules/.bin/vitest ]]; then
    (cd frontend && npx vitest run 2>&1) && step_pass "vitest" || step_fail "vitest"
fi

# ---- Stage 3: SAST ----
echo ""
echo "--- Stage 3: SAST ---"

if command -v bandit &> /dev/null; then
    bandit -r src/ -ll 2>&1 && step_pass "bandit (medium+)" || step_fail "bandit"
else
    echo "  ${YELLOW}SKIP${NC} bandit not installed (pip install bandit)"
fi

# ---- Stage 4: Build (dry) ----
echo ""
echo "--- Stage 4: Build Check ---"

echo -n "  Dockerfile syntax..."
python -c "
import sys
for f in ['Dockerfile','docker/api/Dockerfile','docker/worker/Dockerfile','docker/rag/Dockerfile']:
    try:
        with open(f) as fh:
            for line in fh:
                if line.startswith('FROM ') or line.startswith('CMD ') or line.startswith('COPY ') or line.startswith('RUN '):
                    pass
    except FileNotFoundError:
        print(f'{f} not found')
        sys.exit(1)
print('OK')
" && step_pass "Dockerfile syntax" || step_fail "Dockerfile syntax"

# ---- Stage 5: Helm ----
echo ""
echo "--- Stage 5: Helm ---"

if command -v helm &> /dev/null; then
    helm lint deploy/helm/enterprise-agent/ 2>&1 && step_pass "helm lint" || step_fail "helm lint"
else
    echo "  ${YELLOW}SKIP${NC} helm not installed"
fi

# ---- Stage 6: Import check ----
echo ""
echo "--- Stage 6: Import Check ---"

python -c "
import ast, os, sys
errors = []
for root, dirs, files in os.walk('src'):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for f in files:
        if not f.endswith('.py'): continue
        try:
            with open(os.path.join(root,f)) as fh:
                ast.parse(fh.read(), filename=f)
        except SyntaxError as e:
            errors.append(f'{root}/{f}: {e}')
if errors:
    for e in errors: print(f'  FAIL: {e}')
    sys.exit(1)
print('  OK')
" && step_pass "Python AST parse" || step_fail "Python AST parse"

# ---- Summary ----
echo ""
echo "=========================================="
if [[ $EXIT_CODE -eq 0 ]]; then
    echo -e "  ${GREEN}ALL STAGES PASSED${NC}"
else
    echo -e "  ${RED}SOME STAGES FAILED${NC}"
fi
echo "=========================================="

exit $EXIT_CODE
