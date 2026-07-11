#!/bin/bash
# ============================================================================
# Enterprise Agent — 一键部署脚本（单服务器，免 Docker）
# ============================================================================
# 适用环境: Ubuntu 22.04 / Debian 12
# 权限要求: sudo
# 预计耗时: 5-10 分钟
# ============================================================================

set -euo pipefail

# ---------- 颜色输出 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---------- 配置变量（可在运行前修改） ----------
APP_NAME="enterprise-agent"
APP_DIR="/opt/${APP_NAME}"
APP_USER="www-data"
PYTHON_VERSION="3.11"
DOMAIN="${DOMAIN:-}"            # 域名，留空则不配置 HTTPS
NGINX_PORT="${NGINX_PORT:-80}"
FASTAPI_PORT="${FASTAPI_PORT:-8000}"

# ---------- 前置检查 ----------
echo ""
echo "============================================"
echo "  Enterprise Agent 一键部署"
echo "============================================"
echo ""

# 必须是 root
if [[ $EUID -ne 0 ]]; then
    error "请使用 root 用户或 sudo 运行此脚本"
fi

# 仅支持 Debian/Ubuntu
if [[ ! -f /etc/os-release ]]; then
    error "仅支持 Debian/Ubuntu 系统"
fi

DISTRO=$(grep '^ID=' /etc/os-release | cut -d= -f2 | tr -d '"')
if [[ "$DISTRO" != "ubuntu" && "$DISTRO" != "debian" ]]; then
    warn "检测到非标准 Debian/Ubuntu 发行版 ($DISTRO)，可能遇到问题"
fi

# ---------- 1. 安装系统依赖 ----------
info "Step 1/9: 安装系统依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

apt-get install -y -qq \
    python3.${PYTHON_VERSION} \
    python3.${PYTHON_VERSION}-venv \
    python3.${PYTHON_VERSION}-dev \
    python3-pip \
    postgresql \
    postgresql-client \
    redis-server \
    nginx \
    git \
    curl \
    wget \
    build-essential \
    libpq-dev \
    libssl-dev \
    libffi-dev \
    zlib1g-dev \
    tesseract-ocr \
    pkg-config \
    certbot \
    python3-certbot-nginx \
    2>&1 | tail -1

ok "系统依赖安装完成"

# ---------- 2. 配置 PostgreSQL ----------
info "Step 2/9: 配置 PostgreSQL..."

# 设置 postgres 用户密码（从环境变量或生成随机密码）
PG_PASSWORD="${PG_PASSWORD:-$(openssl rand -base64 16)}"
export PG_PASSWORD

su - postgres -c "psql -c \"ALTER USER postgres PASSWORD '${PG_PASSWORD}';\"" 2>&1 | grep -v '^ALTER' || true

# 创建数据库和用户
su - postgres -c "psql -c \"CREATE DATABASE ${APP_NAME};\"" 2>/dev/null || true
su - postgres -c "psql -c \"CREATE USER ${APP_NAME} WITH PASSWORD '${PG_PASSWORD}';\"" 2>/dev/null || true
su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${APP_NAME} TO ${APP_NAME};\"" 2>/dev/null || true

# 修改 pg_hba.conf 允许本地密码认证
PG_HBA=$(find /etc/postgresql -name pg_hba.conf 2>/dev/null | head -1)
if [[ -f "$PG_HBA" ]]; then
    # 确保 local 连接用 md5/scram-sha-256
    sed -i 's/^local\s\+all\s\+all\s\+peer/local   all             all                                     scram-sha-256/' "$PG_HBA"
    su - postgres -c "pg_ctlcluster $(ls /etc/postgresql/) reload" 2>/dev/null || true
fi

ok "PostgreSQL 配置完成（密码已保存，后面会用到）"

# ---------- 3. 配置 Redis ----------
info "Step 3/9: 配置 Redis..."

# 绑定 localhost（不暴露到公网）
sed -i 's/^bind 127.0.0.1 ::1$/bind 127.0.0.1 ::1/' /etc/redis/redis.conf 2>/dev/null || true
# 关闭保护模式（本地访问）
sed -i 's/^protected-mode yes$/protected-mode no/' /etc/redis/redis.conf 2>/dev/null || true

systemctl enable redis-server
systemctl restart redis-server
ok "Redis 配置完成"

# ---------- 4. 创建应用用户和目录 ----------
info "Step 4/9: 创建应用目录和用户..."

if ! id -u "$APP_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR"
mkdir -p "$APP_DIR/data"
mkdir -p "$APP_DIR/static"
mkdir -p "$APP_DIR/logs"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
ok "应用目录: $APP_DIR"

# ---------- 5. 部署应用代码 ----------
info "Step 5/9: 部署应用代码..."

if [[ ! -d "$APP_DIR/.git" ]]; then
    # 如果没有 git 仓库，尝试从远程拉取
    if [[ -n "$GIT_REPO" ]]; then
        info "从 Git 仓库克隆: $GIT_REPO"
        rm -rf "$APP_DIR"
        git clone "$GIT_REPO" "$APP_DIR"
    else
        warn "未提供 GIT_REPO，假设代码已存在于 $APP_DIR"
        warn "请确保代码已在 $APP_DIR 中"
    fi
else
    # 已有仓库，拉取最新代码
    cd "$APP_DIR"
    git pull || true
fi

ok "应用代码就绪"

# ---------- 6. 安装 Python 依赖 ----------
info "Step 6/9: 安装 Python 依赖..."

cd "$APP_DIR"

# 创建虚拟环境
if [[ ! -d "$APP_DIR/venv" ]]; then
    python3.${PYTHON_VERSION} -m venv "$APP_DIR/venv"
fi

# 激活并安装
source "$APP_DIR/venv/bin/activate"
pip install --upgrade pip setuptools wheel 2>&1 | tail -1
pip install -r requirements.txt 2>&1 | tail -5

# 保存 .env 中的密码到文件（供 systemd 服务读取）
if [[ -f "$APP_DIR/.env" ]]; then
    # 确保 .env 不包含敏感信息暴露
    chmod 600 "$APP_DIR/.env"
fi

ok "Python 依赖安装完成"

# ---------- 7. 配置 systemd 服务 ----------
info "Step 7/9: 配置 systemd 服务..."

# --- FastAPI 服务 ---
cat > /etc/systemd/system/${APP_NAME}.service <<SERVICE
[Unit]
Description=Enterprise Agent FastAPI Service
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python -m uvicorn src.api.server:app \
    --host 0.0.0.0 \
    --port $FASTAPI_PORT \
    --workers 2 \
    --loop uvloop \
    --http httptools
Restart=always
RestartSec=5
StandardOutput=append:$APP_DIR/logs/app.log
StandardError=append:$APP_DIR/logs/error.log

# 安全加固
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR $APP_DIR/logs $APP_DIR/data

[Install]
WantedBy=multi-user.target
SERVICE

# --- 文档入库服务（一次性） ---
cat > /etc/systemd/system/${APP_NAME}-ingest.service <<SERVICE
[Unit]
Description=Enterprise Agent Document Ingestion (run once)
After=network.target postgresql.service redis-server.service

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python scripts/ingest_docs.py
Restart=no

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable ${APP_NAME}
systemctl restart ${APP_NAME}

sleep 3  # 等服务启动

if systemctl is-active --quiet ${APP_NAME}; then
    ok "FastAPI 服务已启动 (http://localhost:${FASTAPI_PORT})"
else
    warn "FastAPI 服务启动失败，查看日志: tail -50 $APP_DIR/logs/error.log"
fi

# ---------- 8. 配置 Nginx ----------
info "Step 8/9: 配置 Nginx..."

NGINX_CONF="/etc/nginx/sites-available/${APP_NAME}"

cat > "$NGINX_CONF" <<NGINX
# 反向代理到 FastAPI
upstream fastapi_backend {
    server 127.0.0.1:${FASTAPI_PORT};
    keepalive 32;
}

server {
    listen ${NGINX_PORT};
    server_name ${DOMAIN:-_};

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # 静态文件（React SPA 打包产物）
    location / {
        root ${APP_DIR}/static;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }

    # API 反向代理
    location /api/ {
        proxy_pass http://fastapi_backend/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
    }

    # WebSocket 端点
    location /ws/ {
        proxy_pass http://fastapi_backend/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # 健康检查
    location /health {
        proxy_pass http://fastapi_backend/health;
        proxy_set_header Host \$host;
    }

    # 禁止访问隐藏文件
    location ~ /\. {
        deny all;
    }
}
NGINX

# 启用站点
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/

# 删除默认站点
rm -f /etc/nginx/sites-enabled/default

# 测试配置
nginx -t 2>&1 | tail -1 || true

systemctl enable nginx
systemctl restart nginx
ok "Nginx 配置完成"

# ---------- 9. 配置 HTTPS（可选） ----------
if [[ -n "$DOMAIN" ]]; then
    info "配置 HTTPS (域名: $DOMAIN)..."

    # 确保域名 DNS 已解析到本机 IP
    MY_IP=$(curl -s ifconfig.me)
    info "当前服务器公网 IP: $MY_IP"
    info "请确保域名 $DOMAIN 已解析到此 IP"
    read -p "DNS 已配置？(y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        warn "跳过 HTTPS 配置，Nginx 仍监听 HTTP"
    else
        certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$(grep EMAIL .env 2>/dev/null | cut -d= -f2 || echo admin@$DOMAIN)"
        ok "HTTPS 配置完成"
    fi
else
    warn "未设置 DOMAIN 环境变量，跳过 HTTPS 配置"
    warn "如需 HTTPS，请设置 DOMAIN=你的域名 后重新运行"
fi

# ========== 部署完成 ==========
echo ""
echo "============================================"
echo "  部署完成!"
echo "============================================"
echo ""
echo "  服务状态:"
echo "    FastAPI:  systemctl status ${APP_NAME}"
echo "    Nginx:    systemctl status nginx"
echo "    PostgreSQL: systemctl status postgresql"
echo "    Redis:    systemctl status redis-server"
echo ""
echo "  日志查看:"
echo "    应用日志:  tail -f $APP_DIR/logs/app.log"
echo "    错误日志:  tail -f $APP_DIR/logs/error.log"
echo ""
echo "  文档入库:"
echo "    systemctl start ${APP_NAME}-ingest"
echo ""

if [[ -n "$DOMAIN" ]]; then
    echo "  访问地址: https://${DOMAIN}"
else
    echo "  访问地址: http://服务器IP"
    echo "  管理后台: http://服务器IP/api/v1/metrics/all"
fi

echo ""
echo "  重要密码（PostgreSQL）: $PG_PASSWORD"
echo "  请妥善保存此密码!"
echo ""

# 保存密码到文件（仅 root 可读）
cat > /opt/.deploy_secrets <<SECRETS
PostgreSQL Password: $PG_PASSWORD
FastAPI Port: $FASTAPI_PORT
Domain: ${DOMAIN:-未配置}
SECRETS
chmod 600 /opt/.deploy_secrets

ok "全部完成"
