# Enterprise Agent — 智能客服系统

基于 LangGraph + ReAct 的企业级智能客服，支持 RAG 知识库检索、多轮对话、自动转人工。

## 快速启动（3 步搞定）

### 第 1 步：确认配置

打开项目文件夹里的 `.env` 文件，确认以下内容正确：

```
OPENAI_API_KEY=你的密钥
```

> 密钥填写说明：打开 [阿里百炼控制台](https://bailian.console.aliyun.com/) → API-KEY → 复制你的 Key 粘贴到这里。

### 第 2 步：一键启动

打开 **Git Bash**（在项目文件夹右键 → Git Bash Here），依次输入：

```bash
# 1. 构建后端镜像（首次需要几分钟）
docker compose build fastapi

# 2. 启动所有服务
docker compose up -d
```

看到这些就说明成功了：
```
 ✔ Container enterprise-agent-postgres-1  Started
 ✔ Container enterprise-agent-redis-1     Started
 ✔ Container enterprise-agent-fastapi-1   Started
 ✔ Container enterprise-agent-web-1       Started
```

### 第 3 步：打开网页

浏览器打开：**http://localhost**

就能看到聊天界面了！

---

## 常用命令

| 操作 | 命令 |
|------|------|
| 启动 | `docker compose up -d` |
| 停止 | `docker compose down` |
| 查看日志 | `docker compose logs -f` |
| 重启 | `docker compose restart` |
| 查看运行状态 | `docker compose ps` |

---

## 第一次使用

### 1. 导入知识库文档

把你的产品手册、FAQ 等文档放进 `data/docs/` 文件夹，然后运行：

```bash
docker compose exec fastapi python scripts/ingest_docs.py
```

### 2. 测试对话

在网页聊天框输入问题，比如：
- "如何重置密码？"
- "你们的退货政策是什么？"
- "技术支持电话是多少？"

### 3. 查看运行状态

```bash
# 健康检查
curl http://localhost:8000/api/v1/health

# 监控指标
curl http://localhost:8000/api/v1/metrics/all
```

---

## 系统架构

```
浏览器 (http://localhost)
    ↓
Nginx (端口 80) — 静态页面 + 反向代理
    ↓
FastAPI (端口 8000) — 业务逻辑 + WebSocket
    ↓
┌─────────────────────────────────┐
│  LangGraph Agent (RAG + 记忆)   │
│  ├─ 知识库检索 (Chroma)          │
│  ├─ 短期记忆 (Redis)             │
│  └─ 长期记忆 (PostgreSQL)        │
└─────────────────────────────────┘
```

---

## 端口说明

| 端口 | 服务 | 访问方式 |
|------|------|---------|
| 80 | 前端 + Nginx | 浏览器访问 |
| 8000 | 后端 API | 内部使用，不直接访问 |
| 5432 | PostgreSQL | 内部使用 |
| 6379 | Redis | 内部使用 |

---

## 常见问题

### Q: 打不开 http://localhost 怎么办？

A: 检查服务是否正常启动：
```bash
docker compose ps
```
如果看到服务状态不是 `Up`，查看日志：
```bash
docker compose logs fastapi
```

### Q: 聊天没反应？

A: 1. 确认 `.env` 里的 `OPENAI_API_KEY` 已正确填写
   2. 检查网络连接（需要访问阿里百炼 API）
   3. 查看后端日志：`docker compose logs fastapi`

### Q: 怎么停止服务？

A: ```bash
docker compose down
```

### Q: 怎么更新代码？

A: ```bash
git pull
docker compose up -d --build
```

### Q: 磁盘空间不够了？

A: 清理不再使用的 Docker 镜像：
```bash
docker system prune -a
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 前端 | React + TypeScript + Vite |
| 后端 | FastAPI + Python 3.11 |
| 对话引擎 | LangGraph + LangChain |
| 知识库 | Chroma (向量数据库) |
| 缓存 | Redis |
| 数据库 | PostgreSQL |
| 部署 | Docker Compose |

---

## 许可

MIT
