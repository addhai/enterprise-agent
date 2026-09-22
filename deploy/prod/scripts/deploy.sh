#!/usr/bin/env bash
# =============================================================================
# Enterprise Agent - 一键部署脚本
# 8 步部署：环境检查 -> 配置检查 -> 备份 -> 构建 -> 停旧 -> 启新 -> 健康检查 -> 输出
# 用法:  bash deploy/prod/scripts/deploy.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/deploy/prod/docker-compose.prod.yml"
ENV_FILE="$PROJECT_ROOT/deploy/prod/.env.production"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo "=========================================="
echo "  Enterprise Agent - Production Deploy"
echo "=========================================="

# ---- Step 1: 环境检查 ----
echo -e "\n[1/8] Environment check..."

command -v docker >/dev/null 2>&1 || err "docker not found"
ok "docker: $(docker --version)"

docker compose version >/dev/null 2>&1 || err "docker compose plugin not found"
ok "docker compose: available"

# 端口 8000 检查
if curl -s --connect-timeout 1 http://localhost:8000 >/dev/null 2>&1; then
    warn "Port 8000 already in use (may be old service, will restart)"
else
    ok "Port 8000: available"
fi

# GPU 检查（非必须，但警告）
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    ok "GPU: ${GPU_MEM}MiB total"
    [ "${GPU_MEM:-0}" -ge 8000 ] || warn "GPU memory < 8GB, ollama may be slow"
else
    warn "No GPU detected. CPU-only mode will be slow (LLM inference ~10x slower)"
fi

# ---- Step 2: 配置检查 ----
echo -e "\n[2/8] Config check..."

if [ ! -f "$ENV_FILE" ]; then
    warn ".env.production not found, copying from example"
    cp "$PROJECT_ROOT/deploy/prod/.env.production.example" "$ENV_FILE"
    err ".env.production created. Edit it and set JWT_SECRET and POSTGRES_PASSWORD, then re-run deploy."
fi

# 检查关键变量非默认值
JWT_SECRET=$(grep -E "^JWT_SECRET=" "$ENV_FILE" | cut -d= -f2-)
if echo "$JWT_SECRET" | grep -qi "changeme"; then
    err "JWT_SECRET is still 'changeme' - must be changed before deployment"
fi
ok "JWT_SECRET: configured (non-default)"

PG_PASS=$(grep -E "^POSTGRES_PASSWORD=" "$ENV_FILE" | cut -d= -f2-)
if echo "$PG_PASS" | grep -qi "changeme"; then
    err "POSTGRES_PASSWORD is still 'changeme' - must be changed"
fi
ok "POSTGRES_PASSWORD: configured (non-default)"

# ---- Step 3: 备份当前数据 ----
echo -e "\n[3/8] Backup current data..."
if [ -f "$PROJECT_ROOT/scripts/ops/backup_data.sh" ]; then
    bash "$PROJECT_ROOT/scripts/ops/backup_data.sh" 2>&1 | tail -3
    ok "Backup complete"
else
    warn "backup_data.sh not found, skipping backup"
fi

# ---- Step 4: 构建镜像 ----
echo -e "\n[4/8] Build image..."
cd "$PROJECT_ROOT"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build app 2>&1 | tail -5
ok "Image built: enterprise-agent:prod"

# ---- Step 5: 停止旧容器 ----
echo -e "\n[5/8] Stop old containers..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down 2>/dev/null || true
ok "Old containers stopped (volumes preserved)"

# ---- Step 6: 启动新容器 ----
echo -e "\n[6/8] Start new containers..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d 2>&1 | tail -5
ok "Containers started"

# ---- Step 7: 等待健康检查 ----
echo -e "\n[7/8] Wait for health check..."
for i in $(seq 1 20); do
    resp=$(curl -s --connect-timeout 3 http://localhost:8000/api/health 2>/dev/null || echo "")
    if [ -n "$resp" ]; then
        status=$(echo "$resp" | python -c "import sys,json; print(json.loads(sys.stdin.read()).get('status',''))" 2>/dev/null || echo "")
        if [ "$status" = "ok" ]; then
            ok "Health check: OK (attempt $i)"
            break
        elif [ "$status" = "degraded" ]; then
            warn "Health check: DEGRADED (attempt $i) - service running with limited features"
            break
        fi
    fi
    echo "  Waiting... ($i/20)"
    sleep 3
done

# ---- Step 8: 输出部署结果 ----
echo -e "\n[8/8] Deploy result..."
echo "=========================================="
echo "  Deploy Summary"
echo "=========================================="
echo "  Image:      enterprise-agent:prod"
echo "  Compose:    $COMPOSE_FILE"
echo "  Env:        $ENV_FILE"
echo ""
echo "  Containers:"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
echo ""
echo "  Health:     http://localhost:8000/api/health"
echo "  API docs:   http://localhost:8000/docs"
echo "  Verify:     bash deploy/prod/scripts/verify.sh"
echo "  Rollback:   bash deploy/prod/scripts/rollback.sh"
echo "=========================================="
