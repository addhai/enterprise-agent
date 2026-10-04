#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 实时日志查看
# 用 jq 格式化结构化 JSON 日志（无 jq 时降级为 tail）
# 用法:  bash scripts/ops/tail_logs.sh [container_name] [lines]
# =============================================================================
set -euo pipefail

CONTAINER="${1:-thermo-intranet}"
LINES="${2:-50}"
HAS_JQ=0

# 检查 jq 是否可用
if command -v jq >/dev/null 2>&1; then
    HAS_JQ=1
    echo "[tail_logs] jq available, formatting JSON logs"
else
    echo "[tail_logs] jq not found, using raw output"
fi

echo "[tail_logs] Tailing logs from container: $CONTAINER"
echo "[tail_logs] Last $LINES lines, then follow"
echo "---"

JQ_FILTER='[\(.level // "INFO")] \(.timestamp // "?") \(.message // "?")\(.request_id // "" | if . != "" then " req=\(.)" else "" end)\(.session_id // "" | if . != "" then " sid=\(.)" else "" end)\(.duration_ms // "" | if . != "" then " \(.)ms" else "" end)'

if [ "$HAS_JQ" = "1" ]; then
    # 有 jq：格式化 JSON 日志
    docker logs --tail "$LINES" -f "$CONTAINER" 2>&1 | while IFS= read -r line; do
        if echo "$line" | jq -e . >/dev/null 2>&1; then
            echo "$line" | jq -r "$JQ_FILTER"
        else
            echo "$line"
        fi
    done
else
    # 无 jq：直接 tail
    docker logs --tail "$LINES" -f "$CONTAINER" 2>&1
fi
