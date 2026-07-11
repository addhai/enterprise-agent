#!/bin/bash
# ============================================================================
# Enterprise Agent — 健康检查脚本
# 用法: ./healthcheck.sh
# 可加入 crontab: */5 * * * * /opt/enterprise-agent/healthcheck.sh
# ============================================================================

set -euo pipefail

APP_DIR="/opt/enterprise-agent"
LOG_FILE="$APP_DIR/logs/healthcheck.log"
FASTAPI_PORT=8000
NGINX_PORT=80
HEALTH_URL="http://127.0.0.1:${FASTAPI_PORT}/api/v1/health"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

# 检查 FastAPI 是否存活
if curl -sf --max-time 5 "$HEALTH_URL" > /dev/null 2>&1; then
    log "[OK] FastAPI is healthy"
else
    log "[FAIL] FastAPI is not responding, restarting..."
    systemctl restart enterprise-agent
    sleep 3
    if curl -sf --max-time 5 "$HEALTH_URL" > /dev/null 2>&1; then
        log "[OK] FastAPI recovered after restart"
    else
        log "[CRITICAL] FastAPI still down after restart!"
    fi
fi

# 检查 Nginx 是否存活
if pgrep -x nginx > /dev/null 2>&1; then
    log "[OK] Nginx is running"
else
    log "[FAIL] Nginx is down, restarting..."
    systemctl restart nginx
fi

# 检查 PostgreSQL 是否存活
if systemctl is-active --quiet postgresql; then
    log "[OK] PostgreSQL is running"
else
    log "[FAIL] PostgreSQL is down, restarting..."
    systemctl restart postgresql
fi

# 检查 Redis 是否存活
if systemctl is-active --quiet redis-server; then
    log "[OK] Redis is running"
else
    log "[FAIL] Redis is down, restarting..."
    systemctl restart redis-server
fi

# 磁盘空间检查
USAGE=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')
if [[ "$USAGE" -gt 90 ]]; then
    log "[WARN] Disk usage is ${USAGE}%, consider cleaning up"
fi
