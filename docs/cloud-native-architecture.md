# 企业智能客服 — 云原生架构升级方案

> 撰写时间：2026-07-15
> 项目：`enterprise-agent` — 基于 LangGraph + ReAct 的智能客服系统
> 现状：单进程 FastAPI + Chroma + 可选 PG/Redis，docker-compose 一键部署

---

## ⚠️ 前置判断：K8s 还是 Docker Compose？

**直接上 K8s 是错的。** 这个项目当前日均 QPS 不会超过 100，一个 uvicorn worker 就能跑。先上 K8s 会增加不必要的复杂度（Pod 网络、Ingress Controller、etcd 维护、PV/PVC 管理），且本地开发体验极差。

**推荐路线：Docker Compose（现阶段）→ K3s（单机生产）→ 完整 K8s 集群（多机扩容时）**

| 阶段 | 方案 | 适用场景 | 免费 |
|------|------|----------|------|
| 开发/测试 | Docker Compose v2 | 单机、服务 < 10 个 | ✅ |
| 单机生产 | K3s + Helm | 个人/小团队生产环境 | ✅ |
| 多机集群 | K3s 集群 / MicroK8s | 需要水平扩容时 | ✅ |
| 托管（可选） | 阿里云 ACK 免费额度 | 已用阿里云百炼时可复用 | 有限免费 |

本文按 **K3s（轻量 K8s）**设计，但所有配置向下兼容 Docker Compose——你可以在 `docker-compose.yml` 验证通过后再迁移到 K3s 部署。

---

## 一、容器化与编排

### 1.1 当前问题

[现有 Dockerfile](Dockerfile) 把所有代码打进一个镜像，`uvicorn --workers 2` 在容器内多进程——这违背容器"一个进程一个容器"的原则，且无法独立扩容。

### 1.2 目标架构

```
                     ┌──────────────┐
                     │  APISIX/Nginx│  网关层（独立 Pod）
                     └──────┬───────┘
                            │
        ┌───────────────────┼───────────────────────┐
        │                   │                       │
   ┌────▼────┐      ┌──────▼──────┐       ┌────────▼────────┐
   │  API     │      │  WebSocket  │       │  Frontend (Nginx│
   │  Service │      │  Service    │       │  static)        │
   └────┬─────┘      └──────┬──────┘       └─────────────────┘
        │                   │
        └─────────┬─────────┘
                  │
     ┌────────────┼─────────────┐
     │            │             │
  ┌──▼───┐  ┌────▼────┐  ┌────▼────┐
  │Worker │  │ RAG     │  │ Channel │  异步任务/独立服务
  │Service│  │ Service │  │ Service │
  └───────┘  └─────────┘  └─────────┘
```

### 1.3 容器拆分

每个目录一个 `Dockerfile` + 独立 `requirements.txt`：

| 服务 | 路径 | 职责 | 扩容策略 |
|------|------|------|----------|
| `api-service` | `src/api/` | 同步 REST API + 依赖注入 + 路由 | 按 CPU/请求数 HPA |
| `ws-service` | `src/websocket/` | WebSocket 长连接管理 + 会话状态机 | 按连接数 HPA |
| `rag-service` | `src/rag/` | 文档加载/切块/嵌入/检索（独立于 API） | 按检索 QPS HPA |
| `agent-worker` | `src/agent/` + `src/graph/` | LangGraph 编排异步执行 | 按队列深度 KEDA |
| `channel-service` | `src/channels/` | 多渠道接入（微信/电话/Chatwoot） | 按渠道独立实例 |
| `frontend` | `frontend/` | React SPA 静态文件 | Nginx alpine，CDN 可选 |

### 1.4 K3s 部署结构（Helm Chart）

```
deploy/
├── helm/
│   └── enterprise-agent/
│       ├── Chart.yaml
│       ├── values.yaml          # 所有配置入口
│       ├── values-dev.yaml      # 开发环境覆盖
│       ├── values-prod.yaml     # 生产环境覆盖
│       └── templates/
│           ├── api-deployment.yaml
│           ├── ws-deployment.yaml
│           ├── rag-deployment.yaml
│           ├── worker-deployment.yaml
│           ├── frontend-deployment.yaml
│           ├── ingress.yaml
│           ├── configmap.yaml
│           ├── secrets.yaml
│           └── hpa.yaml
├── docker-compose.yml           # 本地开发用（完整版）
└── docker-compose.dev.yml       # 本地开发覆盖（热重载）
```

### 1.5 弹性策略

| 机制 | 实现 |
|------|------|
| **水平扩缩** | K3s HPA v2：CPU > 70% 或 memory > 80% 自动扩容 |
| **定时伸缩** | CronHPA：工作日 9:00-18:00 保持 3 副本，夜间缩到 1 |
| **冷启动优化** | 镜像分层构建（依赖层 / 代码层），启动探针就绪前不接流量 |
| **资源限制** | requests=128Mi/0.25CPU, limits=512Mi/1CPU（按服务调优） |

---

## 二、CI/CD 自动化流水线

### 2.1 选型分析

| 方案 | 优点 | 缺点 | 本项目适配 |
|------|------|------|------------|
| **GitLab CI** | 内置 Registry、环境管理、Review Apps | 需要 GitLab 实例 | ✅ 功能最完整 |
| GitHub Actions | 免费额度大、Marketplace 丰富 | 与 K8s 部署需要额外配置 | ✅ 如果代码在 GitHub |
| Jenkins | 最灵活、插件丰富 | 维护成本高、Java 运行时重 | ❌ 杀鸡用牛刀 |
| ArgoCD | GitOps 标准、自动同步 | 只做 CD 不做 CI，需另配 CI | ✅ 配合 GitLab CI/GitHub Actions |

**推荐：GitLab CI（CI 部分）+ ArgoCD（CD 部分）**

- 如果代码托管在 **GitLab**：GitLab CI 一站式，自带 Container Registry
- 如果代码托管在 **GitHub**：GitHub Actions + GitHub Container Registry
- 无论哪种，**CD 层都用 ArgoCD** 做 GitOps 自动同步

### 2.2 流水线设计

```
代码提交（Push / MR）
    │
    ▼
┌─────────────────────┐
│ Stage 1: Lint & Fmt │  ← ruff (Python) + oxlint (TypeScript) + prettier
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Stage 2: Unit Test  │  ← pytest + vitest，并行跑
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Stage 3: SAST Scan  │  ← bandit (Python) + Semgrep (通用) + Trivy (依赖)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Stage 4: Build Image│  ← Docker BuildKit，多阶段构建，层缓存
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Stage 5: Push Image │  ← 推送到 Registry，tag = commit SHA + latest
└────────┬────────────┘
         │
    ┌────┴────┐
    ▼         ▼
 测试环境    生产环境
（自动部署） （手动审批 → ArgoCD Sync）
```

### 2.3 GitLab CI 配置要点（`.gitlab-ci.yml`）

```
关键 decisions：
- ruff check + ruff format 替代 flake8+black（速度 10x）
- pytest -n auto 并行测试
- Trivy 扫描镜像漏洞（免费），Severity HIGH/CRITICAL 阻断
- 构建用 BuildKit（DOCKER_BUILDKIT=1），缓存层加速
- 测试环境：merge to main → 自动部署到 staging namespace
- 生产环境：git tag v1.x.x → 手动审批 → ArgoCD sync prod namespace
```

### 2.4 ArgoCD GitOps 流程

```
Git Repo (deploy/helm/values-prod.yaml)
    │
    │  ArgoCD 每 3 分钟 Poll
    ▼
ArgoCD Application
    │
    │  diff 检测到变更
    ▼
自动 Sync → K3s Cluster (prod namespace)
    │
    │  健康检查（Readiness Probe）
    ▼
Slack/钉钉 通知部署结果
```

---

## 三、数据存储分层

### 3.1 存储映射

```
┌─────────────────────────────────────────────────────┐
│                    数据分层                          │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐│
│  │PostgreSQL│  │  Milvus  │  │  MinIO   │  │Redis ││
│  │          │  │          │  │          │  │      ││
│  │·租户信息 │  │·知识库向 │  │·原始文档 │  │·会话 ││
│  │·对话记录 │  │  量存储  │  │·模型权重 │  │  缓存 ││
│  │·用户画像 │  │·RAG 检  │  │·日志归档 │  │·热点 ││
│  │·评估数据 │  │  索索引  │  │·图片附件 │  │  知识 ││
│  │·配置管理 │  │          │  │·备份文件 │  │·限流 ││
│  └──────────┘  └──────────┘  └──────────┘  │·分布 ││
│                                              │  式锁││
│                                              └──────┘│
└─────────────────────────────────────────────────────┘
```

### 3.2 迁移方案（Chroma → Milvus）

当前项目使用 Chroma 做向量存储。**Chroma 适合单机开发和 PoC，但生产环境有硬伤**：

| 维度 | Chroma | Milvus |
|------|--------|--------|
| 分布式 | ❌ 单机 | ✅ 天然分布式 |
| 多租户 | ❌ 需手动分区 | ✅ Partition Key 原生隔离 |
| 索引类型 | HNSW 单一 | IVF/HNSW/DiskANN 等 12 种 |
| 持久化 | 本地文件 | S3/MinIO 对象存储 |
| 监控 | 无 | Prometheus 原生 metrics |
| 混合检索 | ❌ | ✅ 标量过滤 + 向量检索一条语句 |

**迁移策略**（不丢数据）：
1. 启动 Milvus Standalone（免费单机版足够，QPS < 1000 不需要集群）
2. 写一个 `migrate_vector.py` 脚本，从 Chroma 读取 → 重新 embed → 写入 Milvus（因为 Chroma 不暴露 raw vector，稳妥做法是重跑 embed）
3. 双写阶段：`MilvusVectorStore` 和 `ChromaVectorStore` 同时写，验证 Milvus 召回率一致后再切
4. Chroma 数据保留 30 天作为回滚保险

### 3.3 租户数据隔离

PostgreSQL 中 `tenant_id` 作为每张表的复合主键前缀：

```
accounts         (tenant_id, user_id, ...)
conversations    (tenant_id, conversation_id, session_id, ...)
messages         (tenant_id, message_id, conversation_id, ...)
knowledge_bases  (tenant_id, kb_id, ...)
audit_logs       (tenant_id, log_id, ...)
```

Milvus 中 `tenant_id` 作为 Partition Key，实现物理隔离。

### 3.4 免费方案确认

| 组件 | 方案 | 费用 |
|------|------|------|
| PostgreSQL | K3s 内部署 `postgres:16-alpine` | 免费 |
| Milvus | Milvus Standalone（单 Docker 容器） | 免费 |
| MinIO | K3s 内部署 `minio/minio:latest` | 免费 |
| Redis | K3s 内部署 `redis:7-alpine` | 免费 |

全部自托管，零服务费。数据持久化通过 K3s hostPath / local-path-provisioner。

---

## 四、微服务拆分

### 4.1 拆分原则

按照 **业务边界 + 数据所有权 + 独立变更频率** 三个维度拆：

```
当前单体 src/
├── api/           → api-service（REST 接口层）
├── websocket/     → ws-service（长连接管理层）
├── graph/         → agent-worker（编排引擎层）
├── agent/         ↗
├── rag/           → rag-service（检索服务层）
├── memory/        → memory-service（记忆服务层）
├── channels/      → channel-service（渠道接入层）
├── safety/        → 嵌入为公共库（被 api-service 和 agent-worker 引用）
├── evaluation/    → 嵌入 agent-worker
└── protocols/     → 独立为公共库
```

### 4.2 服务间通信

```
┌─────────────┐   REST/HTTP    ┌─────────────┐
│ api-service │───────────────→│ rag-service  │  ← 同步：检索请求
│             │                │              │
│             │    gRPC        └──────┬───────┘
│             │← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
└──────┬──────┘                       （备选：HTTP 足够，gRPC 过度设计）
       │
       │  MQ (RabbitMQ)
       ▼
┌──────────────┐     MQ       ┌──────────────┐
│ agent-worker │←────────────│ api-service   │  ← 异步：推理任务
│              │             │              │
└──────┬───────┘             └──────────────┘
       │
       │  MQ
       ▼
┌──────────────────┐
│ memory-service   │  ← 异步：记忆持久化
└──────────────────┘
```

### 4.3 关键点

- **api-service 和 rag-service 之间用 HTTP**：检索请求量不大，HTTP 延迟可接受；gRPC 对 Python 生态支持一般且给运维增加复杂度
- **agent-worker 通过 MQ 消费**：推理任务耗时长（LLM 调用 3-10 秒），异步解耦
- **memory-service 独立为单独服务**：当前 MemoryManager 内嵌在 graph 节点里，独立后可：
  - 独立扩容（读写分离）
  - 缓存预热（热点用户记忆提前加载到 Redis）
  - 长期记忆定期清理/归档不阻塞主流程

### 4.4 公共库（不单独部署）

```
libs/
├── safety-lib/        # 安全护栏（input_guard, output_guard, sanitizer）
├── protocol-lib/      # A2A / MCP 协议实现
├── config-lib/        # 统一配置（pydantic-settings，各服务引用）
└── types-lib/         # 共享 Pydantic models / AgentState
```

通过 pip install 本地路径安装：`pip install libs/safety-lib/`

---

## 五、中间件层

### 5.1 Redis — 缓存 + 分布式锁

**缓存策略**：

```
# 短期记忆缓存（当前已有，在 docker-compose 中）
redis:6379
  ├── session:{session_id}:window      → 滑动窗口对话（TTL 1h）
  ├── session:{session_id}:summary     → LLM 摘要缓存（TTL 1h）
  ├── user:{user_id}:profile           → 用户画像缓存（TTL 24h）
  ├── kb:{kb_id}:hot_chunks            → 热点知识库 chunk（LFU 淘汰）
  └── rate_limit:{user_id}:{endpoint}  → 限流计数器
```

**分布式锁场景**（当前项目缺失，需要新增）：

```
# 知识库索引更新锁（防止并发写入冲突）
lock:index:{kb_id}                     → SET NX EX 60

# 长期记忆去重锁（防止同一对话被多次持久化）
lock:memory:{session_id}:{round}       → SET NX EX 30

# 租户配额扣减锁
lock:quota:{tenant_id}:{resource}      → SET NX EX 5
```

用 `redis-py` 实现，不需额外依赖 Redisson 等 Java 框架。

### 5.2 消息队列 — RabbitMQ

**选择 RabbitMQ 而非 Kafka**：

| 维度 | RabbitMQ | Kafka | 本项目 |
|------|----------|-------|--------|
| 消息量 | 万/秒 | 百万/秒 | 百/秒 → RabbitMQ |
| 延迟 | 毫秒级 | 百毫秒级 | 需低延迟 |
| 运维 | 简单 | 复杂（ZK/KRaft） | 小团队 |
| 消息重试 | 原生 DLX + TTL | 需自行实现 | RabbitMQ |

**异步任务队列设计**：

```
Exchange: agent.tasks (topic)
    │
    ├── Queue: agent.inference.queue
    │   Routing Key: agent.inference.{priority}
    │   消费者: agent-worker (3 副本)
    │   任务: LLM 推理、ReAct 循环
    │
    ├── Queue: memory.persist.queue
    │   Routing Key: memory.persist
    │   消费者: memory-service
    │   任务: 长期记忆持久化、摘要生成
    │
    ├── Queue: rag.index.queue
    │   Routing Key: rag.index.{kb_id}
    │   消费者: rag-service
    │   任务: 文档入库、向量化、索引重建
    │
    └── Queue: notify.queue
        Routing Key: notify.*
        消费者: channel-service
        任务: 推送通知（微信模板消息、邮件）
```

### 5.3 服务注册发现 — Nacos 还是自建？

**判断：不需要 Nacos/Eureka。** 原因：

1. **K3s 自带服务发现**：K8s Service + CoreDNS 已经提供 `service-name.namespace.svc.cluster.local` 的 DNS 解析
2. **项目服务数量 < 10**：Nacos 维护成本（Java 部署、MySQL 后端）远超收益
3. **REST 调用直接用 K8s Service**：

```python
# 不需要 hardcode IP，直接用 K8s Service 名
RAG_SERVICE_URL = "http://rag-service.agent.svc.cluster.local:8000"
```

**如果未来脱离 K8s 部署**（纯 docker-compose 场景），用 Nginx 做 DNS-based 服务发现就够了（docker-compose 的 DNS networking）。

---

## 六、API 网关

### 6.1 选型分析

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **APISIX** | 动态路由、插件丰富、毫秒级热重载、内置限流熔断 | 需 etcd 集群（可用内置 standalone） | ⭐⭐⭐⭐⭐ |
| Kong | 插件生态最大 | 需要 PostgreSQL，较重 | ⭐⭐⭐ |
| Nginx | 最简单，当前已用 | 配置变更需 reload，无动态能力 | ⭐⭐ 仅开发环境 |
| Traefik | K8s 原生，自动发现 | 插件生态不如 APISIX | ⭐⭐⭐ |

**推荐 APISIX**（免费开源，Apache 2.0 协议）。

理由：
- 当前 [nginx.conf](nginx.conf) 只有最基础的 proxy_pass + WebSocket 升级头，没有限流/熔断/鉴权
- APISIX 的 `limit-count`、`api-breaker`、`jwt-auth` 插件零代码实现这些需求
- 配置通过 Admin API 动态下发，K8s 中用 `apisix-ingress-controller` 以 CRD 声明

### 6.2 网关路由设计

```
                     APISIX (Gateway)
                    port 9080 (HTTP)
                    port 9443 (HTTPS)
                          │
    ┌─────────────────────┼──────────────────────┐
    │                     │                      │
    ▼                     ▼                      ▼
/api/v1/chat/*       /ws/*                   /*
    │                     │                      │
    ▼                     ▼                      ▼
api-service          ws-service           frontend (静态)
(限流: 20req/s/user)  (连接数上限: 1000)    (无鉴权)

/api/v1/admin/*       /api/v1/rag/*         /api/v1/webhook/*
    │                     │                      │
    ▼                     ▼                      ▼
admin-service         rag-service           channel-service
(仅内网 + JWT)        (限流: 50req/s)       (微信 IP 白名单)
```

### 6.3 网关插件配置

| 插件 | 用途 | 配置要点 |
|------|------|----------|
| `jwt-auth` | 用户鉴权（/api/v1/chat 路由） | JWT secret 存 K8s Secret，不 hardcode |
| `limit-count` | 限流（按 user_id + endpoint） | 免费用户 5req/s，Pro 用户 20req/s |
| `api-breaker` | 熔断（LLM API 调用失败率 > 50%） | 10s 熔断窗口，半开自动恢复 |
| `prometheus` | 导出 metrics 给 Prometheus | 请求量/延迟/状态码分布 |
| `http-logger` | 请求日志落盘 / 推送到日志中心 | 日志写到 Loki 或 ElasticSearch |
| `cors` | 跨域（替代 FastAPI CORSMiddleware） | 生产环境只允许业务域名 |
| `ssl` | TLS 终止 | Let's Encrypt 自动续期 + cert-manager |

### 6.4 TLS 整条链路

```
用户浏览器
    │  HTTPS (TLS 1.3)
    ▼
APISIX Gateway          ← TLS 终止在这里（Let's Encrypt 证书）
    │  HTTP（内网）
    ▼
K3s Service → Pod      ← 内网明文，不额外加密（K8s 网络策略保证）
```

---

## 七、完整架构总图

```
                            ┌──────────────┐
                            │   GitLab CI  │  代码提交自动触发
                            │   + ArgoCD   │  测试 → 构建 → 部署
                            └──────┬───────┘
                                   │
    ┌──────────────────────────────┼──────────────────────────────┐
    │                    K3s Cluster                              │
    │                                                             │
    │  ┌─────────────────────────────────────────────────────┐    │
    │  │                  APISIX Gateway                     │    │
    │  │         (路由/限流/熔断/鉴权/SSL/日志)              │    │
    │  └──────┬──────────────┬──────────────┬───────────────┘    │
    │         │              │              │                     │
    │  ┌──────▼─────┐ ┌─────▼──────┐ ┌─────▼──────┐              │
    │  │api-service │ │ ws-service │ │ frontend   │              │
    │  │ (REST)     │ │ (WebSocket)│ │ (Nginx)    │              │
    │  └──────┬─────┘ └─────┬──────┘ └────────────┘              │
    │         │              │                                    │
    │         └──────┬───────┘                                    │
    │                │                                            │
    │       ┌────────┼────────┐                                  │
    │       │  RabbitMQ       │  异步解耦                         │
    │       └────────┼────────┘                                  │
    │         ┌──────┼──────┐                                     │
    │    ┌────▼──┐ ┌─▼───┐ ┌▼────────┐                           │
    │    │agent  │ │rag  │ │memory   │                            │
    │    │worker │ │svc  │ │svc      │                            │
    │    └───────┘ └──┬──┘ └──┬──────┘                            │
    │                 │        │                                   │
    │    ┌────────────┼────────┼────────────────┐                 │
    │    │            │        │                │                 │
    │  ┌─▼──┐    ┌───▼──┐ ┌──▼───┐      ┌─────▼────┐             │
    │  │PG  │    │Milvus│ │MinIO │      │  Redis   │             │
    │  │16  │    │      │ │      │      │  7       │             │
    │  └────┘    └──────┘ └──────┘      └──────────┘             │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘
```

---

## 八、实施路线图

### Phase 1：基础设施（1-2 周）
- [ ] Docker Compose 升级（多服务 + MinIO + RabbitMQ）
- [ ] Chroma → Milvus 迁移脚本 + 双写验证
- [ ] APISIX 替换 nginx.conf（本地 Docker Compose 验证）
- [ ] PostgreSQL Schema 设计（租户隔离 + 对话记录表）

### Phase 2：CI/CD 搭建（1 周）
- [ ] GitLab CI 流水线（lint → test → build → push）
- [ ] ArgoCD 安装 + Application 配置
- [ ] 测试环境自动部署验证

### Phase 3：微服务拆分（2-3 周）
- [ ] 公共库提取（safety-lib, config-lib, types-lib）
- [ ] rag-service 独立服务
- [ ] agent-worker MQ 消费者
- [ ] memory-service 独立服务
- [ ] api-service 调用改造（HTTP → 服务间调用）

### Phase 4：K3s 生产部署（1 周）
- [ ] K3s 集群安装（单机起步）
- [ ] Helm Chart 编写 + 部署
- [ ] APISIX Ingress Controller + cert-manager
- [ ] Prometheus + Grafana 监控面板

### Phase 5：生产加固（持续）
- [ ] HPA 弹性伸缩验证
- [ ] 混沌工程（随机杀 Pod 验证自愈）
- [ ] 备份策略（PG WAL 归档 + MinIO bucket 版本控制）
- [ ] 成本优化（Spot Instance / 低峰缩容）
