# enterprise-agent 生产部署与运维手册

> 工业知识库 AI Agent — 全内网离线部署
> 适用环境：Windows 10 + Docker Desktop (WSL2)
> 最后更新：2026-09-19

---

## 一、系统架构

### 1.1 业务栈容器（3 个）

| 容器名 | 镜像 | 端口 | 说明 |
|--------|------|------|------|
| prod-app-1 | enterprise-agent-app-ollama:latest | 8000（对外） | FastAPI + LangGraph + RAG(Chroma) + 内置 Ollama |
| prod-postgres-1 | postgres:16-alpine | 5432（内部） | 会话/用户/审计数据 |
| prod-redis-1 | redis:7-alpine | 6379（内部） | 缓存/限流/分布式锁 |

### 1.2 监控栈（独立，4 个容器）

Prometheus + Grafana（端口 3000）+ node-exporter + cadvisor，与业务栈网络隔离。

### 1.3 数据卷

| 卷名 | 内容 | 说明 |
|------|------|------|
| prod-agent-chroma | Chroma 向量库 | knowledge_base 14块 + long_term_memory 2块 = 共16块，生产基线 |
| prod-postgres-data | PostgreSQL 数据 | 持久化 |
| prod-redis-data | Redis 数据 | 持久化 |

### 1.4 网络

- `prod-net`：业务栈内部网络

---

## 二、环境要求

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Windows 10 64位 | Windows 10/11 64位 |
| Docker | Docker Desktop (WSL2 backend) | 最新稳定版 |
| CPU | 4 核 | 8 核+（CPU 推理，核数影响响应速度） |
| 内存 | 8GB | 16GB+（容器上限 8GB，推理峰值打满） |
| 磁盘 | 20GB 可用 | 50GB+（镜像 4.5GB + 数据卷 + 日志） |
| 网络 | 内网离线（无需外网） | — |

> **注意**：生产环境全离线部署，构建镜像时需临时联网（拉取基础镜像 + pip 安装依赖），构建完成后运行时完全离线。

---

## 三、部署步骤

### 3.1 首次部署

```powershell
# 进入项目目录
cd C:\Users\hai\enterprise-agent

# 1. 构建业务镜像（约 15 分钟，需联网，torch CPU 版下载较慢）
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production build app

# 2. 启动全部容器
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d

# 3. 等待健康检查通过（约 1-2 分钟）
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production ps

# 4. 验证 API
curl.exe -s http://localhost:8000/api/v1/health
# 期望返回: {"status":"ok","service":"enterprise-agent","aliyun_demo_fallback":false}
```

### 3.2 健康检查

```powershell
# 容器状态
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production ps

# API 健康
curl.exe -s http://localhost:8000/api/v1/health

# Prometheus metrics
curl.exe -s http://localhost:8000/api/v1/metrics/prometheus | Select-Object -First 10

# 应用日志
docker logs prod-app-1 --tail 50

# 聊天接口测试
curl.exe -s -X POST http://localhost:8000/api/v1/chat `
  -H "Content-Type: application/json" `
  -d '{\"message\":\"ThermoView T100测温范围是多少？\",\"session_id\":\"deploy_test\"}'
```

### 3.3 停止与启动

```powershell
# 停止业务栈（保留数据卷）
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production down

# 启动
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d

# 仅重启 app（配置/代码更新后）
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app
```

> **重要**：所有 compose 操作必须显式加 `-f deploy/prod/docker-compose.prod.yml`，否则会操作到根目录云端形态的旧容器。

---

## 四、配置说明

### 4.1 环境变量文件

路径：`deploy/prod/.env.production`

| 变量 | 示例值 | 说明 |
|------|--------|------|
| `OPENAI_API_BASE` | `http://127.0.0.1:11434/v1` | Ollama 本地 OpenAI 兼容接口（容器内） |
| `LLM_MODEL` | `qwen2.5:7b` | 大模型名称（Ollama 内置） |
| `RERANK_MODEL` | `/app/models/bge-reranker-base` | rerank 模型路径（容器内，权重已内置） |
| `POSTGRES_PASSWORD` | 64位随机串 | 数据库密码（Phase4a 已改随机密钥） |
| `POSTGRES_USER` | `postgres` | 数据库用户 |
| `POSTGRES_DB` | `enterprise_agent` | 数据库名 |
| `REDIS_URL` | `redis://prod-redis-1:6379/0` | Redis 连接 |
| `HF_HUB_OFFLINE` | `1` | 禁用 HuggingFace 联网 |
| `TRANSFORMERS_OFFLINE` | `1` | 禁用 transformers 联网 |
| `CHROMA_PERSIST_DIR` | `/app/chroma_data` | Chroma 持久化目录（容器内） |

### 4.2 镜像内置资产

- **bge-reranker 权重**：`/app/models/bge-reranker-base/`（仅 safetensors，已排除 onnx/pytorch_model.bin 冗余）
- **预构建向量库**：`/app/chroma_data/`（knowledge_base + long_term_memory，随镜像分发）
- **知识库文档**：`/app/data/docs/`（PDF/Markdown/HTML）
- **Ollama 二进制**：`/usr/bin/ollama` + `/usr/lib/ollama/`（内置，单容器私有化部署）

### 4.3 关键性能参数（src/config.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_reasoning_turns` | 5 | Agent 最大推理轮次 |
| `max_turns_faq` | 1 | FAQ 通道轮次 |
| `max_turns_technical` | 5 | 技术查询通道轮次 |
| `max_turns_complex` | 4 | 复杂查询通道轮次 |
| `rerank_enabled` | True | 启用本地 bge-reranker 重排序 |
| `retrieval_rerank_top_n` | 3 | rerank 返回 top N |

---

## 五、数据备份与恢复

### 5.1 Chroma 向量库备份

```powershell
# 备份（打包数据卷）
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
docker run --rm -v prod-agent-chroma:/data -v "${PWD}:/backup" alpine `
  tar czf "/backup/chroma_backup_${timestamp}.tar.gz" -C /data .

# 恢复（停止 app 后恢复，再启动）
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production stop app
docker run --rm -v prod-agent-chroma:/data -v "${PWD}:/backup" alpine `
  sh -c "rm -rf /data/* && tar xzf /backup/chroma_backup_YYYYMMDD_HHMMSS.tar.gz -C /data"
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production start app
```

### 5.2 PostgreSQL 备份

```powershell
# 备份
docker exec prod-postgres-1 pg_dump -U postgres enterprise_agent > pg_backup_$(Get-Date -Format "yyyyMMdd_HHmmss").sql

# 恢复
docker exec -i prod-postgres-1 psql -U postgres enterprise_agent < pg_backup_YYYYMMDD_HHMMSS.sql
```

### 5.3 Redis 备份

```powershell
# 触发持久化
docker exec prod-redis-1 redis-cli BGSAVE

# 复制 RDB 文件
docker cp prod-redis-1:/data/dump.rdb .\redis_dump_$(Get-Date -Format "yyyyMMdd_HHmmss").rdb
```

### 5.4 备份策略建议

- Chroma 向量库：每次知识库更新后备份
- PostgreSQL：每日自动备份（可加 cron）
- Redis：可重建，按需备份
- 所有备份文件存储到独立磁盘或 NAS

---

## 六、升级流程

### 6.1 代码/配置升级

```powershell
# 1. 备份数据（见第五节）
# 2. 更新代码（git pull 或替换文件）
# 3. 重新构建镜像
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production build app

# 4. 重建 app 容器（postgres/redis 不动，数据卷保留）
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app

# 5. 等待健康
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production ps

# 6. 验证
curl.exe -s http://localhost:8000/api/v1/health

# 7. 全量回归（可选，在主机 venv 中运行）
.\venv\Scripts\python.exe -m pytest -o addopts="" -q -n 2 --basetemp=".pytest_tmp" -p no:cacheprovider
```

### 6.2 知识库更新

```powershell
# 方式一：通过 API 上传文档（运行时）
curl.exe -s -X POST http://localhost:8000/api/v1/admin/knowledge/{kb_id}/documents/upload `
  -F "file=@manual.pdf"

# 方式二：离线批量入库（联网机器上执行，生成 chroma_data 后重新构建镜像）
pip install -r requirements.txt
python scripts/ingest_docs.py
# 然后重新 build 镜像
```

### 6.3 模型更新

- **LLM 模型**：修改 `.env.production` 的 `LLM_MODEL`，确保 Ollama 已 pull 对应模型，重启 app
- **rerank 模型**：替换 `models/bge-reranker-base/` 权重，重新构建镜像
- **Embedding 模型**：默认 Ollama bge-m3，修改 Ollama 配置即可

---

## 七、监控与告警

### 7.1 访问监控面板

- Grafana：`http://localhost:3000`
- Prometheus：`http://localhost:9090`
- 应用 metrics：`http://localhost:8000/api/v1/metrics/prometheus`

### 7.2 关键监控指标

| 指标 | 告警阈值 | 说明 |
|------|----------|------|
| 容器重启次数 | > 3 次/小时 | 应用异常崩溃 |
| API 响应时间 P99 | > 120s | CPU 瓶颈或查询异常 |
| 健康检查失败 | 连续 3 次 | 应用不可用 |
| 内存使用率 | > 90% | 推理峰值，考虑加内存 |
| 磁盘使用率 | > 85% | 日志/数据卷膨胀 |

### 7.3 日志查看

```powershell
# 应用日志（实时）
docker logs -f prod-app-1

# 最近 100 行
docker logs prod-app-1 --tail 100

# 按时间过滤
docker logs prod-app-1 --since 30m

# PostgreSQL 日志
docker logs prod-postgres-1 --tail 50
```

---

## 八、常见问题排查

### 8.1 容器启动失败

```powershell
# 查看启动日志
docker logs prod-app-1 --tail 100

# 常见原因：
# 1. POSTGRES_PASSWORD 不匹配（.env 与数据卷不一致）→ 保持 .env 不变，或重置数据卷
# 2. 端口 8000 被占用 → netstat -ano | findstr :8000
# 3. 内存不足 → 关闭其他占用内存的程序
```

### 8.2 响应慢（> 60s）

- CPU 推理瓶颈：8 核短问答约 10s，长问答约 37s，故障查询优化后约 112s
- 检查是否走了 ReAct 多轮：日志中查看 `rag_node` / `agent` 轮次
- 故障代码类查询已优化为快速 RAG 路径（单次 LLM 生成）
- 并发时吞吐量不增，属正常 CPU 瓶颈

### 8.3 Rerank 不生效

- 确认 `.env.production` 中 `RERANK_MODEL` 指向容器内 `/app/models/bge-reranker-base`
- 确认镜像构建时 `models/bge-reranker-base/model.safetensors` 存在
- 容器内验证：`docker exec prod-app-1 python -c "from sentence_transformers import CrossEncoder; m=CrossEncoder('/app/models/bge-reranker-base'); print(m.predict([('测试','测试')]))"`

### 8.4 知识库检索不到

- 确认 Chroma 数据卷已挂载：`docker exec prod-app-1 ls /app/chroma_data/`
- 确认集合存在：`docker exec prod-app-1 python -c "import chromadb; c=chromadb.PersistentClient('/app/chroma_data'); print(c.list_collections())"`
- 期望：knowledge_base + long_term_memory 两个集合

### 8.5 WebSocket 连接失败

- 确认端点：`ws://localhost:8000/ws/chat`
- 消息格式：`{"type":"chat_message","message":"...","session_id":"..."}`
- 回复为流式：`streaming_chunk`（delta/text 字段），结束标志 `done:true`，citations 在最后一个 chunk

---

## 九、离线合规说明

### 9.1 已清除的外网依赖

- `src/` 代码中所有外网 API 地址已清零
- `docker-compose.yml` 中 LLM_MODEL 默认值已从云端 qwen-plus 改为本地 qwen2.5:7b
- Embedding 默认走本地 Ollama bge-m3（OpenAI 兼容接口）
- `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` 禁止运行时联网下载模型
- rerank 权重内置镜像，运行时无需联网

### 9.2 按需保留的外网地址

- 第三方协作平台（钉钉/飞书/Slack/GitHub）Webhook 地址：11 处，仅在启用对应集成时使用，默认不调用

### 9.3 构建时联网需求

- 拉取基础镜像：`python:3.10-slim`、`ollama/ollama:latest`、`postgres:16-alpine`、`redis:7-alpine`
- pip 安装依赖：默认清华镜像源，torch CPU 版从 pytorch.org 下载
- 构建完成后运行时完全离线

---

## 十、接口速查

### 10.1 HTTP 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/metrics/prometheus` | Prometheus metrics |
| POST | `/api/v1/chat` | 同步聊天（body: `{"message":"...","session_id":"..."}`） |
| POST | `/api/v1/admin/knowledge/{kb_id}/documents/upload` | 上传知识库文档 |

### 10.2 WebSocket 接口

| 端点 | 说明 |
|------|------|
| `ws://localhost:8000/ws/chat` | 流式聊天 |

**发送消息**：
```json
{"type":"chat_message","message":"ThermoView T100测温范围？","session_id":"test"}
```

**接收消息类型**：
- `session_ready`：连接就绪
- `typing_indicator`：正在输入（`is_typing` + `status`）
- `streaming_chunk`：流式分片（`delta`/`text` 内容，`done:true` 结束，`citations` 引用）

---

## 附录：关键文件路径

| 文件 | 路径 | 说明 |
|------|------|------|
| Dockerfile | `Dockerfile` | 镜像构建（四 stage：ollama-src/runtime-base/runtime-with-ollama/runtime） |
| 生产编排 | `deploy/prod/docker-compose.prod.yml` | 业务栈 compose |
| 生产环境变量 | `deploy/prod/.env.production` | 敏感配置 |
| 运行时依赖 | `requirements-runtime.txt` | 镜像内 pip 依赖 |
| 应用入口 | `main.py` | FastAPI 启动 |
| Graph 节点 | `src/graph/nodes.py` | clarify/router/faq/rag 节点 |
| 配置 | `src/config.py` | 全局配置（max_turns 等） |
| 向量库数据 | `chroma_data/` | 预构建 Chroma 数据（随镜像分发） |
| rerank 权重 | `models/bge-reranker-base/` | bge-reranker 模型 |
| 知识库文档 | `data/docs/` | PDF/Markdown/HTML 源文件 |
