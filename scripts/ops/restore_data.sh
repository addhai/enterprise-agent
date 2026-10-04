#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 数据恢复脚本
# 从指定备份目录恢复向量库和数据库
# 用法:  bash scripts/ops/restore_data.sh <backup_dir>
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKUP_PATH="${1:-}"

if [ -z "$BACKUP_PATH" ]; then
    echo "Usage: bash scripts/ops/restore_data.sh <backup_dir>"
    echo "Example: bash scripts/ops/restore_data.sh backup/20260912_180000"
    echo ""
    echo "Available backups:"
    ls -1d "$PROJECT_ROOT/backup"/*/ 2>/dev/null || echo "  (no backups found)"
    exit 1
fi

# 支持相对路径
if [ ! -d "$BACKUP_PATH" ]; then
    BACKUP_PATH="$PROJECT_ROOT/$BACKUP_PATH"
fi

if [ ! -d "$BACKUP_PATH" ]; then
    echo "[restore] ERROR: backup directory not found: $BACKUP_PATH"
    exit 1
fi

echo "[restore] Source: $BACKUP_PATH"
echo "[restore] Target: $PROJECT_ROOT"
echo ""
echo "WARNING: This will overwrite current data. Press Ctrl+C to abort."
read -p "Continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "[restore] Aborted."
    exit 0
fi

# 1. 恢复向量库
if [ -d "$BACKUP_PATH/chroma_data" ]; then
    echo "[restore] Restoring chroma_data..."
    rm -rf "$PROJECT_ROOT/chroma_data"
    cp -r "$BACKUP_PATH/chroma_data" "$PROJECT_ROOT/chroma_data"
    echo "[restore] chroma_data: $(du -sh "$PROJECT_ROOT/chroma_data" | cut -f1)"
fi

# 2. 恢复数据库
if [ -f "$BACKUP_PATH/agent.db" ]; then
    echo "[restore] Restoring agent.db..."
    cp "$BACKUP_PATH/agent.db" "$PROJECT_ROOT/agent.db"
    echo "[restore] agent.db: $(du -sh "$PROJECT_ROOT/agent.db" | cut -f1)"
fi

# 3. 恢复知识库文档
if [ -d "$BACKUP_PATH/docs" ]; then
    echo "[restore] Restoring data/docs..."
    rm -rf "$PROJECT_ROOT/data/docs"
    cp -r "$BACKUP_PATH/docs" "$PROJECT_ROOT/data/docs"
fi

# 4. 恢复配置
if [ -f "$BACKUP_PATH/.env.intranet" ]; then
    echo "[restore] Restoring .env.intranet..."
    cp "$BACKUP_PATH/.env.intranet" "$PROJECT_ROOT/.env.intranet"
fi

echo ""
echo "[restore] Complete. Restart the service:"
echo "  docker restart thermo-intranet"
echo "  # or: docker compose -f deploy/p2/docker-compose.yml restart app"
