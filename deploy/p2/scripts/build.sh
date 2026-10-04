#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 一键构建镜像
# 用法:  bash deploy/p2/scripts/build.sh
# =============================================================================
set -euo pipefail

# 定位项目根目录（脚本可能在 deploy/p2/scripts/ 下）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/deploy/p2/docker-compose.yml"
ENV_FILE="$PROJECT_ROOT/deploy/p2/.env.p2"

echo "=========================================="
echo "  Enterprise Agent - Building Image"
echo "=========================================="

# 检查 .env.p2 是否存在
if [ ! -f "$ENV_FILE" ]; then
    echo "[WARN] .env.p2 not found, copying from .env.p2.example"
    cp "$PROJECT_ROOT/deploy/p2/.env.p2.example" "$ENV_FILE"
    echo "[INFO] Please edit $ENV_FILE and fill in your API keys."
fi

# 构建
cd "$PROJECT_ROOT"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build app

echo ""
echo "[OK] Build complete."
echo "     Image: enterprise-agent:latest"
echo "     Test:  docker run --rm -p 8000:8000 enterprise-agent:latest"
