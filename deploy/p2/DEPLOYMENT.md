# Enterprise Agent - P2-4 部署说明

## 目录结构

```
deploy/p2/
  Dockerfile                 # 多阶段构建镜像
  docker-compose.yml         # 编排文件（app + postgres + redis）
  .env.p2.example            # 环境变量模板
  scripts/
    build.sh                 # 一键构建镜像
    start.sh                 # 一键启动服务（含健康等待）
    stop.sh                  # 一键停止服务
  DEPLOYMENT.md              # 本文件
```

## 本地部署步骤

### 1. 准备环境变量

```bash
cd enterprise-agent
cp deploy/p2/.env.p2.example deploy/p2/.env.p2
```

编辑 `.env.p2`，填入：
- `OPENAI_API_KEY`：阿里云百炼 DashScope key（实际是 OpenAI 兼容接口）
- `POSTGRES_PASSWORD`：生产环境必须修改

### 2. 一键构建

```bash
bash deploy/p2/scripts/build.sh
```

构建产出 `enterprise-agent:latest` 镜像。多阶段构建，运行时镜像约 400MB。

### 3. 一键启动

```bash
bash deploy/p2/scripts/start.sh
```

脚本会按顺序启动 postgres + redis，等待健康检查通过后再启动 app。

成功输出：
```
==========================================
  All services are UP!
==========================================
  App:       http://localhost:8000
  Health:    http://localhost:8000/api/v1/health
  API docs:  http://localhost:8000/docs
==========================================
```

### 4. 验证

```bash
# 健康检查
curl http://localhost:8000/api/v1/health
# 期望: {"status":"ok","service":"enterprise-agent"}

# 对话接口
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"你好"}'

# Swagger UI
# 浏览器打开 http://localhost:8000/docs
```

### 5. 一键停止

```bash
bash deploy/p2/scripts/stop.sh
```

数据卷保留（pg、redis、chroma、logs）。如需清除全部数据：
```bash
docker compose -f deploy/p2/docker-compose.yml --env-file deploy/p2/.env.p2 down -v
```

## 挂载本地知识库

知识库文档默认从 `data/docs/` 挂载到容器 `/app/data/docs`（只读）。
如需使用自定义文档目录，修改 `docker-compose.yml` 的 volumes：

```yaml
volumes:
  - /path/to/your/docs:/app/data/docs:ro    # 改为你的路径
```

向量库默认存储在 Docker volume `p2-agent-chroma`。
如需使用本地目录持久化，改为 bind mount：

```yaml
volumes:
  - ../../chroma_data:/app/chroma_data      # 本地目录
```

## 环境变量说明

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | (必填) | LLM / Embedding API key（百炼兼容 OpenAI 格式） |
| `OPENAI_API_BASE` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | LLM API 地址 |
| `LLM_MODEL` | `qwen-plus` | 对话模型 |
| `EMBEDDING_MODEL` | `text-embedding-v4` | 向量化模型 |
| `POSTGRES_PASSWORD` | (必填) | 数据库密码 |
| `HOST_PORT` | `8000` | 应用对外端口 |
| `MAX_REASONING_TURNS` | `5` | Agent 最大推理轮次 |
| `LANGSMITH_TRACING` | `false` | 是否开启 LangSmith 追踪 |

## 云服务器部署注意事项

### 1. 安全组 / 防火墙

- 仅暴露 `8000`（应用）端口到公网，`5432`（PG）和 `6379`（Redis）**不要**对公网开放
- 如果需要 HTTPS，在前面加一层 Nginx/Caddy 反向代理
- APISIX 网关版见项目根目录 `docker-compose.yml`

### 2. 密钥管理

- **永远不要**把真实 API key 写进 `.env.p2` 后提交到 git（`.env*` 已在 `.gitignore` 中）
- 生产环境用 Docker Secrets 或环境变量直接注入
- `POSTGRES_PASSWORD` 必须修改默认值

### 3. 资源规格

| 服务 | 最低内存 | 推荐内存 |
|---|---|---|
| app | 512MB | 1GB |
| postgres | 256MB | 512MB |
| redis | 128MB | 256MB |
| 合计 | ~900MB | ~1.8GB |

1核 2GB 的云服务器可跑（单副本），但推理速度受限。

### 4. 数据持久化

Docker volumes 在 `docker compose down` 后保留，但 `docker compose down -v` 会删除。
生产环境建议定期备份：
```bash
# 备份 PostgreSQL
docker exec p2-postgres pg_dump -U postgres agent > backup_$(date +%Y%m%d).sql

# 备份向量库（必须先停止 app）
docker compose -f deploy/p2/docker-compose.yml stop app
docker run --rm -v p2-agent-chroma:/data -v $(pwd):/backup alpine \
  tar czf /backup/chroma_backup_$(date +%Y%m%d).tar.gz -C /data .
docker compose -f deploy/p2/docker-compose.yml start app
```

### 5. 日志

```bash
# 查看应用日志
docker compose -f deploy/p2/docker-compose.yml logs -f app

# 查看最近 100 行
docker compose -f deploy/p2/docker-compose.yml logs --tail 100 app
```

日志同时持久化到 volume `p2-agent-logs`（容器内 `/app/logs/`）。

### 6. 升级

```bash
# 拉取最新代码后重新构建
git pull
bash deploy/p2/scripts/build.sh
bash deploy/p2/scripts/stop.sh
bash deploy/p2/scripts/start.sh
```

### 7. 与云端版的关系

本 P2-4 部署是**精简单体版**（app + pg + redis），适合开发、测试、小型部署。
项目根目录的 `docker-compose.yml` 是**云端微服务版**（APISIX 网关 + api/ws/worker/rag 四服务 + Milvus/MinIO/RabbitMQ），适合生产级多副本部署。
两者共享同一套代码，仅部署形态不同。
