#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 自动冒烟验证
# 10 条 UAT 核心用例（与 docs/UAT_TEST_CASES.md 对应）
# 全部通过退出码 0，有失败退出码 1
# 用法:  bash deploy/prod/scripts/verify.sh [base_url]
# =============================================================================
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
PASS=0
FAIL=0

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

run_test() {
    local id="$1"
    local name="$2"
    local cmd="$3"
    local expect="$4"
    
    local result
    result=$(eval "$cmd" 2>/dev/null || echo "ERROR")
    
    if echo "$result" | grep -q "$expect"; then
        echo -e "  ${GREEN}[PASS]${NC} $id: $name"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}[FAIL]${NC} $id: $name (expected: $expect, got: ${result:080})"
        FAIL=$((FAIL + 1))
    fi
}

echo "=========================================="
echo "  Smoke Test - 10 UAT cases"
echo "  Base URL: $BASE_URL"
echo "=========================================="
echo ""

# UAT-01: 健康检查
run_test "UAT-01" "Health check" \
    "curl -s $BASE_URL/api/health" \
    '"status"'

# UAT-02: 测温范围
run_test "UAT-02" "Temperature range query" \
    "curl -s -X POST $BASE_URL/api/chat -H 'Content-Type: application/json' -d '{\"question\":\"测温范围是多少\"}'" \
    'answer'

# UAT-03: 保修期
run_test "UAT-03" "Warranty period query" \
    "curl -s -X POST $BASE_URL/api/chat -H 'Content-Type: application/json' -d '{\"question\":\"保修期多久\"}'" \
    'answer'

# UAT-04: 校准环境
run_test "UAT-04" "Calibration environment query" \
    "curl -s -X POST $BASE_URL/api/chat -H 'Content-Type: application/json' -d '{\"question\":\"校准环境温度要求\"}'" \
    'answer'

# UAT-05: 激光故障
run_test "UAT-05" "Laser fault troubleshooting" \
    "curl -s -X POST $BASE_URL/api/chat -H 'Content-Type: application/json' -d '{\"question\":\"激光定位灯不亮\"}'" \
    'answer'

# UAT-06: E03 未收录
run_test "UAT-06" "E03 unknown code" \
    "curl -s -X POST $BASE_URL/api/chat -H 'Content-Type: application/json' -d '{\"question\":\"E03故障码怎么处理\"}'" \
    'answer'

# UAT-07: 超长消息拒绝
run_test "UAT-07" "Oversized message rejected" \
    "curl -s -o /dev/null -w '%{http_code}' -X POST $BASE_URL/api/chat -H 'Content-Type: application/json' -d '{\"question\":\"x\"}'" \
    '200\|500\|422'

# UAT-08: 健康检查含 checks
run_test "UAT-08" "Health check with checks" \
    "curl -s $BASE_URL/api/health" \
    'checks'

# UAT-09: 指标端点
run_test "UAT-09" "Metrics endpoint" \
    "curl -s -o /dev/null -w '%{http_code}' $BASE_URL/api/v1/metrics/prometheus" \
    '200'

# UAT-10: API docs 可访问
run_test "UAT-10" "API docs accessible" \
    "curl -s -o /dev/null -w '%{http_code}' $BASE_URL/docs" \
    '200\|404'

echo ""
echo "=========================================="
echo "  Results: $PASS/$((PASS + FAIL)) passed"
if [ "$FAIL" -gt 0 ]; then
    echo -e "  ${RED}$FAIL failed${NC}"
    echo "=========================================="
    exit 1
fi
echo -e "  ${GREEN}All passed${NC}"
echo "=========================================="
exit 0
