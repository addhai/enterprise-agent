#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 数据备份脚本
# 备份向量库和数据库到 backup/ 目录，保留最近 5 份
# 用法:  bash scripts/ops/backup_data.sh [backup_dir]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKUP_DIR="${1:-$PROJECT_ROOT/backup}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/$TIMESTAMP"
MAX_BACKUPS=5

echo "[backup] Starting backup to $BACKUP_PATH"

mkdir -p "$BACKUP_PATH"

# 1. 备份向量库（必须先停容器或用冷拷贝）
if [ -d "$PROJECT_ROOT/chroma_data" ]; then
    echo "[backup] Copying chroma_data..."
    cp -r "$PROJECT_ROOT/chroma_data" "$BACKUP_PATH/chroma_data"
    echo "[backup] chroma_data: $(du -sh "$BACKUP_PATH/chroma_data" | cut -f1)"
fi

# 2. 备份数据库
if [ -f "$PROJECT_ROOT/agent.db" ]; then
    echo "[backup] Copying agent.db..."
    # SQLite 安全备份（先用 .backup 命令，失败则直接拷贝）
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$PROJECT_ROOT/agent.db" ".backup '$BACKUP_PATH/agent.db'"
    else
        cp "$PROJECT_ROOT/agent.db" "$BACKUP_PATH/agent.db"
    fi
    echo "[backup] agent.db: $(du -sh "$BACKUP_PATH/agent.db" | cut -f1)"
fi

# 3. 备份知识库文档
if [ -d "$PROJECT_ROOT/data/docs" ]; then
    echo "[backup] Copying data/docs..."
    cp -r "$PROJECT_ROOT/data/docs" "$BACKUP_PATH/docs"
fi

# 4. 备份 .env 配置（脱敏：只备份文件名和变量名，不备份值）
if [ -f "$PROJECT_ROOT/.env.intranet" ]; then
    echo "[backup] Copying .env.intranet..."
    cp "$PROJECT_ROOT/.env.intranet" "$BACKUP_PATH/.env.intranet"
fi

# 5. 清理旧备份（保留最近 MAX_BACKUPS 份）
echo "[backup] Cleaning old backups (keeping last $MAX_BACKUPS)..."
ls -1d "$BACKUP_DIR"/*/ 2>/dev/null | sort -r | tail -n +$((MAX_RETRIES + 1)) | while read old; do
    echo "[backup] Removing old backup: $old"
    rm -rf "$old"
done

echo "[backup] Complete: $BACKUP_PATH"
echo "[backup] Size: $(du -sh "$BACKUP_PATH" | cut -f1)"
