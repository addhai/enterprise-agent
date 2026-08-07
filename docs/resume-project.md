# 企业级智能客服系统 — 简历项目模块

> 所有数字基于实际代码统计和测试运行，无编造数据。本文档与仓库 `README.md` 保持同步。

---

## 项目背景

针对传统企业客服存在知识库检索不准、多轮对话上下文丢失、人工应答响应慢三大痛点，设计并实现了一套基于 LangGraph + RAG 的智能客服系统。系统覆盖从渠道接入、意图路由、向量检索、多轮推理到安全防护、多维评估的完整链路，并完成了微服务拆分与 K3s 云原生部署架构设计。

> **项目定位**：作为个人**简历作品集**构建，对标「阿里云 AI 助理」形态的智能客服，重点展示全栈 AI 工程能力（LangGraph + RAG + MCP + RBAC + 多租户 + 云原生部署 + 可观测）。

## 项目职责（个人贡献）

**1. 全栈架构设计与微服务拆分**

- 将单体 FastAPI 应用拆分为多个独立微服务（API / RAG / WebSocket / Agent Worker + 基础设施），每个服务独立 Dockerfile + docker-compose 编排，可按 CPU/连接数/队列深度独立扩缩容
- 设计 Helm Chart（11 个模板 + 3 个环境 values），覆盖 Deployment/Service/ConfigMap/Secret/HPA/Ingress/APISIX Gateway，支持 staging 自动部署 + production 手动审批

**2. RAG 检索系统核心开发**

- 实现混合检索器（HybridRetriever）：向量语义检索 + BM25 关键词检索 + RRF 融合，双索引架构（段落级 + 句子级），支持句子窗口上下文展开
- 设计多维离线评估体系：实现 Recall/Precision/MRR/F1 四项指标计算模块。在 6 种真实检索场景模拟测试中，最佳情况 Recall=1.0, F1=1.0，中等场景（3 条期望文档命中 2 条）Recall=0.6667, MRR=1.0（第 1 位命中）
- 实现 Chroma → Milvus 向量库迁移方案：保留 Chroma 本地降级能力，生产环境切换 Milvus 获得 Partition Key 多租户物理隔离、12 种索引类型支持、Prometheus 原生监控

**3. LangGraph 多路径工作流编排**

- 设计多节点 DAG（entry → clarify → router → faq/rag/human → reflect → reply），多种对话路径自动路由（FAQ 直达/技术排查/人工转接/FAQ 升级 RAG/RAG 转人工）
- 实现 MemoryManager 三节点记忆接入（entry 注入长期记忆上下文 → rag 提取对话历史 → reply 持久化 + 质量评估），支持 Redis 短期记忆 + PG 长期记忆双层架构

**4. 安全护栏与质量评估**

- 实现 **5 层安全护栏**：输入注入检测（正则 + LLM）→ 系统提示词约束 → Agent 工具权限检查（PermissionChecker 三层防护：工具级 + 参数级 + 审计日志）→ 输出敏感信息检测（PII + 幻觉引用交叉验证）→ 速率限制与鉴权（APISIX 层 + 租户配额）
- 实现 LLM-as-Judge 5 维对话质量评分（相关性/准确性/完整性/安全性/语气），在线抽样框架（基于 user_id hash 一致性抽样），幻觉检测模块（技术标识符交叉验证）

**5. 云原生部署体系**

- 完整基础设施配置：APISIX 网关（路由分发/限流/熔断/鉴权/Prometheus 指标）+ RabbitMQ 任务队列拓扑（4 队列 + DLQ 死信）+ PostgreSQL 9 表 Schema（租户隔离 + 对话记录 + 审计日志）+ Prometheus + Grafana 监控面板（12 面板 + 8 告警规则）
- **GitHub Actions 3 阶段流水线**：lint（ruff + oxlint）→ test（pytest 白名单覆盖 agent/mcp_tools/safety/ticket/evaluation）→ SAST（Bandit + Semgrep）→ 构建与部署（Docker Compose / Helm）

**6. 真实云 API 资源查询适配层**

- 实现阿里云 OpenAPI 只读适配层：零额外依赖（仅 `requests` 手写 RPC Signature V1 签名），覆盖 ECS / RDS / SLB 查询 + 云监控指标（CPU / 内存）
- 设计 `CloudProvider` 抽象 + `FallbackProvider`：有 AK/SK 直连真实云，无密钥（或真实查空）自动回退样本数据，`source` 标记区分 `aliyun` / `aliyun+sample` / `sample` 三档，demo 不空且真实代码全保留
- 对话中实时操作端到端实测：经 WebSocket 发起「查资源 / 开工单」，资源工具返回真实/样本数据、工单真实落库（跨进程可查），验证 MCP 工具由 LangChain 原生函数调用真正执行（修复了早期 ReAct 文本格式与 tool_calls 机制冲突导致工具架空的缺陷）

**7. 引用可溯源与知识库命中验证**

- 针对智能客服"回复是否有据可依"的可信度问题，实现**引用气泡（citations）全链路**：AI 回复下方出现"引用知识片段 N"可展开气泡，对标阿里云智能客服坐席引用
- 后端协议层（`protocol.py`）修正空列表挂字段；检索节点（`nodes.py`）补检 `retriever.search` 填结构化 `retrieved_docs`；路由层（`routes.py`）规整并兜底 score 来源，三层缺一不可
- 前端 `App.tsx` 定义 `ChatCitation` 接口 + `details/summary` 气泡渲染，`loadSession` 从 `metadata.citations` 恢复，刷新 / 重连不丢引用
- 知识库命中测试做精：AdminDashboard 加"采用 / 低于阈值"徽章 + 文档标题 + 内容折叠，每条召回的质量直观可见

**8. 多租户隔离与 RBAC 权限**

- SQL 级 + 向量级双重隔离：`tenant_id` 由后端从调用上下文强制注入，LLM 无法跨租户读取
- P0 加固：空 tenant 文档默认归 default 租户，堵住"漏打 tenant 的文档对所有租户可见"后门；`add_documents` 与过滤端统一空 tenant 归一化，避免检索静默过滤掉合法文档
- RBAC 4 角色（admin / agent / viewer / user）+ 权限点 + 依赖注入 + REST 管理端点 + seed 用户，覆盖工具级 / 参数级 / 审计三层防护

**9. JWT 无状态鉴权**

- 零依赖 HS256（RFC 7519）实现 access token，替代进程内 token 字典
- 无状态设计使鉴权支持多副本 / 多进程部署（任意副本独立验签，无需共享内存），重启不失效，契合容器化多副本形态

## 项目成果

**代码规模：**
- 核心业务代码 **14,707 行** Python（90 个模块，24 个子包）
- 部署配置 **2,471 行**（30 个 YAML/SQL/JSON 文件）
- 基础设施配置：3 个 Dockerfile + 3 个 docker-compose + 11 个 Helm 模板 + 5 个运维脚本

**测试统计：**
- CI 采用白名单策略（仅跑确定能过的核心目录：`test_agent` / `test_mcp_tools` / `test_safety` / `test_ticket` / `test_evaluation`），**313 个测试通过 + 1 跳过，CI 稳定可绿**
- 覆盖模块：agent 工具调用 / MCP 工具 / 安全护栏 / 工单 / 评估追踪器 等核心链路
- RAG 离线评估 4 项指标（Recall / Precision / MRR / F1）全部通过
- 安全护栏测试全部通过（输入注入识别 / 已知攻击模式 / 特殊字符清洗 / 正常内容保留）
- 真实覆盖率约 **17%**（基线，作为作品集以「CI 绿 + demo 一键可跑」为质量目标，不硬刷覆盖率）

**RAG 检索质量（评估模块模拟测试）：**
| 场景 | Recall | Precision | MRR | F1 |
|------|--------|-----------|-----|-----|
| 5 条期望文档全命中 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 3 条期望全命中（top-5） | 1.0000 | 0.6000 | 1.0000 | 0.7500 |
| 3 条期望命中 2 条 | 0.6667 | 0.4000 | 1.0000 | 0.5000 |
| 6 场景平均值 | 0.6528 | 0.4333 | 0.8333 | 0.5073 |

**架构特点：**
- 多后端向量库支持（Chroma/Milvus/Remote HTTP），通过配置一键切换，自动降级
- 分布式锁（Redis Lua 脚本原子释放）：索引更新锁 / 记忆去重锁 / 配额扣减锁
- 微服务间通信：同步 HTTP（API↔RAG）+ 异步 MQ（API→Worker），支持 KEDA 队列深度自动伸缩

## 可演示性（端到端已实测 ✅）

这是本作品集**最重要的交付验证**——不是只有代码，而是真实能跑起来、能对话：

- **单进程即可跑通完整 demo**：`uvicorn src.api.server:app` 在根路径用 `StaticFiles` 同源托管前端 `static/` 目录，一个进程同时提供前端页面 + REST API + **WebSocket 聊天**，无需前端单独起服务或配代理。
- **聊天主链路为 WebSocket `/ws/chat`**：前端浮动智能客服组件通过该端点与后端 LangGraph 工作流实时流式对话。AI 回复由真实大模型（通义千问）生成，**非 mock**。
- **实测验证**：`/api/v1/health` 返回 `{"status":"ok"}`；WebSocket 实测可流式返回贴合产品人设的回复（如询问产品功能得到详细答案），未知问题走护栏优雅降级（建议转人工）。
- **引用气泡实测**：登录 → WebSocket 发问，ECS 类问题命中《ECS 远程连接排障 SOP》并透出"引用知识片段 1"可展开气泡；纯价格类问题 0 命中、不展示引用（正确不误引）。
- **实时操作链路实测（端到端）**：对话中「查云资源 / 开工单」经 WebSocket 端到端验证通过——资源工具返回代码内真实样本数据（含公网 IP、RDS 连接地址等唯一标记），工单真实落库（SQLite/PG，跨进程可查），确认工具由 LangChain 原生函数调用真正执行，而非模型文本编造。
- **最轻量启动路径（克隆即可演示）**：配置 `.env`（填 `DASHSCOPE_API_KEY`）→ `cd frontend && npm run build`（产物自动输出到 `static/`）→ `set VECTOR_STORE_BACKEND=chroma && uvicorn src.api.server:app` → 打开 `http://localhost:8000` 即可对话。
- 完整 12 服务云原生栈（APISIX + 业务服务 + PG/Milvus/Redis/RabbitMQ/MinIO + 监控）亦可经 Docker Compose / K3s + Helm 部署。

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.11+ |
| 编排 | LangGraph（多节点 DAG） |
| Agent | LangChain (create_agent, ReAct) |
| LLM | 阿里百炼 Qwen-Plus / Qwen-Max（兼容 OpenAI 格式） |
| Embedding | text-embedding-v4 (1024 维) |
| 向量库 | Chroma（开发）/ Milvus 2.5（生产） |
| 服务 | FastAPI + uvicorn + WebSocket |
| 网关 | Apache APISIX 3.x（限流/熔断/Prometheus） |
| 消息队列 | RabbitMQ 4.0（Topic Exchange + DLX 死信） |
| 存储 | PostgreSQL 16 + Redis 7 + MinIO |
| 前端 | React + TypeScript + Vite |
| 云资源查询 | 阿里云 OpenAPI（ECS/RDS/SLB/Redis 只读 + 云监控，手写 RPC 签名零依赖） |
| 鉴权 | JWT（HS256 零依赖，无状态，支持多副本 / 多进程部署） |
| 部署 | Docker Compose **多副本**（`--scale`）+ K3s + Helm（生产） |
| CI/CD | **GitHub Actions**（3 阶段：lint / test / SAST） |
| 监控 | Prometheus + Grafana（12 面板 + 8 告警） |
| 代码质量 | Ruff + Bandit + Semgrep |

## 相关技能标签

`LangGraph` `RAG` `向量检索` `混合检索` `BM25` `RRF` `Milvus` `Chroma` `Recall@K` `MRR` `LLM-as-Judge` `幻觉检测` `微服务` `Docker` `K3s` `Helm` `APISIX` `RabbitMQ` `PostgreSQL` `Redis` `分布式锁` `GitHub Actions` `Prometheus` `Grafana` `安全护栏` `多租户` `RBAC` `FastAPI` `WebSocket` `MCP`
