#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 一键回滚
# 回退到最近备份或上一镜像版本
# 用法:  bash deploy/prod/scripts/rollback.sh [backup_dir|image_tag]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/deploy/prod/docker-compose.prod.yml"
ENV_FILE="$PROJECT_ROOT/deploy/prod/.env.production"
TARGET="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "  Enterprise Agent - Rollback"
echo "=========================================="

if [ -z "$TARGET" ]; then
    # 无参数：自动找最近备份
    BACKUP_DIR="$PROJECT_ROOT/backup"
    if [ ! -d "$BACKUP_DIR" ]; then
        echo -e "${RED}[ERROR]${NC} No backup directory found at $BACKUP_DIR"
        echo "Usage: bash deploy/prod/scripts/rollback.sh <backup_dir|image_tag>"
        exit 1
    fi
    LATEST=$(ls -1d "$BACKUP_DIR"/*/ 2>/dev/null | sort -r | head -1)
    if [ -z "$LATEST" ]; then
        echo -e "${RED}[ERROR]${NC} No backups found in $BACKUP_DIR"
        exit 1
    fi
    TARGET="$LATEST"
    echo -e "${YELLOW}[INFO]${NC} Using latest backup: $TARGET"
fi

# 判断是备份目录还是镜像 tag
if [ -d "$TARGET" ]; then
    # 场景 3：向量库损坏，从备份恢复
    echo -e "\n[1/4] Rollback from backup: $TARGET"
    
    echo "[2/4] Stop containers..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" stop app 2>/dev/null || true
    
    echo "[3/4] Restore data..."
    bash "$PROJECT_ROOT/scripts/ops/restore_data.sh" "$TARGET"
    
    echo "[4/4] Restart containers..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d 2>&1 | tail -3
else
    # 场景 2：代码 bug，回退镜像版本
    echo -e "\n[1/4] Rollback to image: $TARGET"
    
    echo "[2/4] Stop old containers..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down 2>/dev/null || true
    
    echo "[3/4] Tag old image as current..."
    docker tag "$TARGET" enterprise-agent:prod
    
    echo "[4/4] Start with old image..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d 2>&1 | tail -3
fi

# 健康检查
echo -e "\nWaiting for health check..."
for i in $(seq 1 20); do
    resp=$(curl -s --connect-timeout 3 http://localhost:8000/api/health 2>/dev/null || echo "")
    if [ -n "$resp" ]; then
        status=$(echo "$resp" | python -c "import sys,json; print(json.loads(sys.stdin.read()).get('status',''))" 2>/dev/null || echo "")
        if [ "$status" = "ok" ] || [ "$status" = "degraded" ]; then
            echo -e "${GREEN}[OK]${NC} Health check: $status (attempt $i)"
            echo ""
            echo "=========================================="
            echo "  Rollback complete"
            echo "  Status: $status"
            echo "  Verify: bash deploy/prod/scripts/verify.sh"
            echo "=========================================="
            exit 0
        fi
    fi
    echo "  Waiting... ($i/20)"
    sleep 3
done

echo -e "${RED}[ERROR]${NC} Health check failed after rollback"
echo "Check logs: docker compose -f $COMPOSE_FILE logs app"
exit 1
