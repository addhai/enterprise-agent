#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 探活脚本
# 循环调用 /api/health，非 ok 时退出码非零
# 用法:  bash scripts/ops/health_check.sh [url] [interval]
# =============================================================================
set -euo pipefail

URL="${1:-http://localhost:8000/api/health}"
INTERVAL="${2:-5}"
MAX_RETRIES=3

echo "[health_check] Checking $URL every ${INTERVAL}s (max $MAX_RETRIES retries)"

for i in $(seq 1 $MAX_RETRIES); do
    resp=$(curl -s -w "\n%{http_code}" --connect-timeout 3 --max-time 5 "$URL" 2>/dev/null || echo "CURL_ERROR")
    code=$(echo "$resp" | tail -1)
    body=$(echo "$resp" | head -n -1)

    if [ "$code" = "200" ]; then
        status=$(echo "$body" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
        if [ "$status" = "ok" ]; then
            echo "[health_check] OK (attempt $i/$MAX_RETRIES)"
            exit 0
        elif [ "$status" = "degraded" ]; then
            echo "[health_check] DEGRADED (attempt $i/$MAX_RETRIES)"
            exit 1
        else
            echo "[health_check] UNKNOWN status: $status"
        fi
    else
        echo "[health_check] HTTP $code (attempt $i/$MAX_RETRIES)"
    fi

    if [ $i -lt $MAX_RETRIES ]; then
        sleep "$INTERVAL"
    fi
done

echo "[health_check] FAILED after $MAX_RETRIES attempts"
exit 1
