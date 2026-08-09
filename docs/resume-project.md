# 企业级智能客服系统 — 简历项目模块

> 所有数字基于实际代码统计和测试运行，无编造数据。本文档与仓库 `README.md` 保持同步，可作为简历「项目经历」栏的叙事母本与面试准备底稿。

---

## 🎯 招聘官 30 秒速览

- **项目是什么**：对标「阿里云 AI 助理」形态的**企业级智能客服 AI Agent**，个人全栈作品集，**production-grade（生产级），不是 demo**。
- **一句话价值**：用 **LangGraph + RAG + MCP** 端到端解决企业客服三大痛点 —— 知识库检索不准、多轮对话丢上下文、人工响应慢，并做到生产级工程落地（多租户、RBAC、安全护栏、云原生部署、可观测）。
- **量化亮点**：核心代码 **14,707 行 Python** · **856 测试全绿 / 覆盖率 48.83%** · **38 个标准化 MCP 工具** · 多租户隔离 + 多副本扩展**均有自动化测试/脚本证据**。
- **展示的能力层级**：全栈 AI 工程（编排 + 检索 + 工具 + 护栏）+ 云原生部署（Docker / K8s / Helm / APISIX）+ 工程化质量（CI / SAST / 可观测）。
- **最硬的证据**：单进程即可跑起真实对话 demo；多租户越权防护进 CI 长期复跑；无状态多副本实测共享存储一致；demo GIF 由真实对话脚本化生成，非截图伪造。

---

## 项目背景

传统企业客服存在三大痛点：**知识库检索不准、多轮对话上下文丢失、人工应答响应慢**。本项目设计并实现了一套基于 LangGraph + RAG 的智能客服系统，覆盖从渠道接入、意图路由、向量检索、多轮推理到安全防护、多维评估的完整链路，并完成微服务拆分与 K3s 云原生部署架构设计。

> **项目定位**：作为个人**简历作品集**构建，对标「阿里云 AI 助理」形态的智能客服，重点展示全栈 AI 工程能力（LangGraph + RAG + MCP + RBAC + 多租户 + 云原生部署 + 可观测）。

## 项目职责（个人贡献）

> 以下均为个人独立完成的建设工作，按"做了什么 → 达到什么效果"组织，便于面试时展开。

**1. 全栈架构设计与微服务拆分**

- 主导从单体到微服务的演进：将单体 FastAPI 拆分为 **API / RAG / WebSocket / Agent Worker** 4 个独立服务 + 基础设施，每个服务独立 Dockerfile + docker-compose 编排，可按 CPU / 连接数 / 队列深度独立扩缩容。
- 产出 Helm Chart（**11 个模板 + 3 个环境 values**），覆盖 Deployment/Service/ConfigMap/Secret/HPA/Ingress/APISIX Gateway，支持 staging 自动部署 + production 手动审批。

**2. RAG 检索系统核心开发**

- 实现 **HybridRetriever**：向量语义检索 + BM25 关键词检索 + RRF 融合，双索引架构（段落级 + 句子级）+ 句子窗口上下文展开，命中质量肉眼可验。
- 建立离线评估体系（Recall / Precision / MRR / F1）：6 种场景模拟测试中最佳 **Recall=1.0, F1=1.0**，中等场景（3 条期望命中 2 条）**MRR=1.0（第 1 位命中）**。
- 设计 **Chroma → Milvus 迁移方案**：保留 Chroma 本地降级，生产切 Milvus 获 Partition Key 多租户物理隔离、12 种索引类型、Prometheus 原生监控。

**3. LangGraph 多路径工作流编排**

- 设计 **7 节点 DAG**（entry → clarify → router → faq/rag/human → reflect → reply），多路径自动路由（FAQ 直达 / 技术排查 / 人工转接 / FAQ 升级 RAG / RAG 转人工）。
- 实现 **MemoryManager 三节点记忆接入**（entry 注入长期记忆 → rag 提取对话历史 → reply 持久化 + 质量评估），Redis 短期记忆 + PG 长期记忆双层架构。

**4. 安全护栏与质量评估**

- 实现 **5 层安全护栏**：输入注入检测（正则 + LLM）→ 系统提示词约束 → Agent 工具权限检查（工具级 + 参数级 + 审计日志）→ 输出敏感信息检测（PII + 幻觉引用交叉验证）→ 速率限制与鉴权。
- 实现 **LLM-as-Judge 5 维对话质量评分**（相关性 / 准确性 / 完整性 / 安全性 / 语气）+ 基于 user_id hash 一致性抽样 + 幻觉检测模块（技术标识符交叉验证）。

**5. 云原生部署体系**

- 完整基础设施：APISIX 网关（路由 / 限流 / 熔断 / 鉴权 / Prometheus 指标）+ RabbitMQ 任务队列（4 队列 + DLQ 死信）+ PostgreSQL 9 表 Schema + Prometheus / Grafana（12 面板 + 8 告警）。
- **GitHub Actions 3 阶段流水线**：ruff lint/format → pytest 全量 + 覆盖率门禁 40% → SAST（Bandit 中高危阻断 + Semgrep ERROR 级）。靠 `requires_llm` / `integration` marker 自动跳过需真实密钥用例，**无 Key 即可稳定转绿**。

**6. 真实云 API 资源查询适配层**

- 实现阿里云 OpenAPI **只读适配层**：零额外依赖（仅 `requests` 手写 RPC Signature V1 签名），覆盖 ECS / RDS / SLB 查询 + 云监控指标（CPU / 内存）。
- 设计 `CloudProvider` 抽象 + `FallbackProvider`：有 AK/SK 直连真实云，无密钥（或真实查空）自动回退样本，`source` 标记区分 `aliyun` / `aliyun+sample` / `sample` 三档，demo 不空且真实代码全保留。
- **端到端实测**：经 WebSocket 发「查资源 / 开工单」，资源工具返回真实/样本数据、工单真实落库（跨进程可查），确认 MCP 工具由 LangChain 原生函数调用真正执行（修复了早期 ReAct 文本格式与 `tool_calls` 冲突导致工具架空的缺陷）。

**7. 引用可溯源与知识库命中验证**

- 实现**引用气泡（citations）全链路**：AI 回复下方出现"引用知识片段 N"可展开气泡，对标阿里云智能客服坐席引用；后端 `protocol.py` / `nodes.py` / `routes.py` 三层修正 + 前端气泡渲染，刷新 / 重连不丢引用。
- AdminDashboard 加"采用 / 低于阈值"徽章 + 文档标题 + 内容折叠，每条召回的质量直观可见。

**8. 多租户隔离与 RBAC 权限**

- **SQL 级 + 向量级双重隔离**：`tenant_id` 由后端从调用上下文强制注入，LLM 无法跨租户读取。
- **P0 加固**：空 tenant 文档默认归 default 租户，堵住"漏打 tenant 的文档对所有租户可见"后门；`add_documents` 与过滤端统一空 tenant 归一化。
- RBAC **4 角色**（admin / agent / viewer / user）+ 权限点 + 依赖注入 + REST 管理端点 + seed 用户；WebSocket `/ws/chat` 租户隔离与越权防护由 `tests/test_websocket/test_ws_tenant_isolation.py` 覆盖（匿名按连接隔离、登录派生真实租户、客户端注入 tenant 被忽略、伪造 token 降级匿名，4 点全绿）。

**9. JWT 无状态鉴权**

- 零依赖 **HS256（RFC 7519）** 实现 access token，替代进程内 token 字典。
- 无状态设计使鉴权支持**多副本 / 多进程部署**（任意副本独立验签、重启不失效），契合容器化多副本形态；`scripts/verify_multireplica.py` 实测：单机起 2 个独立 uvicorn 实例（等价 2 个容器副本），各自 health OK、各自独立 accept WebSocket、副本 A 创建的工单副本 B 用同一 token 能读到（共享存储一致，退出码 0）。

## 项目成果

**代码规模：**
- 核心业务代码 **14,707 行** Python（90 个模块，24 个子包）
- 部署配置 **2,471 行**（30 个 YAML/SQL/JSON 文件）
- 基础设施配置：4 个 Dockerfile（legacy + api / worker / rag）+ 3 个 docker-compose + 11 个 Helm 模板 + 5 个运维脚本

**测试统计（CI 裸环境真实运行：无 API Key / 无 .env）：**
- **856 个测试通过 + 17 跳过**（全量 `tests/`，`-m "not integration"`），覆盖 agent / MCP 工具 / 安全护栏 / 工单 / 评估 / 多租户 WS 隔离 / API 接线守卫等
- 覆盖率 **48.83%**（门禁 40%，`--cov-fail-under=40` 同时固化进 pytest 与 CI，本地 `make test` 与 CI 行为一致）
- 应用接线守卫（`tests/test_api/test_app_wiring.py`）：19 个 router 模块逐个导入探测 + 鉴权关键路由存在性断言，任一 router 静默消失立即红灯（曾因 `auth` 路由在 Python 3.11 因前向引用 `NameError` 被静默吞掉导致 `/auth/*` 404，由此守卫测试堵住同类缺陷）
- RAG 离线评估 4 项指标（Recall / Precision / MRR / F1）全部通过
- 安全护栏测试全部通过（输入注入识别 / 已知攻击模式 / 特殊字符清洗 / 正常内容保留）

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
- **实测验证**：`/api/v1/health` 返回 `{"status":"ok"}`；WebSocket 实测可流式返回贴合产品人设的回复，未知问题走护栏优雅降级（建议转人工）。
- **引用气泡实测**：登录 → WebSocket 发问，ECS 类问题命中《ECS 远程连接排障 SOP》并透出"引用知识片段 1"可展开气泡；纯价格类问题 0 命中、不展示引用（正确不误引）。
- **实时操作链路实测（端到端）**：对话中「查云资源 / 开工单」经 WebSocket 端到端验证通过——资源工具返回代码内真实样本数据（含公网 IP、RDS 连接地址等唯一标记），工单真实落库（SQLite/PG，跨进程可查），确认工具由 LangChain 原生函数调用真正执行，而非模型文本编造。
- **最轻量启动路径（克隆即可演示）**：配置 `.env`（填 `OPENAI_API_KEY`，配 DashScope 兼容 `OPENAI_API_BASE`）→ `cd frontend && npm run build`（产物自动输出到 `static/`）→ `set VECTOR_STORE_BACKEND=chroma && uvicorn src.api.server:app` → 打开 `http://localhost:8000` 即可对话。
- **多租户 RBAC 隔离（可复现）**：`pytest tests/test_websocket/test_ws_tenant_isolation.py -v` 进 CI 长期复跑，证明 A 租户数据 B 租户不可见、客户端注入 `tenant_id` 越权被服务端忽略。
- **云原生多副本水平扩展（可复现）**：`python scripts/verify_multireplica.py` 起 2 个无状态副本实测共享存储一致性（副本 A 工单副本 B 可读），等价于 `docker compose up --scale api-service=3` 的副本语义。
- **基础设施配置进 CI 门禁（可复现）**：`infra-validate` job 每次流水线校验 4 个 compose 文件、真实 build api/worker/rag 三个生产镜像、`helm lint` + default/staging/prod 三套 values 渲染。该门禁上线即查出 `values-prod.yaml` 渲染 nil pointer（`apisix.service` 结构缺失，仅 `apisix.enabled=true` 时触发，等同生产 `helm install` 会当场失败），已修复。
- **能力边界（面试可如实回答）**：单进程 demo 与双副本扩展已本机实测，Compose/Dockerfile/Helm 由 CI 逐次校验并真实构建镜像；完整 12 服务栈（APISIX + PG/Milvus/Redis/RabbitMQ/MinIO + 监控）的长时间联跑尚未在本机完成。

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.11+（部署 Dockerfile 与 CI 均锁定 3.11，本地开发对齐以消除「本地绿 CI 红」） |
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
| CI/CD | **GitHub Actions**（4 个并行 job：pytest + 覆盖率门禁 · SAST · 前端 tsc/vite build · 基础设施 compose+镜像+Helm 校验） |
| 监控 | Prometheus + Grafana（12 面板 + 8 告警） |
| 代码质量 | Ruff（line-length 88，target py311）+ Bandit + Semgrep |

## 相关技能标签

`LangGraph` `RAG` `向量检索` `混合检索` `BM25` `RRF` `Milvus` `Chroma` `Recall@K` `MRR` `LLM-as-Judge` `幻觉检测` `微服务` `Docker` `K3s` `Helm` `APISIX` `RabbitMQ` `PostgreSQL` `Redis` `分布式锁` `GitHub Actions` `Prometheus` `Grafana` `安全护栏` `多租户` `RBAC` `FastAPI` `WebSocket` `MCP`

---

## 📋 简历「项目经历」栏可直接用的精简版（约 120 字）

> **企业级智能客服 AI Agent**（个人作品集，production-grade）｜对标阿里云 AI 助理
> 用 LangGraph + RAG + MCP 搭建智能客服：HybridRetriever 混合检索、7 节点多路径编排、5 层安全护栏、多租户强隔离 + RBAC、JWT 无状态多副本部署。前端单进程即可跑真实对话 demo，38 个 MCP 工具真实落库；GitHub Actions 4 job 流水线（测试 / SAST / 前端构建 / 基础设施校验），856 测试全绿、覆盖率 48.83%。
