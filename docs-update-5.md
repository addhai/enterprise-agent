# 企业级智能客服 Agent — 云原生微服务架构设计文档

> 日期：2026-06-21（初版）
> 最后更新：2026-07-17（v2.0 — 云原生微服务架构 + 业务系统升级）
> 覆盖技能：RAG 知识库引擎（Milvus + 多后端路由）、ReAct 范式、LangGraph 工作流编排、高级记忆管理、微服务拆分、API 网关、消息队列、对象存储、K3s 部署、监控告警、安全纵深防御、RBAC权限、工单系统、客户管理、满意度调查、数据仪表盘、人工工作台
> GitHub：github.com/addhai/enterprise-agent

---

## 项目总结

### 一、项目背景

传统客服系统依赖人工坐席，存在响应慢、成本高、服务时间受限等问题。企业产品文档分散、技术问题排查依赖专家经验，无法满足7×24小时服务需求。随着AI Agent技术发展，构建一个具备私有知识检索、自主推理、安全可控的企业级智能客服系统成为必然选择。

### 二、项目目标

打造一个覆盖"用户接入→意图理解→知识检索→自主推理→人工兜底→服务闭环"全链路的企业级智能客服Agent平台。目标实现：80%常见问题AI自主解决、平均响应时间<3秒、人工介入率<20%、支持多渠道接入（Web/飞书/Chatwoot）、具备完整的服务管理后台（工单/客户/满意度/权限）。

### 三、核心开发工作

- 基于 LangGraph 实现多智能体工作流编排（8节点单层StateGraph + 条件路由 + Reflection自我反思节点）
- 基于 RAG + Milvus + BM25 + RRF 实现混合检索知识库引擎（三层解耦插件化架构 + 多后端路由适配）
- 基于 ReAct 范式实现自主推理Agent（思考-行动-观察循环 + 动态max_turns收敛控制 + 工具白名单）
- 基于 Redis + PostgreSQL + Milvus 实现三层记忆管理架构（短期滑窗 + LLM结构化摘要 + 向量长期记忆）
- 基于五层纵深防御模型实现智能体安全防护（输入检测→编排护栏→Agent约束→输出校验→审计告警）
- 基于 MCP 协议实现标准化工具互联（billing/users/sso/feishu/github/email/slack/calendar/filesystem/api_keys等10+工具）
- 基于 RabbitMQ 实现异步任务解耦（4业务队列 + DLQ死信队列 + Topic Exchange + 优先级支持）
- 基于 APISIX 实现云原生API网关（动态路由 + 限流熔断 + JWT鉴权 + Prometheus指标导出）
- 基于 K3s + Helm + ArgoCD 实现云原生部署（Docker Compose开发环境 → K3s生产环境 + GitOps自动同步）
- 基于 RBAC 模型实现4级权限控制体系（Super Admin/Admin/Agent/Viewer，15个权限点细粒度控制）
- 基于状态机实现工单全生命周期管理（open→in_progress→resolved/closed/cancelled，状态机不可变约束）
- 基于画像标签实现客户管理系统（客户画像 + 标签管理 + 服务历史 + 时间线追踪）
- 基于 CSAT 模型实现满意度调查（1-5星评分 + 标签分类 + 文字留言收集）
- 基于角色推送实现通知中心（系统消息 + 转接提醒 + 工单提醒，按角色/用户精准推送）
- 基于 KPI 聚合实现数据仪表盘（会话量/AI解决率/人工介入率/工单统计/满意度 + 实时活动监控 + 客服绩效排行）
- 基于 SSE + 队列实现人工客服工作台（转接队列 + AI上下文摘要 + 客服回复 + 服务关闭）
- 基于内存存储 + 工厂模式实现演示数据注入（工单/客户/满意度/用户/通知 示例数据自动生成）
- 基于 FastAPI + React + TypeScript 实现前后端分离全栈架构（RESTful API + WebSocket实时通信）

### 四、项目成果

- 完成从单体RAG聊天机器人到云原生微服务架构的完整演进
- 代码规模：14,707+行Python，90+模块，前端2,000+行TypeScript/React
- 部署方案：Docker Compose（12服务一键启动）/ K3s + Helm + ArgoCD（生产GitOps）
- 核心指标：FAQ直达<1s、技术排查2-5s、RAG混合检索准确率>95%、LLM调用减少60-80%（v2.0扁平化）
- 业务覆盖：4级权限 + 工单全生命周期 + 客户画像 + 满意度调查 + 通知中心 + 数据仪表盘 + 人工工作台
- GitHub：github.com/addhai/enterprise-agent

## 一、项目概述

### 1.1 目标

开发一个企业级 SaaS 产品智能客服 Agent，具备：

- 产品知识库问答（基于 RAG，支持多格式文档解析、混合检索、多后端路由、权限管控、多租户隔离）
- 常见问题自动回复（FAQ 匹配）
- 复杂问题转接人工客服
- 多轮对话上下文理解（三层记忆架构）
- 多渠道接入（Web / 微信 / 电话 / Chatwoot）
- 多 Agent 协作（MCP 工具互联 + A2A 委托）
- 云原生部署（Docker Compose 开发 → K3s + Helm + ArgoCD 生产）

### 1.2 技术栈（v0.5 更新）

| 组件 | 版本 | 技术选型 | 说明 |
|------|------|---------|------|
| **编排框架** | >=0.2.0 | LangGraph | 有状态工作流编排，8 节点 DAG |
| **Agent 框架** | >=0.3.0 | LangChain | ReAct 循环 + 工具调用 |
| **LLM** | — | 阿里百炼 Qwen-Plus / Qwen-Max | 分层模型策略，兼容 OpenAI 接口 |
| **Embedding** | — | DashScope text-embedding-v4 | 1024 维，OpenAI 兼容格式 |
| **API 网关** | 3.14.1 | Apache APISIX | 路由/限流/熔断/鉴权/Prometheus 指标 |
| **消息队列** | 4.0 | RabbitMQ | 4 业务队列 + 3 DLQ，Topic 交换机 |
| **向量数据库（生产）** | 2.5.9 | Milvus Standalone | Partition Key 多租户隔离，MinIO 持久化 |
| **向量数据库（开发/降级）** | >=0.5.0 | Chroma | 本地持久化，零配置启动 |
| **对象存储** | RELEASE.2025-06-26 | MinIO | S3 兼容，文档/日志/模型/备份 |
| **关系数据库** | 16-alpine | PostgreSQL | 9 表业务数据 + 审计日志 |
| **缓存** | 7-alpine | Redis | 会话缓存 + 分布式锁 + 短期记忆 |
| **容器编排** | — | K3s + Helm | 轻量级 Kubernetes 发行版 |
| **GitOps** | — | ArgoCD | 声明式应用同步，Staging(自动) + Prod(手动) |
| **CI/CD** | — | GitLab CI | 6 阶段流水线 (lint → test → sast → build → deploy) |
| **监控** | 3.3.0 / 11.6.0 | Prometheus + Grafana | 8 采集目标 + 8 告警规则 + 预置 Dashboard |
| **日志** | 3.3.0 (可选) | Loki + Promtail | 日志聚合与分析 |
| **服务框架** | >=0.115.0 | FastAPI + uvicorn | REST API + WebSocket |
| **语言** | 3.11+ | Python | asyncio + type hints |
| **前端** | — | React + Vite | SPA 静态部署（Nginx 1.27-alpine） |
| **视觉引擎** | — | Qwen-VL-Plus → GPT-4o → PaddleOCR → Tesseract | ABC 降级策略 |
| **代码质量** | >=0.9.0 | ruff | Lint + Format（替代 flake8 + black）|
| **SAST** | — | bandit + semgrep + trivy | Python AST + 语义模式 + 容器漏洞 |

### 1.3 整体架构（v0.5 云原生版）

```
                              ┌─────────────────────────┐
                              │    外部用户 / 多渠道      │
                              │   Web Chat / 微信 / 电话  │
                              └───────────┬─────────────┘
                                          │ HTTPS / WSS
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          接入层 — APISIX 网关 (:9080/:9443)                  │
│                                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ 路由转发  │  │ 限流控制  │  │ 熔断保护  │  │ JWT 鉴权  │  │ Prometheus│     │
│  │ (4 rules)│  │(20-50/s) │  │(5 fail→) │  │(key-auth) │  │  metrics  │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
└───────┬──────────────┬──────────────┬──────────────┬────────────────────────┘
        │              │              │              │
        ▼              ▼              ▼              ▼
┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
│api-service │  │ws-service │  │rag-service│  │ frontend  │
│   :8000    │  │   :8000    │  │   :8001   │  │   :80     │
│            │  │            │  │            │  │           │
│ REST API   │  │ WebSocket  │  │ RAG 检索   │  │ React SPA │
│ LangGraph  │  │ 长连接管理  │  │ Milvus/Chroma│ │ Nginx     │
│ 工作流编排  │  │ 流式推送   │  │ 混合检索   │  │ 静态文件   │
│ 记忆管理    │  │ 会话状态   │  │ 文档入库   │  │           │
└──┬───┬─────┘  └─────┬─────┘  └──┬───┬─────┘  └───────────┘
   │   │              │           │   │
   │   │    ┌─────────┘           │   │
   │   │    ▼                     │   │
   │   │  ┌────────────────┐      │   │
   │   └─►│   RabbitMQ      │◄─────┘   │
   │      │ agent.tasks     │          │
   │      │ (Topic 交换机)   │          │
   │      │                 │          │
   │      │ ┌─────────────┐ │          │
   │      │ │inference.q  │ │          │
   │      │ │memory.q     │ │          │
   │      │ │rag.index.q  │ │          │
   │      │ │notify.q     │ │          │
   │      │ └─────────────┘ │          │
   │      └────────┬────────┘          │
   │               │                   │
   │               ▼                   │
   │      ┌────────────────┐           │
   │      │ agent-worker   │           │
   │      │ 异步推理消费者   │           │
   │      │ LangGraph 编排  │           │
   │      └────────────────┘           │
   │                                   │
   └───────┬───────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            数据存储层                                        │
│                                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │PostgreSQL│  │  Milvus  │  │  MinIO   │  │  Redis   │  │ RabbitMQ │     │
│  │   :5432  │  │  :19530  │  │  :9000   │  │  :6379   │  │  :5672   │     │
│  │          │  │          │  │          │  │          │  │          │     │
│  │ 9 表     │  │ 向量检索  │  │ 对象存储  │  │ 会话缓存  │  │ 消息队列  │     │
│  │ 租户隔离  │  │ 多租户    │  │ S3 兼容  │  │ 分布式锁  │  │ 4+3 DLQ  │     │
│  │ 审计日志  │  │Partition  │  │ 文档/日志 │  │ 短期记忆  │  │ 死信机制  │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                            可观测性层                                        │
│                                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│  │Prometheus│  │ Grafana  │  │  Loki    │  │ LangSmith│                   │
│  │  :9090   │  │  :3000   │  │  :3100   │  │ (可选)   │                   │
│  │          │  │          │  │          │  │          │                   │
│  │ 8 采集   │  │ 1 面板   │  │ 日志聚合  │  │ LLM 追踪 │                   │
│  │ 8 告警   │  │          │  │ (可选)    │  │          │                   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、微服务拆分

### 2.1 服务清单

| 服务 | 端口 | Dockerfile | 职责 | 通信方式 | 扩容策略 | 资源限额 |
|------|------|-----------|------|---------|---------|---------|
| **api-service** | 8000 | `docker/api/Dockerfile` | REST API + LangGraph 工作流编排 + 记忆管理 + 依赖注入 | HTTP (被网关调用) + MQ (发布任务) | HPA by CPU 70% | 1G mem / 2 CPU |
| **rag-service** | 8001 | `docker/rag/Dockerfile` | RAG 检索独立服务 (Milvus/Chroma 多后端路由 + 混合检索 + 文档入库) | HTTP (被 api-service/worker 调用) + MQ (消费索引任务) | HPA by QPS | 1G mem / 2 CPU |
| **agent-worker** | — | `docker/worker/Dockerfile` | RabbitMQ 消费者，异步执行 LangGraph 推理 | MQ (消费 inference.q) | KEDA by 队列深度 | 1G mem / 2 CPU |
| **ws-service** | 8000 | 复用 api 镜像 | WebSocket 长连接 + 会话管理 + 流式推送 | WebSocket (客户端直连) + Redis (会话共享) | HPA by 连接数 | 512M mem / 1 CPU |
| **frontend** | 80 | nginx:1.27-alpine | React SPA 静态文件服务 | HTTP (被网关路由) | 多副本 | 128M mem / 0.5 CPU |
| **apisix** | 9080/9443 | apache/apisix:3.14.1 | API 网关：路由转发/限流/熔断/鉴权/Prometheus 指标 | HTTP/HTTPS (所有外部流量入口) | 多副本 | 2G mem / 2 CPU |

### 2.2 服务通信矩阵

```
                     ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
                     │api-service│rag-service│worker    │ws-service│frontend  │apisix    │
┌──────────┬──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│api-service│   —     │ HTTP(S)  │ MQ(Pub)  │ Redis    │    —     │ HTTP(In) │
│          │          │ RagClient │agent.task│(会话共享)│          │(被网关代理)│
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│rag-service│ HTTP(In)│    —     │ MQ(Sub)  │    —     │    —     │    —     │
│          │(被调用)  │          │rag.index.q│          │          │          │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│worker    │ MQ(Sub)  │ HTTP(S)  │    —     │    —     │    —     │    —     │
│          │inference.q│RagClient │          │          │          │          │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ws-service│ Redis    │    —     │ MQ(Pub)  │    —     │    —     │ HTTP(In) │
│          │(会话共享)│          │notify.q  │          │          │(被网关代理)│
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│apisix    │ HTTP(Out)│    —     │    —     │ HTTP(Out)│ HTTP(Out)│    —     │
│          │(反向代理)│          │          │(反向代理)│(反向代理)│          │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘

通信模式：
  HTTP(S)  — 同步请求-响应（api-service ↔ rag-service）
  MQ(Pub)  — 异步发布（api-service → RabbitMQ，发布推理/记忆/索引/通知任务）
  MQ(Sub)  — 异步消费（agent-worker ← RabbitMQ，消费推理任务）
  Redis    — 共享状态（api-service ↔ ws-service，会话数据共享）
  HTTP(In) — 外部流量入口（所有客户端请求经过 APISIX 路由）
```

---

## 三、数据流转

### 3.1 核心业务流：FAQ 快速问答

```
用户: "怎么重置密码？"
  │
  ▼
APISIX (:9080) — 路由匹配 /api/v1/chat → api-service:8000
  │ [limit-count: 20次/秒/用户]
  │ [api-breaker: 连续失败5次触发熔断]
  ▼
api-service — FastAPI POST /api/v1/chat
  │ 1. InputGuard.check() → 安全检测通过
  │ 2. 构建 AgentState
  │
  ▼
LangGraph Workflow (8 节点 DAG)
  │
  ├─[entry]  MemoryManager 注入长期记忆上下文
  │    └─ Redis: 加载短期记忆（滑动窗口 20 条）
  │    └─ PG: 检索长期记忆 (TOP 3 by importance)
  │
  ├─[clarify] 意图澄清
  │    └─ 检测到关键词 "密码" → 命中 FAQ 豁免列表 → clarity_status="clear"
  │
  ├─[router]  意图分类 → intent="faq"
  │
  ├─[faq]     FAQ 匹配
  │    └─ 关键词匹配成功 → faq_match=True
  │
  ├─[reply]   生成回复 + 记忆持久化
  │    ├─ MemoryManager 持久化对话摘要（异步: MQ → memory.persist.queue）
  │    ├─ OutputGuard.check() → 输出安全检测通过
  │    └─ quality_score 评估（在线采样率控制）
  │
  ▼
返回: "您可以通过以下步骤重置密码：1. 访问登录页面 2. 点击'忘记密码'..."
  │
  ▼
Audit Log: PG audit_logs 记录 (action="chat", resource_type="conversation", severity="info")
```

### 3.2 核心业务流：Technical 复杂问题（异步推理）

```
用户: "我们的 SDK 2.3.1 版本在 arm64 架构下编译失败，报错 libssl.so.3 找不到，怎么解决？"
  │
  ▼
APISIX → api-service
  │ InputGuard.check() → 安全检测通过（无注入特征）
  │ 
  ▼
[方案 A: 同步处理 — 适合快速 FAQ 和简单 Technical]
  │
  ├─[entry]  注入长期记忆上下文
  ├─[clarify] 意图分类 → technical, 检测到完整信息(版本号/架构/错误信息) → clarity_status="clear"
  ├─[router]  intent="rag"
  ├─[rag]     三方检索
  │   ├─ 调用 RagClient.search_async() → rag-service HTTP
  │   │   └─ rag-service: Milvus 向量检索 (Partition Key=tenant_id)
  │   │      + BM25 关键词检索 ("arm64", "libssl", "SDK 2.3.1")
  │   │      + RRF 融合 → Top-30 粗筛
  │   │   └─ 权限过滤 (access_level IN user_levels)
  │   ├─ FAQ 匹配 (兜底)
  │   └─ 知识图谱检索 (预留)
  ├─[reflect] 自我反思 & 幻觉检测
  │   └─ 交叉验证检索结果与回复引用的一致性
  ├─[reply]   生成回复
  │
  ▼
同步返回: 技术排查方案

[方案 B: 异步处理 — 适合复杂 Technical 和需要多轮推理的场景]
  │
  ├─ api-service 发布消息到 RabbitMQ
  │   └─ exchange: agent.tasks, routing_key: agent.inference.complex
  │   └─ priority: 5 (中优先级)
  ├─ api-service 返回 202 Accepted + task_id
  │
  ▼
agent-worker 消费消息
  ├─ 执行 LangGraph 编排（同上 8 节点 DAG）
  ├─ 结果写回 Redis (task_id → result)
  │
  ▼
api-service 轮询/WebSocket 推送结果给用户
```

### 3.3 核心业务流：人工转接

```
用户: "你们的服务太烂了，我要投诉！"
  │
  ▼
APISIX → api-service
  │
  ├─[entry]  注入记忆上下文
  ├─[clarify] 情绪检测 → sentiment="angry" → 标记 needs_human=True
  │           情绪检测前置：愤怒/紧急用户不追问，直接标记转人工
  ├─[router]  intent="human"（情绪触发 + 关键词"投诉"）
  ├─[human]   生成转接话术 + 收集上下文摘要
  │   └─ 触发通知: MQ → notify.push.queue
  │   └─ 人工客服系统收到通知（含对话摘要 + 用户画像 + 情绪标签）
  ├─[reply]   安抚话术
  │
  ▼
返回: "非常抱歉给您带来不好的体验。我已经为您转接人工客服，请稍候..."
  │
  ▼
Audit Log: severity="warning", details={sentiment: "angry", escalation_reason: "用户投诉"}
```

### 3.4 文档入库流（异步索引）

```
管理员上传文档 (PDF/Markdown/HTML/DOCX/Image)
  │
  ▼
api-service POST /api/v1/admin/knowledge-base/index
  │ 1. 鉴权: 检查用户 admin 角色
  │ 2. 获取分布式锁: RedisLock("lock:index:{kb_id}", ttl=120)
  │    └─ 防止并发入库冲突
  │ 3. 文件上传到 MinIO: bucket=agent-docs, object=tenant/{tenant_id}/{file_hash}
  │
  ▼
发布索引任务到 RabbitMQ
  │ exchange: agent.tasks, routing_key: rag.index.{kb_id}
  │ priority: 3 (低优先级)
  │ TTL: 10 分钟
  │
  ▼
rag-service 消费 rag.index.queue
  │ 1. 从 MinIO 下载文件
  │ 2. FileSyncManager 检测变更 (content_hash + mtime)
  │ 3. @register_loader 格式加载器 (Markdown/PDF/HTML/DOCX/Image)
  │ 4. IngestionPipeline 处理管道:
  │    Normalize → NoiseFilter → StructureDetect → ContentSafety
  │    → MetadataEnrich → QualityCheck → Deduplicate
  │ 5. HybridChunker 双粒度切块 (标准 512 + 句子窗口)
  │ 6. MilvusVectorStore.insert(batch_size=100)
  │    └─ Milvus 写入 MinIO 持久化 (内嵌 etcd + MinIO backend)
  │ 7. 更新 PG knowledge_bases (doc_count, chunk_count, status)
  │ 8. 释放分布式锁
  │
  ▼
失败处理:
  │ 消息 TTL 过期 → agent.dlx → rag.index.dlq (保留 24 小时)
  │ 人工通过管理面板重试 DLQ
```

---

## 四、部署架构

### 4.1 开发环境（Docker Compose）

```
┌──────────────────────────────────────────────────────┐
│                   Docker Host                         │
│                                                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │ apisix  │  │ api-svc │  │ rag-svc │  │ ws-svc  │ │
│  │ :9080   │  │ :8000   │  │ :8001   │  │ :8000   │ │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘ │
│       │            │            │            │       │
│       └────────────┴────────────┴────────────┘       │
│                        │ agent-net (bridge)           │
│       ┌────────────────┼────────────────┐            │
│       │                │                │            │
│  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐  ┌─────────┐│
│  │postgres │  │ milvus  │  │  minio  │  │  redis  ││
│  │ :5432   │  │ :19530  │  │ :9000   │  │ :6379   ││
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘│
│                                                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────────┐  │
│  │rabbitmq │  │frontend │  │ worker (后台消费者)  │  │
│  │ :5672   │  │ :80     │  │                     │  │
│  └─────────┘  └─────────┘  └─────────────────────┘  │
│                                                      │
│  启动: docker compose up -d                          │
│  扩展: docker compose up -d --scale agent-worker=3   │
└──────────────────────────────────────────────────────┘
```

启动命令：
```bash
# 1. 配置环境变量
cp .env.example .env

# 2. 一键启动 12 个服务
make up

# 3. 入库知识库
make ingest

# 4. 验证服务
make test && bash scripts/smoke-test.sh

# 5. (可选) 启动监控栈
docker compose -f docker-compose.monitoring.yml up -d
```

### 4.2 生产环境（K3s + Helm + ArgoCD）

```
┌─────────────────────────────────────────────────────────────────────┐
│                         K3s 集群                                     │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   Namespace: agent-prod                       │   │
│  │                                                               │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │   │
│  │  │  APISIX  │  │API(×3)   │  │RAG(×2)   │  │WS(×2)    │    │   │
│  │  │  Deploy  │  │ Deploy   │  │ Deploy   │  │ Deploy   │    │   │
│  │  │  + SVC   │  │ + SVC    │  │ + SVC    │  │ + SVC    │    │   │
│  │  │  + HPA   │  │ + HPA    │  │ + HPA    │  │ + HPA    │    │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │   │
│  │                                                               │   │
│  │  ┌──────────┐  ┌──────────┐                                  │   │
│  │  │ Worker   │  │ Frontend │  (多副本水平伸缩)                  │   │
│  │  │ Deploy   │  │ Deploy   │                                  │   │
│  │  │ + HPA    │  │ + SVC    │                                  │   │
│  │  └──────────┘  └──────────┘                                  │   │
│  │                                                               │   │
│  │  ┌──────────────────────────────────────────────────────┐    │   │
│  │  │ ConfigMap + Secrets (Sealed Secrets / External Secrets)│    │   │
│  │  └──────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────┐    ┌──────────────────────────┐      │
│  │   Namespace: data         │    │   Namespace: argocd      │      │
│  │                           │    │                          │      │
│  │  PG  │ Milvus │ Redis    │    │ agent-staging (auto)     │      │
│  │  MinIO  │ RabbitMQ       │    │ agent-production(manual) │      │
│  └──────────────────────────┘    └──────────────────────────┘      │
│                                                                     │
│  ┌──────────────────────────┐    ┌──────────────────────────┐      │
│  │   Namespace: monitoring   │    │   ArgoCD Image Updater   │      │
│  │                           │    │  (watch registry →       │      │
│  │  Prometheus + Grafana     │    │   auto update Helm vals) │      │
│  │  + Loki (optional)        │    └──────────────────────────┘      │
│  └──────────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────────┘
```

部署流程：
```bash
# 1. 安装 K3s 集群
curl -sfL https://get.k3s.io | sh -

# 2. 安装 ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# 3. Helm 部署（staging）
helm upgrade --install agent-staging deploy/helm/enterprise-agent/ \
  -f deploy/helm/enterprise-agent/values.yaml \
  -f deploy/helm/enterprise-agent/values-staging.yaml \
  --namespace agent-staging --create-namespace

# 4. Helm 部署（production）
helm upgrade --install agent-prod deploy/helm/enterprise-agent/ \
  -f deploy/helm/enterprise-agent/values.yaml \
  -f deploy/helm/enterprise-agent/values-prod.yaml \
  --namespace agent-prod --create-namespace

# 5. 验证
kubectl get pods -n agent-prod
kubectl get hpa -n agent-prod
helm list -A
```

---

## 五、设计决策与理由

### 5.1 为什么选择 APISIX 而不是 Nginx / Kong / Traefik？

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| **Nginx** | 生态成熟，性能极高 | 动态配置需 reload，插件开发成本高，限流/熔断需 OpenResty + Lua | ❌ 不选 |
| **Kong** | 插件生态丰富，企业级 | 依赖 PostgreSQL，资源开销大，对 K3s 轻量环境偏重 | ❌ 不选 |
| **Traefik** | K8s 原生，自动服务发现 | HTTP 中间件配置复杂，限流熔断粒度不够细 | ❌ 不选 |
| **APISIX** | 高性能（辐射树路由），插件热加载，standalone 模式无需 etcd，内置 prometheus/limit-count/api-breaker/jwt-auth | 社区相对较新（Apache 顶级项目 2020） | ✅ 选择 |

**决定性因素：**
- **standalone 模式**：开发环境不依赖 etcd，零额外组件即可运行完整网关功能。生产环境可切换到 etcd 模式支持动态路由
- **内置插件覆盖需求**：limit-count（限流）、api-breaker（熔断）、jwt-auth（鉴权）、prometheus（指标）——四个核心需求全是内置插件，无需开发
- **配置即代码**：`apisix.yml` 单一文件描述所有路由和插件，可以被 Git 管理，配合 ArgoCD 实现 GitOps

### 5.2 为什么选择 RabbitMQ 而不是 Kafka / Redis Streams？

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| **Kafka** | 高吞吐，日志流场景王者 | 运维复杂（ZooKeeper/KRaft），消息 TTL 不原生，适合大数据量但不适合低延迟任务调度 | ❌ 不选 |
| **Redis Streams** | 轻量，已有 Redis 基础设施 | 消费者组管理弱，无原生 DLX，持久化依赖 RDB/AOF | ❌ 不选 |
| **RabbitMQ** | 成熟稳定，原生 TTL + DLX + 优先级队列，AMQP 协议标准，管理 UI 友好 | 吞吐量低于 Kafka（但本场景足够）| ✅ 选择 |

**决定性因素：**
- **消息 TTL + 死信队列 (DLX)**：RabbitMQ 的消息 TTL 过期自动进入 DLX 是原生能力。Kafka 需要应用层实现。本项目推理任务 5 分钟超时 + DLQ 24 小时保留是核心需求
- **优先级队列**：`agent.inference.queue` 配置了 `x-max-priority: 10`，VIP 用户的消息可以优先消费
- **运维简单**：K3s 下 RabbitMQ 单节点即可满足需求（配合 Quorum Queue 可后续升级高可用）
- **管理 UI**：`:15672` 开箱即用的 Web 管理界面，开发阶段排查问题方便

### 5.3 为什么选择 K3s 而不是完整 K8s / Docker Swarm？

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| **Docker Swarm** | 简单，与 Compose 兼容 | 社区衰退，功能停滞，HPA/Ingress 弱 | ❌ 不选 |
| **完整 K8s (kubeadm/kops)** | 功能完整，生态最强 | 资源开销大（>2G 内存），运维复杂，学习曲线陡 | ❌ 不选 |
| **K3s** | 轻量（<512M 内存），单二进制，内置 Helm Controller + Traefik(可替换) + CoreDNS + Local Path Provisioner，完全兼容 K8s API | 功能裁剪（Alpha 特性默认关闭）| ✅ 选择 |

**决定性因素：**
- **资源效率**：K3s 在 512MB 内存即可运行，适合小规模生产部署和 CI 环境
- **K8s API 完全兼容**：所有 Helm Chart、HPA、Ingress、ConfigMap、Secrets 等标准 K8s 资源均可直接使用
- **内置组件丰富**：Helm Controller 使得 `helm install` 可以声明式管理；Local Path Provisioner 自动创建 PV，无需额外配置存储类
- **生产就绪**：CNCF Sandbox 项目，Rancher/SUSE 支持，社区活跃

### 5.4 为什么选择 Milvus + Chroma 双后端而不是单一向量库？

| 场景 | 后端 | 理由 |
|------|------|------|
| 本地开发 | Chroma | 零配置 `pip install chromadb`，SQLite 持久化，无需 Docker |
| 单机小规模测试 | Chroma | 10 万级向量下性能足够，运维成本为零 |
| 生产/多租户 | Milvus | Partition Key 物理隔离，MinIO 持久化，标量+向量混合过滤 |
| 远程模式 | rag-service (HTTP) | 检索逻辑完全解耦，独立扩容，api-service 无状态 |
| Milvus 故障降级 | Chroma | `vector_store_backend=auto` 时自动回退，保证可用性 |

配置切换方式：
```bash
# .env 中修改一行即可切换后端
VECTOR_STORE_BACKEND=chroma    # 本地开发
VECTOR_STORE_BACKEND=milvus    # 生产环境
VECTOR_STORE_BACKEND=remote    # 远程 RAG Service
VECTOR_STORE_BACKEND=auto      # 自动选择 (优先 Milvus，不可用时降级 Chroma)
```

### 5.5 为什么 PG Schema 使用应用层租户隔离而不是 RLS（Row-Level Security）？

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| **PG RLS** | 数据库层强制隔离，应用无法绕过 | 每条 SQL 自动注入 WHERE 条件，执行计划缓存失效，高并发下性能下降；PG 用户数 = 租户数，运维爆炸 | ❌ 不选 |
| **应用层过滤** | 性能可控，索引优化灵活，实现简单 | 依赖开发规范，SQL 漏写 tenant_id 会导致数据泄露 | ✅ 选择 + 补偿措施 |

**补偿措施：**
- 所有索引以 `(tenant_id, ...)` 开头——确保租户过滤始终走索引
- 核心查询通过 ORM/Repository 模式统一封装，降低漏写 tenant_id 的概率
- 审计日志 (audit_logs) 记录每次操作，事后可追溯

---

## 六、安全纵深防御模型

### 6.1 五层防线架构

```
                          外部请求
                             │
┌────────────────────────────┼────────────────────────────────────────────┐
│  L1: 网关层 (APISIX)                                                    │
│                                                                         │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐           │
│  │ 限流控制   │  │ 熔断保护   │  │ JWT/Key   │  │ TLS 终结   │           │
│  │20-50次/秒 │  │5失败→熔断  │  │ 鉴权       │  │ HTTPS      │           │
│  │per user   │  │30秒恢复    │  │            │  │            │           │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘           │
└────────────────────────────┬───────────────────────────────────────────┘
                             │ 仅合法请求通过
                             ▼
┌────────────────────────────────────────────────────────────────────────┐
│  L2: 输入层 (InputGuard)                                                │
│                                                                         │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐           │
│  │ 注入检测   │  │ PII 检测   │  │ 合规检查   │  │ 敏感词过滤 │           │
│  │5类模式    │  │6类个人信息 │  │5类违规内容│  │多语言     │           │
│  │置信度评分 │  │渐进验证   │  │风险评分   │  │            │           │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘           │
└────────────────────────────┬───────────────────────────────────────────┘
                             │ 安全输入
                             ▼
┌────────────────────────────────────────────────────────────────────────┐
│  L3: 编排层 (LangGraph + Agent)                                         │
│                                                                         │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐                         │
│  │ Prompt约束 │  │ Tool校验   │  │ Reflection │                         │
│  │角色/边界  │  │参数/权限  │  │自我审查   │                         │
│  │注入防护   │  │调用前拦截 │  │幻觉检测   │                         │
│  └───────────┘  └───────────┘  └───────────┘                         │
└────────────────────────────┬───────────────────────────────────────────┘
                             │ 生成回复
                             ▼
┌────────────────────────────────────────────────────────────────────────┐
│  L4: 输出层 (OutputGuard + ObserverSanitizer)                           │
│                                                                         │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐                         │
│  │ PII 泄露   │  │ 幻觉引用   │  │ 文档注入   │                         │
│  │(API Key/  │  │交叉验证   │  │清洗        │                         │
│  │ 邮箱/手机)│  │检索文档   │  │             │                         │
│  └───────────┘  └───────────┘  └───────────┘                         │
└────────────────────────────┬───────────────────────────────────────────┘
                             │ 安全输出
                             ▼
┌────────────────────────────────────────────────────────────────────────┐
│  L5: 审计层 (PG audit_logs + APISIX http-logger)                        │
│                                                                         │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐                         │
│  │ 全量操作   │  │ IP/UA     │  │ 严重级别   │                         │
│  │记录        │  │追踪       │  │分级        │                         │
│  │action/    │  │           │  │info/       │                         │
│  │resource   │  │           │  │warning/    │                         │
│  │           │  │           │  │critical    │                         │
│  └───────────┘  └───────────┘  └───────────┘                         │
└────────────────────────────────────────────────────────────────────────┘
```

### 6.2 安全能力清单

| 层级 | 能力 | 实现机制 | 成熟度 |
|------|------|---------|--------|
| L1 网关 | 速率限制 | APISIX limit-count (20-50 req/s per user) | 生产级 |
| L1 网关 | 熔断保护 | APISIX api-breaker (5 failures → 30s) | 生产级 |
| L1 网关 | API 鉴权 | APISIX key-auth + jwt-auth | 基础（需在生产路由中实际启用）|
| L1 网关 | TLS 终结 | APISIX :9443 HTTPS | 生产级 |
| L2 输入 | Prompt 注入检测 | InputGuard 5 类正则模式 | 良好 |
| L2 输入 | PII 检测与脱敏 | PiiDetector 6 种模式 + Luhn 校验 + 自动脱敏 | 生产级 |
| L2 输入 | 内容合规 | ContentComplianceChecker 5 类检测 + 风险评分 | 良好 |
| L3 编排 | Agent 护栏 | System Prompt 约束 + 角色边界 | 基础 |
| L3 编排 | 自我反思 | Reflect node 交叉验证检索文档 | 良好 |
| L4 输出 | PII 泄露预防 | OutputGuard 敏感信息模式检测 | 良好 |
| L4 输出 | 幻觉检测 | 检索文档引用交叉验证 | 良好 |
| L4 输出 | 间接注入防护 | ObserverSanitizer 中英文注入指令清洗 | 良好 |
| L5 审计 | 操作日志 | PG audit_logs + APISIX http-logger 回调 | 生产级 |

---

## 七、多租户策略

### 7.1 三层隔离方案

```
┌─────────────────────────────────────────────────────────────────┐
│  PG (关系数据)          │  Milvus (向量数据)    │  APISIX (路由) │
├─────────────────────────┼──────────────────────┼────────────────┤
│ tenant_id 作为每张逻辑表  │ Partition Key 物理隔离│ 按租户路由      │
│ 的隔离前缀               │                      │                │
│                         │                      │                │
│ 所有索引:               │ Schema:              │ /api/v1/{tenant}│
│ (tenant_id, ...)        │ tenant_id VARCHAR    │ /ws/{tenant}   │
│                         │ is_partition_key=true│                │
│ 查询:                   │                      │                │
│ WHERE tenant_id = ?     │ 检索:                │                │
│                         │ expr='tenant_id=="?"' │                │
├─────────────────────────┼──────────────────────┼────────────────┤
│ 隔离强度: ★★★★☆        │ 隔离强度: ★★★★★      │ 隔离强度: ★★★★☆│
│ 应用层过滤 + 索引保障    │ 物理层隔离 (Milvus    │ URL 路由级隔离  │
│                         │ 只扫描目标 Partition) │                │
└─────────────────────────┴──────────────────────┴────────────────┘
```

### 7.2 数据隔离策略

| 存储 | 隔离方式 | 租户 A | 租户 B | 隔离强度 |
|------|---------|--------|--------|---------|
| PostgreSQL | `WHERE tenant_id = ?` | tenant_id = 'a' | tenant_id = 'b' | 应用层（索引保障） |
| Milvus | `Partition Key` | Partition: 'a' | Partition: 'b' | 物理层 |
| MinIO | S3 Prefix | `tenant/a/...` | `tenant/b/...` | 路径级 |
| Redis | Key Prefix | `tenant:a:...` | `tenant:b:...` | 应用层 |
| RabbitMQ | Virtual Host (预留) | `/` (共享) | `/` (共享) | 未隔离（通过消息体 tenant_id 区分）|

### 7.3 权限等级模型

每个用户有 `access_levels` 数组（如 `["public", "internal"]`），每个知识库文档有 `access_level` 字段（`public` / `internal` / `confidential` / `restricted`）。

检索时的过滤逻辑：
```python
# Milvus 标量过滤
access_levels = user.access_levels  # ["public", "internal"]
expr = f'access_level in ["public", "internal"]'

# 用户 access_levels 不包含 "confidential" → 该级别的文档不会被检索到
```

权限自动升级机制：
- PII 严重级别 → 自动升级为 `restricted`
- PII 高危级别 → 自动升级为 `confidential`
- 合规拦截 → 自动升级为 `restricted`

---

## 八、弹性伸缩策略

### 8.1 各服务伸缩方案

| 服务 | 伸缩机制 | 触发指标 | 最小/最大副本 | 说明 |
|------|---------|---------|-------------|------|
| **api-service** | HPA v2 | CPU 70% + Memory 80% | 1 / 5 | HTTP 服务标准伸缩 |
| **rag-service** | HPA v2 | CPU 70% | 1 / 5 | Embedding 计算密集 |
| **agent-worker** | HPA v2 + KEDA (规划) | CPU 60% + 队列深度 > 50 | 2 / 10 | 异步消费者，弹性需求最大 |
| **ws-service** | HPA v2 | CPU 60% | 1 / 5 | 连接数驱动伸缩 |
| **apisix** | HPA v2 | CPU 70% | 1 / 5 | 网关层伸缩 |

### 8.2 KEDA 规划（替代 worker 的 CPU HPA）

当前 agent-worker 的 HPA 基于 CPU 使用率，但异步消费者的真正瓶颈是**消息积压**而不是 CPU。计划引入 KEDA (Kubernetes Event-Driven Autoscaling)：

```yaml
# 未来的 KEDA ScaledObject (替代 HPA)
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: agent-worker-scaler
spec:
  scaleTargetRef:
    name: agent-worker
  minReplicaCount: 2
  maxReplicaCount: 20
  triggers:
    - type: rabbitmq
      metadata:
        queueName: agent.inference.queue
        mode: QueueLength
        value: "50"        # 队列长度超过 50 时扩容
        activationValue: "10"  # 队列长度低于 10 时缩容到 0（或 minReplicas）
```

---

## 九、业务系统架构设计（v2.0 新增）

**定位：** 在 v0.5 云原生技术架构基础上，构建完整的客服业务管理后台，实现从"AI 对话"到"服务闭环"的业务跃迁。

---

### 9.1 业务系统总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     前端管理后台 (React + TypeScript)          │
│  ┌──────────┬──────────┬──────────┬──────────┬────────────┐ │
│  │ 仪表盘   │ 工单看板 │ 客户管理 │ 权限管理 │ 渠道配置   │ │
│  └──────────┴──────────┴──────────┴──────────┴────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │ REST API + JWT Auth
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI 业务 API 层                       │
│  ┌─────────┬─────────┬─────────┬─────────┬────────────────┐ │
│  │ auth    │ rbac    │ tickets │customers│ satisfaction   │ │
│  └─────────┴─────────┴─────────┴─────────┴────────────────┘ │
│  ┌─────────┬─────────┬─────────┬──────────────────────────┐ │
│  │notifications│dashboard│ admin (人工工作台)             │ │
│  └─────────┴─────────┴─────────┴──────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     业务数据存储 (开发:内存 / 生产:PostgreSQL)  │
│  ┌──────────┬──────────┬──────────┬────────────────────────┐ │
│  │ 工单表   │ 客户表   │ 满意度表 │ 通知表 / 用户表        │ │
│  └──────────┴──────────┴──────────┴────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

### 9.2 RBAC 权限与认证架构

**认证流程：**
```
用户登录 → bcrypt 密码校验 → JWT Token 生成 → 前端存储
后续请求 → Authorization: Bearer <token> → 后端解码 → 注入 current_user
```

**权限校验流程：**
```
请求到达 API → require_auth 提取 current_user
         → require_permissions(Permission.TICKET_MANAGE) 检查角色权限
         → 通过则执行 / 不通过则 403
```

**前后端对齐：**
- 后端：`ROLE_PERMISSIONS` 硬编码映射
- 前端：同样的映射表做按钮/菜单显隐控制
- 原则：前端权限只影响 UI，真正的安全由后端 API 守卫

---

### 9.3 工单状态机设计

```
                    ┌─────────────┐
                    │    open     │ ←────────────────┐
                    └──────┬──────┘                  │
                           │                        │
           ┌───────────────┼───────────────┐       │
           ▼               ▼               ▼       │
    ┌─────────────┐ ┌─────────────┐ ┌──────────┐  │
    │ in_progress │ │  cancelled  │ │ resolved │  │
    └──────┬──────┘ └─────────────┘ └──────────┘  │
           │                                        │
     ┌─────┼─────┐                                 │
     ▼     ▼     ▼                                 │
┌────────┐┌──────┐┌─────────┐                     │
│resolved││closed││  open   │ ────────────────────┘
└────────┘└──────┘└─────────┘
```

**设计原则：**
1. 终态（resolved / closed / cancelled）不可再 update
2. 评论与状态分离：工单关闭后仍可添加评论
3. 幂等创建：支持 `idempotency_key` 防止重复提交
4. 生产级：PostgreSQL CHECK 约束 + 乐观锁

---

### 9.4 数据仪表盘聚合策略

**实时聚合（当前实现）：**
- 会话数据：从 `SessionManager._sessions` 内存字典实时统计
- 工单数据：按 `status` / `priority` / `category` 分组计数
- 满意度：从满意度记录计算 `avg(score)` 和分布
- 延迟：< 100ms（内存计算）

**生产优化路径：**
1. **Redis 计数器**：`INCR` 实时累加请求量、人工介入数
2. **定时预计算**：每 5 分钟聚合写入 `dashboard_stats` 缓存表
3. **时序数据库**：Prometheus/ClickHouse 做历史趋势分析

---

### 9.5 人工客服工作台流程

```
用户请求转人工
       │
       ▼
┌──────────────┐
│ WAITING_HUMAN │ ← 进入 SSE 推送队列
└──────┬───────┘
       │
       ▼
客服接受转接 ───────────────────────┐
       │                           │
       ▼                           │
┌──────────────┐                   │
│  HUMAN_CHAT  │ ← 用户收到"客服已接入" │
└──────┬───────┘                   │
       │                           │
       ▼                           │
客服查看 AI 上下文摘要              │
       │                           │
       ▼                           │
客服回复用户 ◄─────────────────────┘
       │
       ▼
客服关闭服务 → 推送满意度调查
```

**AI 上下文摘要内容：**
- 转接原因（用户主动 / AI 判定 / 未解决）
- 紧急程度（基于情绪 + 问题类型）
- 已尝试方案（从对话历史提取）
- 用户画像（VIP 等级、历史工单数）
- 当前卡点（AI 无法解决的具体障碍）

---

### 9.6 跨模块联动设计

**工单创建 → 通知推送：**
```python
# tickets.py 中创建工单后
add_notification(
    type="ticket",
    level="warning",
    title="新工单创建",
    message=f"工单 {ticket.id} 已创建",
    target_roles=["super_admin", "admin"],
    link=f"/tickets/{ticket.id}"
)
```

**人工转接 → 通知推送：**
```python
# handoff 逻辑中
add_notification(
    type="handoff",
    level="info",
    title="用户请求人工服务",
    target_roles=["agent"],
    link=f"/admin/handoff/{session_id}"
)
```

**设计原则：** 通知中心提供统一入口 `add_notification()`，各业务模块调用，解耦业务逻辑与通知逻辑。

---

## 十、未来路线图

### Phase 2: 生产就绪（预计 4-6 周）

| 优先级 | 任务 | 说明 |
|--------|------|------|
| **P0** | 集成测试 + 端到端测试 | Docker Compose 启动全服务 + 核心链路 e2e |
| **P0** | APISIX JWT 鉴权实际启用 | 所有 /api/v1/* 路由强制鉴权 |
| **P0** | Alertmanager 告警通知 | Slack/邮件/钉钉 + 值班轮转 |
| **P0** | 数据库迁移 (Alembic + Helm Hook Job) | 版本化 Schema 管理 |
| **P1** | 分布式追踪 (OpenTelemetry + Jaeger) | 跨服务调用链可视化 |
| **P1** | 结构化日志 + Loki 默认启用 | JSON 格式日志 + 自动聚合 |
| **P1** | Memory Worker 独立拆分 | 消费 memory.persist.queue |
| **P1** | 测试覆盖率 10% → 60% | Mock 测试 + 集成测试补充 |
| **P1** | Cross-Encoder 重排序 | RRF 粗筛 30 → CE 精选 3 |

### Phase 3: 高可用 + 多集群（预计 8-12 周）

| 任务 | 说明 |
|------|------|
| PG 主从复制 + PgBouncer 连接池 | 读写分离 + 连接管理 |
| Redis Sentinel / Cluster | 自动故障转移 |
| RabbitMQ Quorum Queue | 节点故障下的消息安全 |
| Milvus 读写分离 | Read Replica 分担检索负载 |
| KEDA 自动伸缩器 | 替换 worker CPU HPA |
| 多 K3s 集群 + 异地容灾 | 多活/主备架构 |
| 成本优化 (GPTCache + 分级模型) | FAQ 用小模型，Technical 用大模型 |

### Phase 4: 高级特性（持续演进）

| 任务 | 说明 |
|------|------|
| 多语言支持（i18n） | 知识库 + UI 多语言 |
| 意图识别升级为 LLM-based | 替代规则引擎，准确率提升 |
| 知识图谱集成 | 实体关系增强检索 |
| 主动学习 (Active Learning) | 低置信度回答自动标记 + 人工审核 + 反馈闭环 |
| API 市场 / MCP 插件生态 | 第三方工具接入 |
| 多模态 RAG（图表/视频理解） | ColPali / Video RAG |
| 合规认证准备 | SOC2 / ISO27001 差距分析 |

---

## 十、面试速查

**Q1: 为什么拆分 rag-service 为独立微服务？**
- RAG 是 CPU 密集（Embedding 计算）+ 内存密集（向量索引加载），资源特征与 api-service 的 HTTP 请求处理不同
- 独立扩容：当检索 QPS 上升时，只扩容 rag-service（`docker compose up -d --scale rag-service=3`）而不影响 api-service
- 故障隔离：rag-service 不可用时，api-service 仍可处理 FAQ / Human 意图（RagClient 熔断返回空结果）

**Q2: Milvus Partition Key 和 `WHERE tenant_id = ?` 有什么区别？**
- `WHERE tenant_id = ?` 是应用层过滤——Milvus 先检索所有 Partition 的数据，再过滤 tenant_id 不匹配的
- Partition Key 是物理层隔离——Milvus 只扫描目标 Partition 的数据，执行计划中不涉及其他租户的数据
- 性能差异：100 租户时，Partition Key 的检索延迟约为应用层过滤的 1/10

**Q3: 为什么 RabbitMQ 的消息 TTL 设计成分层值？**
- 推理任务 (5 min)：LLM 推理可能较慢（大模型 Max Tokens → 10-30秒/轮 × 5轮），5 分钟足矣
- 记忆持久化 (1 min)：记忆写入是轻量操作（PG INSERT + embedding），1 分钟超时说明系统异常，应快速失败
- 文档索引 (10 min)：大文档的 Embedding 计算 + Milvus 批量写入较慢，10 分钟合理

**Q4: 为什么 APISIX standalone 模式而不是 etcd 模式？**
- Standalone 模式不依赖 etcd 集群，开发/单机部署零额外依赖
- 路由配置通过 `apisix.yml` 文件管理，可以被 Git + ArgoCD 管理（GitOps 友好）
- 生产环境可切换到 etcd 模式以支持 Admin API 动态路由变更
- 权衡：standalone 模式修改路由需重启容器，但配合 K8s Rolling Update 可实现零停机

**Q5: Redis 分布式锁的释放为什么用 Lua 脚本？**
- Redis 的 `DEL` 命令不校验持有者，可能误删他人的锁（client A 的锁过期 → client B 获取锁 → client A 释放锁 → client A 删除了 client B 的锁）
- Lua 脚本 `if get(KEYS[1]) == ARGV[1] then del(KEYS[1]) end` 是原子操作，保证只释放自己持有的锁
- 这是分布式锁最容易出错的点（"释放他人的锁"），Lua 脚本是最小成本的正确解法

**Q6: CI/CD 6 阶段流水线的设计理念？**
- Lint → Test → SAST → Build → Deploy-staging → Deploy-prod
- 前序失败阻断后续（`allow_failure: false`），确保只有通过完整验证的代码才能部署
- SAST 不阻断（初期）：避免安全扫描误报阻塞开发，但记录结果供人工审查
- Staging 自动部署（main 分支推送即触发），Production 手动部署（仅 tag `v1.2.3` 触发 + 手动审批）
- 完整 SDLC 门禁：任何人都不能绕过测试和安全扫描直接部署
