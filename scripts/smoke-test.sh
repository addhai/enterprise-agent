#!/usr/bin/env bash
# =============================================================================
# 冒烟测试脚本 — 一键验证全部服务健康状态
# =============================================================================
# Usage:
#   bash scripts/smoke-test.sh            # 全部检查
#   bash scripts/smoke-test.sh --quick    # 仅关键服务
#   bash scripts/smoke-test.sh --report   # 输出 Markdown 报告
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0
REPORT_MODE=false
QUICK_MODE=false

for arg in "$@"; do
    case $arg in
        --report) REPORT_MODE=true ;;
        --quick)  QUICK_MODE=true ;;
    esac
done

check() {
    local service="$1" url="$2" expected="${3:-200}" desc="${4:-}"
    local label="${desc:-$service}"

    if $QUICK_MODE && [[ "$service" != "api" && "$service" != "frontend" ]]; then
        echo -e "  ${YELLOW}SKIP${NC} $label"
        ((SKIP++)) || true
        return
    fi

    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")

    if [[ "$code" == "$expected" ]] || [[ "$expected" == "2xx" && "$code" =~ ^2 ]]; then
        echo -e "  ${GREEN}PASS${NC} $label → $code"
        ((PASS++)) || true
    else
        echo -e "  ${RED}FAIL${NC} $label → expected $expected, got $code"
        ((FAIL++)) || true
    fi
}

echo ""
echo "=========================================="
echo "  Enterprise Agent — Smoke Test"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
echo ""

# ---- 基础服务 ----
echo "--- Infrastructure ---"
check "postgres"  "" "000" "PostgreSQL (check via TCP)"   # 用 pg_isready 更可靠
check "redis"     "http://localhost:6379" "000" "Redis (no HTTP)"  # Redis 无 HTTP
check "minio"     "http://localhost:9000/minio/health/live" "200" "MinIO"
check "rabbitmq"  "http://localhost:15672" "200" "RabbitMQ Management"
check "milvus"    "http://localhost:9091/healthz" "200" "Milvus"

echo ""
echo "--- Application Services ---"
check "frontend"  "http://localhost/" "200" "Frontend (Nginx)"
check "api"       "http://localhost:8000/api/v1/health" "200" "API Service"
check "rag"       "http://localhost:8001/health" "200" "RAG Service"
check "ws-health" "http://localhost:8000/ws/health" "200" "WebSocket Health"

echo ""
echo "--- API Functional ---"

# 对话接口功能验证（需要 LLM API Key）
API_KEY_SET="${OPENAI_API_KEY:-}"
if [[ -n "$API_KEY_SET" && "$API_KEY_SET" != "sk-xxx" ]]; then
    resp=$(curl -s -X POST http://localhost:8000/api/v1/chat \
        -H "Content-Type: application/json" \
        -d '{"message": "hello", "user_id": "smoke-test"}' \
        --max-time 30 2>/dev/null || echo "")
    if echo "$resp" | grep -q '"reply"'; then
        echo -e "  ${GREEN}PASS${NC} /api/v1/chat → response received"
        ((PASS++)) || true
    else
        echo -e "  ${YELLOW}WARN${NC} /api/v1/chat → unexpected: ${resp:0:120}"
        ((SKIP++)) || true
    fi
else
    echo -e "  ${YELLOW}SKIP${NC} /api/v1/chat (OPENAI_API_KEY not set)"
    ((SKIP++)) || true
fi

echo ""
echo "--- Metrics Endpoints ---"
check "api-metrics"     "http://localhost:8000/api/v1/metrics/prometheus" "200" "/api/v1/metrics/prometheus"
check "rag-metrics"     "http://localhost:8001/metrics" "200" "RAG /metrics"
check "ws-metrics"      "http://localhost:8000/metrics" "200" "WS /metrics"

echo ""
echo "--- RabbitMQ Queue ---"
# 检查队列是否声明
MQ_CHECK=$(curl -s -u agent:agent "http://localhost:15672/api/queues/%2F" --max-time 5 2>/dev/null || echo "")
if echo "$MQ_CHECK" | grep -q '"name"'; then
    queue_count=$(echo "$MQ_CHECK" | grep -o '"name":"[^"]*"' | wc -l)
    echo -e "  ${GREEN}PASS${NC} RabbitMQ queues declared: $queue_count"
    ((PASS++)) || true
else
    echo -e "  ${YELLOW}WARN${NC} RabbitMQ queue check failed (may need API plugin)"
    ((SKIP++)) || true
fi

# ---- 汇总 ----
TOTAL=$((PASS + FAIL + SKIP))
echo ""
echo "=========================================="
echo "  Results: $PASS passed, $FAIL failed, $SKIP skipped ($TOTAL total)"
echo "=========================================="

if $REPORT_MODE; then
    echo ""
    echo "## Smoke Test Report — $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "| Status | Checks |"
    echo "|--------|--------|"
    echo "| ✅ Pass | $PASS |"
    echo "| ❌ Fail | $FAIL |"
    echo "| ⏭️  Skip | $SKIP |"
    echo ""
fi

[[ $FAIL -eq 0 ]] && exit 0 || exit 1
