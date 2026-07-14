# Enterprise Customer Service Agent

基于 LangGraph + ReAct 的企业级智能客服系统，覆盖 RAG 检索、多路径工作流编排、记忆管理、安全防护、评估监控。

> 架构设计详见 [docs/cloud-native-architecture.md](docs/cloud-native-architecture.md)

## 架构

```
接入层(APISIX) → 安全层(5层护栏) → 编排层(LangGraph+DAG) → 能力层(RAG+记忆+工具) → 数据层(Milvus+PG+Redis+MinIO)
                                   ↓
                           MemoryManager(三节点接入)
                          entry→rag→reply
```

## 技术栈

| 组件 | 选型 |
|------|------|
| 编排 | LangGraph |
| Agent | LangChain (create_agent) |
| LLM | 阿里百炼 Qwen-Plus / Qwen-Max |
| Embedding | text-embedding-v4 (1024维) |
| 向量库 | Chroma (开发) / Milvus (生产) |
| 服务 | FastAPI + uvicorn |
| 网关 | APISIX (路由/限流/熔断/鉴权/SSL) |
| 消息队列 | RabbitMQ (异步推理/记忆持久化/文档索引) |
| 对象存储 | MinIO (文档/日志/模型权重/备份) |
| 监控 | Prometheus + Grafana |
| CI/CD | GitLab CI + ArgoCD (GitOps) |
| 部署 | Docker Compose (开发) / K3s + Helm (生产) |

## 快速开始

### Docker Compose (开发环境，一键启动)

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入阿里百炼 API Key

# 2. 启动全部 12 个服务
make up
# 或: docker compose up -d

# 3. 入库知识库
make ingest

# 4. 验证
make test
bash scripts/smoke-test.sh
```

### 本地开发（热重载，不依赖 Docker）

```bash
make install                  # pip install + npm ci
make dev                      # API Server (uvicorn --reload, port 8000)
make dev-rag                  # RAG Server (port 8001)
```

### K3s / Helm 部署（生产环境）

```bash
# 1. 安装 K3s 集群
curl -sfL https://get.k3s.io | sh -

# 2. Helm 部署
helm upgrade --install agent deploy/helm/enterprise-agent/ \
  -f deploy/helm/enterprise-agent/values.yaml \
  -f deploy/helm/enterprise-agent/values-prod.yaml \
  --namespace agent-prod --create-namespace

# 3. 查看状态
kubectl get pods -n agent-prod
```

### 监控栈（可选）

```bash
docker compose -f docker-compose.monitoring.yml up -d
# Grafana:  http://localhost:3000 (admin/admin)
# Prometheus: http://localhost:9090
# MinIO:      http://localhost:9001
# RabbitMQ:   http://localhost:15672 (agent/agent)
```

## Makefile 常用命令

| 命令 | 说明 |
|------|------|
| `make up` / `make down` | 启动/停止全部服务 |
| `make build` | 构建全部镜像 |
| `make logs SVC=api-service` | 查看指定服务日志 |
| `make test` / `make test-cov` | 运行测试 |
| `make lint` / `make format` | 代码检查/格式化 |
| `make migrate-dry` / `make migrate` | Chroma→Milvus 迁移 |
| `make ci-full` | 本地运行完整 CI 流水线 |
| `make helm-lint` / `make helm-template` | Helm 验证 |
| `make validate` | 全量验证 (helm + imports) |

## 微服务拆分

| 服务 | 端口 | 职责 | 扩容 |
|------|------|------|------|
| api-service | 8000 | REST API + LangGraph 编排 | HPA by CPU |
| rag-service | 8001 | RAG 检索 (Milvus/Chroma) | HPA by QPS |
| agent-worker | — | MQ 消费者，异步推理 | KEDA by 队列深度 |
| ws-service | 8000 | WebSocket 会话管理 | HPA by 连接数 |
| frontend | 80 | React SPA 静态文件 | 多副本 |

## 数据存储

| 存储 | 用途 |
|------|------|
| PostgreSQL | 租户/用户/对话/评估/审计 |
| Milvus | RAG 向量库 (Partition Key 多租户隔离) |
| MinIO | 文档/图片/模型权重/日志归档/备份 |
| Redis | 会话缓存 + 分布式锁 + 限流 |
| RabbitMQ | 异步任务：推理/记忆持久化/文档索引/通知 |

## 项目结构

```
src/
├── api/            FastAPI 服务 + 路由 + 指标
├── agent/          ReAct Agent (tools + prompt)
├── graph/          LangGraph 工作流 (7节点 DAG)
├── memory/         MemoryManager (短期/长期/用户画像)
├── rag/            RAG 子系统 (加载/切块/嵌入/检索/Milvus)
├── websocket/      WebSocket 会话管理
├── worker/         RabbitMQ 消费者
├── infrastructure/ Redis 锁 + MinIO 客户端
├── safety/         安全护栏 (输入/输出/清洗)
├── evaluation/     评估指标 + 追踪器
├── channels/       多渠道接入 (微信/电话/Chatwoot)
├── protocols/      A2A + MCP 协议
└── dispatch/       消息标准化 + 仲裁
deploy/
├── helm/enterprise-agent/  K3s 部署 Chart (12 templates)
├── apisix/                 APISIX 网关配置
├── rabbitmq/               RabbitMQ 队列拓扑
├── postgres/init/          PG Schema + 种子数据
├── monitoring/             Prometheus + Grafana
├── argocd/                 ArgoCD Applications
├── nginx-frontend.conf     前端 Nginx
└── docker-compose.dev.yml  开发热重载覆盖
docker/                       多服务 Dockerfile
scripts/                      迁移/备份/冒烟/CI 脚本
```

## License

MIT
