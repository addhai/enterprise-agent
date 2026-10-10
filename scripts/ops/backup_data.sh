#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 生产数据备份脚本（单机 8 容器架构）
#
# 备份范围：PostgreSQL（结构化数据）+ Chroma 向量库卷
# 保留策略：最近 MAX_BACKUPS 份，更旧的自动清理
#
# 用法:  bash scripts/ops/backup_data.sh [backup_dir]
#
# 2026-10-10 重写（P0-4）修复与生产化：
#   1. 修复致命 bug：原第 53 行 `MAX_RETRIES` 未定义，`tail -n +$((MAX_RETRIES+1))`
#      被展开成 `tail -n +1`，导致每次备份后把【所有】旧备份（含刚生成的新备份）
#      全部 rm -rf 清空。已改为正确的 `MAX_BACKUPS` 保留语义。
#   2. 生产化：原脚本针对开发环境（宿主机 chroma_data 目录 + agent.db SQLite），
#      生产是容器 + Postgres + 命名卷，改为 docker exec pg_dump + tar 卷打包。
# =============================================================================
set -euo pipefail

# Git Bash (MSYS) 会把 /tmp/xxx、/app 等参数自动转成 Windows 路径，破坏 docker
# exec 传给容器内命令的路径（实测 pg_dump 报 "could not open output file
# C:/Users/.../Temp/agent.dump"）。只豁免容器内路径前缀（/tmp、/app），
# 保留 /c/Users/... 宿主机路径的正常转换（供 docker cp 识别 Windows 路径）。
export MSYS2_ARG_CONV_EXCL='/tmp;/app'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKUP_DIR="${1:-$PROJECT_ROOT/backup}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/$TIMESTAMP"
MAX_BACKUPS=5

# 生产容器名（prod-net 拓扑，见 docker-compose.prod.yml）
APP_CONTAINER="prod-app-1"
PG_CONTAINER="prod-postgres-1"
PG_USER="postgres"
PG_DB="agent"
CHROMA_DIR="/app/chroma_data"

echo "[backup] Starting backup to $BACKUP_PATH"
mkdir -p "$BACKUP_PATH"

# ---------------------------------------------------------------------------
# 1. PostgreSQL 备份（pg_dump 自定义格式，可压缩）
#    自定义格式需用 pg_restore 恢复；pg_dump 只读，不影响在线服务。
# ---------------------------------------------------------------------------
if docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER"; then
    echo "[backup] Dumping PostgreSQL ($PG_DB)..."
    docker exec "$PG_CONTAINER" pg_dump \
        -U "$PG_USER" -d "$PG_DB" \
        --format=custom --compress=9 \
        -f /tmp/agent.dump
    docker cp "$PG_CONTAINER:/tmp/agent.dump" "$BACKUP_PATH/agent.dump"
    docker exec "$PG_CONTAINER" rm -f /tmp/agent.dump
    echo "[backup] agent.dump: $(du -sh "$BACKUP_PATH/agent.dump" | cut -f1)"
else
    echo "[backup] WARN: container $PG_CONTAINER not running, skip PostgreSQL"
fi

# ---------------------------------------------------------------------------
# 2. Chroma 向量库卷备份（在 app 容器内 tar 打包命名卷挂载点）
#    注意：备份期间若服务正在写 Chroma，快照可能不一致；生产备份建议低峰执行。
# ---------------------------------------------------------------------------
if docker ps --format '{{.Names}}' | grep -qx "$APP_CONTAINER"; then
    echo "[backup] Archiving Chroma vector store..."
    docker exec "$APP_CONTAINER" tar czf /tmp/chroma_data.tar.gz -C /app chroma_data
    docker cp "$APP_CONTAINER:/tmp/chroma_data.tar.gz" "$BACKUP_PATH/chroma_data.tar.gz"
    docker exec "$APP_CONTAINER" rm -f /tmp/chroma_data.tar.gz
    echo "[backup] chroma_data.tar.gz: $(du -sh "$BACKUP_PATH/chroma_data.tar.gz" | cut -f1)"
else
    echo "[backup] WARN: container $APP_CONTAINER not running, skip Chroma"
fi

# ---------------------------------------------------------------------------
# 3. 清理旧备份：保留最近 MAX_BACKUPS 份，删除更旧的
#    ls 按名称（时间戳前缀）倒序，最新在前；tail -n +N 跳过最新 (N-1) 份，
#    从第 N 份开始删除。时间戳 YYYYMMDD_HHMMSS 保证字典序即时间序。
# ---------------------------------------------------------------------------
echo "[backup] Cleaning old backups (keeping last $MAX_BACKUPS)..."
ls -1d "$BACKUP_DIR"/*/ 2>/dev/null | sort -r | tail -n +$((MAX_BACKUPS + 1)) | while read -r old; do
    echo "[backup] Removing old backup: $old"
    rm -rf "$old"
done

echo "[backup] Complete: $BACKUP_PATH"
echo "[backup] Size: $(du -sh "$BACKUP_PATH" | cut -f1)"
