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
├── ticket/         工单管理 (models + store + MCP 工具)
├── websocket/      WebSocket 会话管理
├── worker/         RabbitMQ 消费者
├── infrastructure/ Redis 锁 + MinIO 客户端
├── safety/         安全护栏 (输入/输出/清洗)
├── evaluation/     评估指标 + 追踪器
├── channels/       多渠道接入 (微信/电话/Chatwoot)
├── protocols/      A2A + MCP 协议 (含工单 MCP Server)
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

## MCP 服务（含工单管理）

`src/protocols/mcp_server.py` 暴露标准化 MCP HTTP 接口，任意 MCP 兼容 Agent
（Claude Desktop / Cursor / Claude Agent SDK / 自定义 Agent）连接后可自动发现并调用工具。

### 启动方式

```bash
# 1. 默认启动（所有 38 个工具，端口 9000）
pip install zeromcp
python -m src.protocols.mcp_server

# 2. 仅启动工单管理 MCP Server（6 个工具，端口 9005）
python -m src.protocols.mcp_server --ticket-only

# 3. 仅启动管理后台工具（35 个工具，端口 9010，不含客服基础工具）
python -m src.protocols.mcp_server --admin-only

# 4. 仅启动账单管理（5 个工具，端口 9011）
python -m src.protocols.mcp_server --billing-only

# 5. 带身份上下文启动（注入 admin 角色）
python -m src.protocols.mcp_server --user-id agent_007 --tenant-id tenant_A --roles admin,support_agent

# 6. 禁用特定工具集
python -m src.protocols.mcp_server --no-audit --no-kb    # 禁用审计和知识库工具
```

### 工具清单（共 38 个）

| 分类 | 工具 | 角色 | 说明 |
|---|---|---|---|
| **客服** | `search_knowledge_base` / `search_faq` / `escalate_to_human` | 任何用户 | 基础客服工具 |
| **工单** | `ticket_create` / `ticket_query` / `ticket_list` / `ticket_update` / `ticket_close` / `ticket_add_comment` | 用户/Admin | 创建、查询、更新、关闭工单 |
| **账单** | `billing_query_subscription` / `billing_change_plan` / `billing_refund` / `billing_list_transactions` / `billing_deduct` | Admin/Billing | 查询订阅、变更套餐、退款、扣款 |
| **用户** | `user_get_profile` / `user_reset_password` / `user_disable_account` / `user_list` / `user_update_profile` | Admin | 用户资料、密码重置、禁用账号 |
| **SSO** | `sso_configure` / `sso_list_providers` / `sso_test_connection` / `sso_enable` / `sso_disable` | Admin | 配置 SAML/OIDC 单点登录 |
| **API Key** | `api_key_generate` / `api_key_revoke` / `api_key_list` / `api_key_get` / `api_key_rotate` | Admin | 生成、吊销、轮换 API Key |
| **审计** | `audit_query_logs` / `audit_export_report` / `audit_search_by_user` / `audit_get_log_details` | Admin | 查询、导出审计日志 |
| **知识库** | `kb_ingest_document` / `kb_rebuild_index` / `kb_list_items` / `kb_delete_item` / `kb_search` | Admin/用户 | 导入文档、重建索引、搜索 |

### 权限模型

- **三层防护**：工具级权限 + 参数级校验 + 审计日志（复用 `PermissionChecker`）
- **多租户隔离**：`tenant_id` 由后端从调用者上下文强制注入，LLM 无法跨租户
- **角色粒度**：`admin` 拥有全部权限，`support_agent` 可操作工单，`billing_manager` 可操作账单
- **幂等保证**：`ticket_create` / `billing_deduct` 支持 `idempotency_key`

### MCP 客户端接入示例

```python
# Claude Agent SDK / 任意 MCP 客户端
client = MCPClient("http://localhost:9000/mcp")
await client.initialize()
tools = await client.list_tools()           # 自动发现 38 个工具

# 创建工单
result = await client.call_tool(
    "ticket_create",
    title="无法登录账号",
    description="点击登录无响应",
    category="account",
    priority="high",
    idempotency_key="req-2026-07-15-001",
)

# 查询订阅
result = await client.call_tool("billing_query_subscription")

# 生成 API Key
result = await client.call_tool("api_key_generate", name="my-app-key")
```

能力契约详见 [capability-ticket.yaml](capability-ticket.yaml)。

## License

MIT
