#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 一键停止全部服务
# 用法:  bash deploy/p2/scripts/stop.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/deploy/p2/docker-compose.yml"
ENV_FILE="$PROJECT_ROOT/deploy/p2/.env.p2"

echo "=========================================="
echo "  Enterprise Agent - Stopping Services"
echo "=========================================="

cd "$PROJECT_ROOT"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down

echo ""
echo "[OK] All services stopped."
echo "     Volumes (data) are preserved. To wipe data:"
echo "     docker compose -f $COMPOSE_FILE --env-file $ENV_FILE down -v"
