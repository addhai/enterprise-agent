#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 一键启动全部服务
# 用法:  bash deploy/p2/scripts/start.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/deploy/p2/docker-compose.yml"
ENV_FILE="$PROJECT_ROOT/deploy/p2/.env.p2"

echo "=========================================="
echo "  Enterprise Agent - Starting Services"
echo "=========================================="

# 检查 .env.p2
if [ ! -f "$ENV_FILE" ]; then
    echo "[WARN] .env.p2 not found, copying from .env.p2.example"
    cp "$PROJECT_ROOT/deploy/p2/.env.p2.example" "$ENV_FILE"
    echo "[INFO] Please edit $ENV_FILE and fill in your API keys."
fi

cd "$PROJECT_ROOT"

# 启动数据层（先启动，等健康检查通过后再启动应用）
echo "[1/3] Starting PostgreSQL and Redis..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d postgres redis

# 等待数据层健康
echo "[2/3] Waiting for data services to be healthy..."
for i in $(seq 1 30); do
    pg_ok=$(docker compose -f "$COMPOSE_FILE" ps postgres --format json 2>/dev/null | grep -c "healthy" || true)
    rd_ok=$(docker compose -f "$COMPOSE_FILE" ps redis --format json 2>/dev/null | grep -c "healthy" || true)
    if [ "$pg_ok" -ge 1 ] && [ "$rd_ok" -ge 1 ]; then
        echo "      Data services healthy."
        break
    fi
    sleep 2
done

# 启动应用
echo "[3/3] Starting application..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d app

# 等待应用健康
echo "Waiting for app to be healthy..."
for i in $(seq 1 40); do
    app_ok=$(docker compose -f "$COMPOSE_FILE" ps app --format json 2>/dev/null | grep -c "healthy" || true)
    if [ "$app_ok" -ge 1 ]; then
        echo ""
        echo "=========================================="
        echo "  All services are UP!"
        echo "=========================================="
        echo "  App:       http://localhost:8000"
        echo "  Health:    http://localhost:8000/api/v1/health"
        echo "  API docs:  http://localhost:8000/docs"
        echo ""
        echo "  Logs:      docker compose -f $COMPOSE_FILE logs -f app"
        echo "  Stop:      bash deploy/p2/scripts/stop.sh"
        echo "=========================================="
        exit 0
    fi
    sleep 3
done

echo ""
echo "[FAIL] App did not become healthy within 120s."
echo "       Check logs: docker compose -f $COMPOSE_FILE logs app"
exit 1
