# Chatwoot 部署指南

## 方式一：Docker Compose 一键部署（推荐）

项目根目录已有 `docker-compose.yml`，包含完整链路：

```bash
# 1. 安装 Docker Desktop（Windows）或 Docker Engine（Linux）
# 下载地址：https://www.docker.com/products/docker-desktop/

# 2. 进入项目目录
cd C:\Users\hai\projects\enterprise-agent

# 3. 生成随机密钥（必须！）
openssl rand -hex 32 > .env.secret
SECRET_KEY=$(cat .env.secret)

# 4. 启动所有服务
docker compose up -d

# 5. 等待初始化完成（约 1-2 分钟）
docker compose logs -f chatwoot

# 6. 访问 Chatwoot
# 网页：http://localhost:3000
# 默认账号：admin@example.com / Password1!
```

## 方式二：手动安装 Chatwoot

### Linux / WSL

```bash
# 1. 安装依赖
sudo apt update
sudo apt install -y postgresql redis-server

# 2. 创建数据库
sudo -u postgres psql -c "CREATE DATABASE chatwoot;"
sudo -u postgres psql -c "CREATE USER chatwoot WITH PASSWORD 'chatwoot';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE chatwoot TO chatwoot;"

# 3. 克隆 Chatwoot
git clone https://github.com/chatwoot/chatwoot.git
cd chatwoot

# 4. 安装 Ruby
rbenv install 3.2.2
rbenv global 3.2.2

# 5. 安装 Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 6. 配置环境变量
cp .env.sample .env
# 编辑 .env，设置：
#   SECRET_KEY_BASE=<openssl rand -hex 32>
#   DATABASE_HOST=localhost
#   DATABASE_PORT=5432
#   DATABASE_USERNAME=chatwoot
#   DATABASE_PASSWORD=chatwoot
#   DATABASE_NAME=chatwoot
#   REDIS_URL=redis://localhost:6379

# 7. 安装并启动
bundle install
yarn install
RAILS_ENV=production bundle exec rails db:migrate
RAILS_ENV=production bin/rails assets:precompile
RAILS_ENV=production bin/rails server -p 3000
```

### Windows

Windows 不建议直接安装 Chatwoot（Rails + PostgreSQL + Redis 配置复杂）。

**推荐方案：** 用 WSL2 或 Docker Desktop 部署。

## 配置 Chatwoot 接入 AI 客服

### 1. 创建 Webhook

登录后：
- 左侧菜单 **Settings → Integrations → Webhooks**
- 点 **Add Webhook**
- **Endpoint URL**: `http://localhost:80/api/v1/chatwoot/webhook`（如果用 Nginx 代理则为 `http://你的域名/api/v1/chatwoot/webhook`）
- **Events**: 勾选 `message_created`
- **Secret Token**: 填入一个随机字符串（如 `my-chatwoot-secret-123`）
- 点 **Save**

### 2. 同步 Token 到后端

打开 `src/api/chatwoot.py`，修改第 28 行：

```python
CHATWOOT_WEBHOOK_TOKEN = "my-chatwoot-secret-123"  # 改成上面设置的 token
```

### 3. 配置 Inbox（收件箱）

- 左侧菜单 **Settings → Accounts → Your Account → Settings → Inboxes**
- 点 **Create Inbox**
- Type 选 **Website**
- 填好名称和网站 URL
- 保存后会得到一个 **Widget Script**

### 4. 嵌入 Widget 到你的网页

在 `static/index.html` 的 `<body>` 末尾添加 Chatwoot Widget Script（从步骤 3 获取）。

或者直接访问 `http://localhost:3000` 使用 Chatwoot 自带的聊天界面。

## 访问地址汇总

| 服务 | 地址 | 用途 |
|------|------|------|
| Chatwoot 管理后台 | http://localhost:3000 | 人工客服工作台 |
| 网页聊天界面 | http://localhost | 自定义前端（Nginx 托管） |
| FastAPI 文档 | http://localhost:8000/docs | API 文档 |
| APISIX Dashboard | http://localhost:9001 | 网关管理 |
| 健康检查 | http://localhost:8000/api/v1/health | 服务状态 |

## 常用命令

```bash
# 查看所有服务状态
docker compose ps

# 查看日志
docker compose logs -f chatwoot
docker compose logs -f fastapi

# 重启服务
docker compose restart chatwoot
docker compose restart fastapi

# 停止所有服务
docker compose down

# 停止并删除数据（慎用！）
docker compose down -v
```
