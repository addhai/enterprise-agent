# =============================================================================
# 数据备份初始化 — MinIO backup bucket + cron job
# 在 docker-compose 启动后运行:
#   bash scripts/backup-init.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== 初始化备份基础设施 ===${NC}"
echo ""

# 1. 创建本地备份目录
mkdir -p "${PROJECT_DIR}/backups/postgres"
mkdir -p "${PROJECT_DIR}/backups/minio"
mkdir -p "${PROJECT_DIR}/backups/milvus"
echo -e "${GREEN}[OK]${NC} 本地备份目录已创建"

# 2. 初始化 MinIO backup bucket
echo ""
echo -e "${YELLOW}[...]${NC} 初始化 MinIO backup bucket..."
python -c "
from src.infrastructure.minio_client import MinioClient
import sys

client = MinioClient()
try:
    client.ensure_bucket('agent-backups')
    print('  agent-backups bucket ready')
except Exception as e:
    print(f'  Failed: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1 || {
    echo -e "${YELLOW}[WARN]${NC} MinIO 不可用 (docker compose up 启动后再重试)"
}

# 3. 提示设置定时备份
echo ""
echo "=============================="
echo "  备份基础设施初始化完成!"
echo "=============================="
echo ""
echo "  手动备份:     bash scripts/backup.sh all"
echo "  设置定时备份:  bash scripts/backup.sh cron"
echo "  仅备份 PG:    bash scripts/backup.sh pg"
echo ""
