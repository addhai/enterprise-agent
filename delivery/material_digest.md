# AICoding 架构设计 · 资料摘要

> 本文档做一件事：**精读主理人转交的全部原始资料，逐份、逐章节做出摘要**——后面任何人拿到这份摘要，都能通过章节号快速定位回原始文件的对应位置。

> 上游输入：主理人转交的全部原始资料（md / yaml / compose 配置，均在工作区 `C:\Users\hai\enterprise-agent`）；
> 产出者：`knowledge-ingest-engineer`（知识摄入工程师 - 闻资料），经 G1 校验与人工审核通过后交付。

---

## 0. 元信息

```yaml
标题: enterprise-agent - 资料摘要 v0.1
版本: v0.1
状态: Draft
创建日期: 2026-08-11
整理人: knowledge-ingest-engineer（闻资料）
审核人:
  - team-lead（主理人，待 G1 人工审核）

原始资料清单:
  - HANDOFF.md: 交接文档，项目当前状态最权威来源（2026-08-11 晚间版）
  - README.md: 项目门面说明（定位/技术栈/CI/能力边界）
  - docs/需求文档-模仿阿里云AI助理智能体.md: 开发需求文档 v1.0（含四条硬性定位）
  - docs/cloud-native-architecture.md: 云原生架构升级方案（2026-07-15）
  - docs/resume-project.md: 简历项目叙事母本
  - docs/多租户-RBAC隔离核查.md: 多租户/RBAC 静态+运行态核查报告（2026-08-07）
  - docs/TECH_SHARING_2026.md: 5 期技术分享大纲
  - docs/api.md: REST + WebSocket 接口协议文档
  - docs/INDEX.md: 文档导航索引
  - docs/CODE_STYLE.md: 代码规范速查卡
  - docs/PR_REVIEW_CHECKLIST.md: PR 评审清单
  - docs/deployment/runbook.md: 部署与验证 Runbook（三道缝验证操作手册）
  - overview.md: 团队技术提升四阶段落地总览（⚠️ 时效性存疑，见 §2/D13）
  - 改动方案.md: 2026-07-20 改动方案（⚠️ 部分已过时）
  - 团队技术提升方案.md: 团队协作 8 周路线图（⚠️ HANDOFF 明确标注对本项目不适用）
  - docs-update-1.md ~ docs-update-5.md: 历史深度工作笔记（按需查阅资料库，部分已过时）
  - POSTGRES_LOCAL_SETUP_GUIDE.md: 本机 Postgres Docker 验证指南
  - capability-contract.yaml: 扣款能力契约样例（payments 域）
  - capability-ticket.yaml: 企业级 MCP 38 工具能力契约
  - data/docs/*.md: 13 篇 CloudSync 虚拟产品文档（RAG 业务语料，非项目背景资料）
  - docker-compose.yml + deploy/ + docker/: 12 服务部署编排现状
```

| 版本 | 日期 | 作者 | 变更内容 |
| --- | --- | --- | --- |
| v0.1 | 2026-08-11 | knowledge-ingest-engineer | 初稿（精读 D1~D5 核心五份；其余列清单+角色说明） |

---

## 1. 资料清单

> 列出全部原始资料，每份标注解析状态。解析失败或跳过的必须注明原因。

| 编号 | 文件名 | 类型 | 来源 | 解析状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| D1 | `HANDOFF.md` | md | 项目仓库根（用户/历史会话沉淀） | 已解析（精读） | 2026-08-11 晚间版，当前状态最权威来源 |
| D2 | `README.md` | md | 项目仓库根 | 已解析（精读） | 项目门面；能力边界一节部分滞后于 D1 |
| D3 | `docs/需求文档-模仿阿里云AI助理智能体.md` | md | docs/（八弟与拾一协作） | 已解析（精读） | v1.0 草稿，2026-08-06，含四条硬性定位 |
| D4 | `docs/cloud-native-architecture.md` | md | docs/ | 已解析（精读） | 2026-07-15，部署演进设计 |
| D5 | `docs/resume-project.md` | md | docs/ | 已解析（精读） | 简历叙事母本，数字与 README 同步 |
| D6 | `docs/多租户-RBAC隔离核查.md` | md | docs/ | 已解析 | 2026-08-07 核查报告，行号基于当日代码 |
| D7 | `docs/TECH_SHARING_2026.md` | md | docs/ | 已解析 | 5 期分享大纲，面向团队带练场景 |
| D8 | `docs/api.md` | md | docs/ | 已解析 | REST + WS 双通道接口协议 |
| D9 | `docs/INDEX.md` | md | docs/ | 已解析 | 文档导航；声明 docs-update-* 为历史笔记 |
| D10 | `docs/CODE_STYLE.md` | md | docs/ | 已解析 | 规范速查，配合 pyproject.toml ruff 配置 |
| D11 | `docs/PR_REVIEW_CHECKLIST.md` | md | docs/ | 已解析 | 7 大类评审清单 + SAST 门禁规范 |
| D12 | `docs/deployment/runbook.md` | md | docs/deployment/ | 已解析 | 三道缝验证操作手册；验证清单滞后于 D1 |
| D13 | `overview.md` | md | 仓库根 | 已解析 | ⚠️ 部分已过时（fail_under 35→现状 40/48.83%，见 §3 X1） |
| D14 | `改动方案.md` | md | 仓库根 | 已解析 | ⚠️ 部分已过时（前端 3 页面 ⏳、SSE 描述等，见 §3 X3/X7） |
| D15 | `团队技术提升方案.md` | md | 仓库根 | 已解析 | ⚠️ D1 §0 明确标注"对本项目不适用"（团队协作 8 周路线图/覆盖率 80% KPI） |
| D16 | `docs-update-1.md ~ docs-update-5.md` | md ×5 | 仓库根 | 跳过精读（有依据） | D9 将其定位为"按需查阅的资料库"，主理人指令确认部分已过时；按指令只列角色（D16 在 §2 以组合条目说明） |
| D17 | `POSTGRES_LOCAL_SETUP_GUIDE.md` | md | 仓库根 | 已解析 | 本机 PG 验证手把手指南，已知缺口已修复 |
| D18 | `capability-contract.yaml` | yaml | 仓库根 | 已解析 | payments 扣款能力契约样例（契约规范示例，非本系统接口） |
| D19 | `capability-ticket.yaml` | yaml | 仓库根 | 已解析 | 本系统 38 个 MCP 工具能力契约 v2.0.0 |
| D20 | `data/docs/*.md`（13 篇） | md ×13 | data/docs/ | 跳过逐篇精读（有依据） | RAG 业务语料（虚拟产品 CloudSync 知识库），非项目背景资料；主理人指令确认只需说明角色/数量/入库状态 |
| D21 | `docker-compose.yml` + `deploy/` + `docker/` | yaml/配置 | 仓库根 | 已解析（要点提取） | 12 服务编排现状，已含 08-10/11 未提交修复 |
| D22 | `docs/agent-project-roadmap.html` | html | docs/ | 跳过（有依据） | 未列入主理人转交清单，为路线图展示页，非现状事实来源 |

**类型枚举**：`md` / `yaml` / `html` / `compose 配置`（本批资料无 docx/pdf/pptx/xlsx）

**资料时效性总纲（重要）**：以 D1（HANDOFF.md，2026-08-11 晚间版）为现状最高权威；D13/D14/D15/D16 为规划或历史文档，凡与 D1/代码现状冲突一律以 D1 与代码现状为准（D1 §0 明确警告："看代码现状为准，别据旧文档找不存在的缺口"）。

---

## 2. 资料内容摘要

> 逐份文档按自身章节结构做摘要。每条摘要标注章节号（`D编号，§章节`），后面任何人想核实某个点，直接定位回原文对应位置即可。

### D1：`HANDOFF.md`

> 项目交接文档，含两条任务线（三道缝 Docker 实跑验证 + RAG 真实文档灌入）的完整现状、卡点、未提交清单与踩坑记录 — 来源：仓库根，2026-08-11 晚间版

| 章节 | 内容摘要 |
| --- | --- |
| §0 一句话背景 | 项目为**个人简历作品集**（用户 hai/拾一，大三 AI 应用开发方向），非团队项目；对标「阿里云 AI 助理」智能客服形态；按生产级标准开发（真实云 API、多租户+RBAC、可观测、云原生）。技术栈 Python FastAPI + LangGraph + RAG + MCP，前端 React/TypeScript。仓库 github.com/addhai/enterprise-agent（master） |
| §0 安全红线 | 真实密钥（LLM key / 阿里云 AK / JWT secret）永不上公网；任何挂公网且携带真实 key 的方案一律不做；对外只用本地 docker/localhost 或可吊销 demo 子 key。此红线优先于展示力诉求 |
| §0 误导警告 | `团队技术提升方案.md`（8 周路线图、覆盖率 80%）对本项目不适用；`overview.md`/`改动方案.md` 等部分已过时（"前端 3 个未完成页面"早已落地），以代码现状为准 |
| §1 三道缝定义 | 第一道缝=全栈真跑（compose 拉起 12 服务、apisix 网关工单链路）⏳卡 milvus；第二道缝=Grafana 真渲染 ✅已实跑通过（`Grafana render VERIFIED`，18 面板中 12 真出数据，6 个为流量门控空属正常）；第三道缝=云资源真实性 ⏸️按安全红线有意跳过 |
| §1 授权边界 | 用户睡前授权自主推进修复；所有修复均未 git 提交 |
| §2 已完成（未提交） | 七项修复：①Docker Desktop 全局代理注入容器（新增 `docker/no_proxy.env` 给 12 服务注入 NO_PROXY，头号系统性坑）；②slim 镜像无 curl 改 urllib healthcheck；③RabbitMQ 4.0 boot 死结（删 mqtt 配置/load_definitions，改代码幂等声明拓扑 `src/broker/topology.py`）；④compose 端口+副本冲突（api-service 删主机端口走 9080 网关）；⑤minio 镜像 tag 404（改有效 tag RELEASE.2025-07-23T15-54-02Z）；⑥ws-service `target: production` 不存在（已删）；⑦验证脚本加固（残留容器清理、面板空值区分） |
| §3 当前卡点 | 全栈 12 服务联跑卡 `milvus-standalone is unhealthy`：milvus v2.5.9 standalone（内嵌 etcd），compose 内存限制仅 2G（官方推荐 4G 起步），启动约 3 分钟后 /healthz 仍 HTTP 500，日志无 ERROR 只有 coord 注册 WARN。高度怀疑方向（未证实）：内存偏紧或内嵌 etcd 启动超 healthcheck 窗口；`docker stats` 实锤数据因代理中断未拿到。备选：调大内存/放宽 healthcheck/换 chroma fallback |
| §4 下一步计划 | ①诊断修 milvus（第一优先）；②重跑 `scripts/verify_fullstack.py`；③提交本轮修复（绝不 `git add .`，push 由用户本机做）；④补全过时文档；⑤（可选）第三道缝替代证明（`aliyun_demo_fallback` 标记已在 /api/v1/health 暴露） |
| §5 未提交清单 | 已修改未提交：`deploy/rabbitmq/rabbitmq.conf`、`docker-compose.yml`、`scripts/verify_fullstack.py`、`scripts/verify_monitoring.py`、`src/worker/consumer.py`；未跟踪：`docker/no_proxy.env`、`src/broker/`、`wheels/`（184 个离线轮子，建议 gitignore）、`scripts/proxy_relay.py`（用途待确认，提交前问用户）；垃圾勿提交：`install.log`、`coverage.xml`、`.coverage`、`.trae/`、`.workbuddy/` |
| §5 Git 铁律 | 绝不 `git add .`/`-A`，只 add 指定路径；push 不替用户做（沙箱无代理出口，本机 git 配了 127.0.0.1:7890 代理） |
| §6 踩坑清单 | D1~D10 Docker 类坑（代理注入/残留容器复活/daemon 500 假象/slim 无 curl/RabbitMQ 4.0 严格 schema/端口副本冲突/tag 404/Dockerfile stage 不存在/milvus 内存/Clash 假连接）；工程类坑 1/4/9/17/28/29/30/35/43；工作流坑 P1/P2（Windows 路径、后台任务输出读报告文件） |
| §7 关键文件清单 | 9 个关键文件状态表：5 个✏️改未提交、2 个🆕未提交、`verify_monitoring_report.txt` ✅已生成（第 22 行 VERIFIED）、`POSTGRES_LOCAL_SETUP_GUIDE.md` ✅已推送 |
| §9.1 RAG 任务目标 | 让对话真命中知识库：灌入真实文档，验收标准为对 CloudSync 技术问法回复必须含文档专属事实（`410 Gone`/`2025-12-31`/分页 limit 上限 100 等），不转人工不搪塞 |
| §9.2 RAG 已完成 | ①13 篇 CloudSync 文档经 `scripts/ingest_real_docs.py` 灌入 KB `KBS-CD0480`，**13 篇/205 切片/indexed**，tenant=default；②修复三个真 bug（均未提交）：Bug A `src/agent/tools.py` 元组解包崩溃（retriever.search() 已剥分数返回 Document 列表，`for doc, _ in results` 必抛 TypeError 被吞→转人工，**头号根因**）；Bug B 召回太少+截断太狠（top_k=3→5，截断 500→1200）；Bug C `structure_detect.py` 结构提示标记非幂等堆叠（已加 `_strip_existing_hints()`）；③检索层经 `scripts/probe4.py` 直连实测证明是好的（召回含"2025-12-31 下线/410 Gone"原文） |
| §9.3 RAG 当前卡点 | 三处代码已改好但**未做端到端复验**：probe5.py 跑时百炼 embedding API 报 Connection error（Clash 代理波动，非代码问题）；跑着的 8000 端口 server 可能仍加载旧 tools.py；8021 端口验证实例是 Bug B/C 修复前验证的（当时"不再转人工但答不上来"），修完后未复验 |
| §9.4 RAG 下一步 | ①确认代理可用后跑 probe5.py（离线验检索+截断）；②另起 8021 实例（VECTOR_STORE_BACKEND=chroma）跑 `ws_rag_verify.py` 验对话命中；③达标后只 add 指定文件提交、push 交用户；④可选增强（按 source 聚合相邻 chunk、chunk_size 512→768），先不过度优化 |
| §9.5 RAG 坑 R1~R6 | R1 对话不命中先直连 retriever 排查别怪向量库；R2 `[Contains code blocks]` 是追加标记非内容丢失；R3 WS 流式帧字段是 text/delta 不是 content；R4 百炼 embedding 依赖代理偶发 Connection error；R5 两套 pyc+长驻进程改码不生效须重启实例；R6 top_k/截断是隐形答案杀手 |
| §9.7 一句话交接 | 语料已灌（205 切片）、检索层已证好、三 bug 已修未提交未复验；下一步 probe5 + 8021 实例 ws_rag_verify 两步 |

### D2：`README.md`

> 项目门面文档：定位、Demo 证据链、技术栈、CI、能力边界 — 来源：仓库根（最后修改 2026-08-10）

| 章节 | 内容摘要 |
| --- | --- |
| 开头定位 | "真能对话"的企业级智能客服 AI Agent 作品集，对标阿里云 AI 助理形态；覆盖 LangGraph 编排、RAG、MCP、多租户、RBAC、5 层安全护栏、云原生可观测 |
| 30 秒看懂 | 单进程提供官网前端+REST+WebSocket 聊天；真实大模型（通义千问）非 mock；856 测试 + 覆盖率门禁 + SAST 全绿；GitHub Actions 4 并行 job |
| 实时 Demo | `demo.gif`（工具调用开工单）与 `rag_demo.gif`（RAG 检索）均由真实 WS 对话脚本化生成，可复现（scripts/ws_capture.py、rag_capture.py 等） |
| 项目亮点 | LangGraph 7 节点 DAG（entry→rag→reply）；HybridRetriever（向量+关键词）；MCP 38 个标准化工具；RBAC 三层防护；真实云资源查询（手写阿里云 RPC Signature V1，零依赖只读）；compose 多副本（api/ws replicas:2）；引用气泡可溯源 |
| 可验证证据链 | 多租户 WS 隔离 pytest 进 CI（4 点全绿）；`verify_multireplica.py` 双副本共享存储一致实测；infra-validate job 每次校验 4 个 compose + 真实 build 3 镜像 + Helm 三套 values 渲染（曾查出 values-prod nil pointer） |
| 能力边界（诚实标注） | 已实测：多副本扩展、应用层全栈（verify_fullstack_local.py）、多租户隔离、可观测、RAG；CI 校验：compose/镜像/Helm；**待 Docker 环境补齐：完整 12 服务栈联跑（verify_fullstack.py）、Grafana 出数（verify_monitoring.py）**——⚠️ 此条滞后于 D1（D1 记录 Grafana 已 VERIFIED、全栈已突破 minio 卡 milvus，见 §3 X4）；云资源默认 `ALIYUN_DEMO_FALLBACK=true` 回退样本 |
| 系统架构 | mermaid 图：React SPA → WS /ws/chat + REST /api/v1 → 5 层护栏 → LangGraph 7 节点 DAG + ReAct Agent → RAG/Memory/MCP → Chroma·Milvus/PG/Redis/RabbitMQ；单进程 StaticFiles 同源托管前端 static/ |
| 技术栈表 | LangGraph 7 节点；Qwen-Plus/Max；text-embedding-v4（1024 维）；Chroma 开发/Milvus 生产；FastAPI+uvicorn；APISIX；RabbitMQ；MinIO；React+TS+Vite；Prometheus+Grafana；GitHub Actions；JWT HS256 零依赖；Python 3.11+ 锁定；Node 22+ |
| MCP 服务 | `src/protocols/mcp_server.py` 暴露 38 工具（客服 3/工单 6/账单 5/用户 5/SSO 5/API Key 5/审计 4/知识库 5）；分端口启动模式（9000 全量/9005 工单/9010 管理/9011 账单）；三层权限防护+幂等 key |
| 测试与 CI | 4 并行 job：python-test（ruff+pytest+覆盖率门禁≥40%）、python-security（Bandit 中高危+Semgrep ERROR）、frontend-build（oxlint+tsc+vite）、infra-validate；856 passed/17 skipped；覆盖率 48.83%（门禁 40%）；19 个 router 接线守卫 |
| 注 | 仓库内 `.gitlab-ci.yml` 与当前 CI 无关，实际流水线在 GitHub Actions（见 §3 X2） |

### D3：`docs/需求文档-模仿阿里云AI助理智能体.md`

> 开发需求文档 v1.0（草稿，待评审），含 29 条功能需求、非功能需求与四条已拍板硬性定位 — 来源：八弟与拾一协作，2026-08-06

| 章节 | 内容摘要 |
| --- | --- |
| §1.1 项目定位 | 个人简历作品集，证明全栈 AI 工程能力：LangGraph/RAG/MCP/RBAC/多租户/云原生/可观测 |
| §1.3 模仿边界 | 复刻阿里系共享能力范式（多轮对话、RAG、工具调用、工单流转、权限隔离、多渠道），不全盘复制；聚焦"可演示、架构完整、工程深度"子集 |
| §2 总体架构 | 五面结构：展示层（浮动聊天+管理后台）→ 网关鉴权层（JWT/RBAC/限流）→ 对话编排层（LangGraph）+ 业务支撑层（工单/用户/知识库/RBAC/多租户）→ 能力插件层（RAG chroma/MCP 工具/模型网关/监控） |
| §3.1~3.8 功能需求 | FR-01~FR-29 共 29 条，分 8 域：智能对话（FR-01~05）、知识库（FR-06~09）、资源查询诊断（FR-10~13，FR-13 只读安全约束 P0）、故障工单（FR-14~17）、人机协同（FR-18~19）、多渠道（FR-20~21）、权限多租户（FR-22~25）、管理后台（FR-26~29）；每条标注 P0/P1/P2 与阿里云能力来源域名 |
| §4 非功能需求 | NFR-01 性能：TTFT≤3s、端到端≤8s、RAG P95≤500ms；NFR-03 安全：bcrypt、只读、JWT 过期刷新、防注入；NFR-05 部署：本地 SQLite 零依赖启动、生产 PG+向量库容器化 |
| §5 技术架构映射 | 需求→现有代码映射表（对话编排/RAG/工具/鉴权/RBAC/工单/前端/部署/可观测），标注缺口；登录 bug（repositories.py 缺 password_hash）已于 2026-08-05 修复（commit 62c56da） |
| §6 验收标准 | MVP 验收 6 条（admin/admin123 登录、多轮对话、PDF 上传可引用、工单创建流转、三角色越权 403、单进程全链路演示）；进阶验收 4 条 |
| §7 功能对齐清单 | 16 项阿里云能力映射（来源均为 alibabacloud.com 或 aliyun.com/en 英文站，非中文信源） |
| §9 四条硬性定位（2026-08-06 拾一拍板，已决策） | ①形态：客服工作台智能客服（面向坐席/运维，非纯 C 端）；②数据真实性：资源查询/诊断必须走真实云 API（已实现手写 RPC 签名零依赖客户端，无 AK/SK 回退样本，默认 `ALIYUN_DEMO_FALLBACK=true`）；③多租户+RBAC 纳入 MVP（四级角色 + tenant_id 全链路，LLM 无法跨租户）；④部署必须容器化多副本（已实现 compose 去 container_name + api/ws replicas:2） |

### D4：`docs/cloud-native-architecture.md`

> 云原生架构升级方案：容器拆分、CI/CD、存储分层、微服务拆分、中间件、网关与实施路线图 — 来源：docs/，2026-07-15

| 章节 | 内容摘要 |
| --- | --- |
| 前置判断 | 直接上 K8s 是错的（QPS 小于 100）；路线 Docker Compose → K3s 单机 → 完整 K8s 集群；本文按 K3s 设计但向下兼容 compose |
| §1 容器化与编排 | 拆 6 服务（api/ws/rag/agent-worker/channel/frontend）各自 Dockerfile；Helm Chart 结构（11 模板+多 values）；HPA/CronHPA/资源限制策略；§1.6 已落地：应用层去 container_name、api/ws replicas:2、数据层单实例；§1.7 已落地：真实云 API 适配层（aliyun_client.py 手写签名、CloudProvider/FallbackProvider 抽象、tenant_id 强制注入、只读边界） |
| §2 CI/CD | 选型推荐 GitLab CI + ArgoCD（⚠️ 与现状 GitHub Actions 不一致，见 §3 X2）；5 阶段流水线（lint→test→SAST→build→push）；生产 git tag + 手动审批 + ArgoCD sync |
| §3 数据存储分层 | PG（租户/对话/画像/评估）+ Milvus（向量）+ MinIO（文档/权重/日志）+ Redis（会话/缓存/限流/分布式锁）；Chroma→Milvus 迁移策略（重 embed、双写、Chroma 留 30 天回滚）；tenant_id 作复合主键前缀、Milvus Partition Key 物理隔离；全自托管零服务费 |
| §4 微服务拆分 | 按业务边界+数据所有权+变更频率拆；api↔rag 同步 HTTP（gRPC 判为过度设计）、worker 经 MQ 异步；memory-service 独立规划；公共库（safety/protocol/config/types）不单独部署 |
| §5 中间件 | Redis 缓存键设计 + 分布式锁三场景（索引更新/记忆去重/配额扣减）；RabbitMQ 选型理由（对比 Kafka）；4 队列拓扑（inference/memory.persist/rag.index/notify）；不需要 Nacos（K8s Service + CoreDNS 足够） |
| §6 API 网关 | 选型 APISIX（对比 Kong/Nginx/Traefik）；路由设计（9080/9443）；插件配置（jwt-auth/limit-count/api-breaker/prometheus 等）；TLS 终止于网关 |
| §8 实施路线图 | Phase 1 基础设施（compose 多副本已勾 ✅；Chroma→Milvus、APISIX 替换、PG Schema 未勾）；Phase 2 CI/CD、Phase 3 微服务拆分、Phase 4 K3s 部署、Phase 5 生产加固均未勾——⚠️ 部分项（APISIX/PG/Milvus 编排）此后已落地于 compose，路线图勾选状态滞后 |

### D5：`docs/resume-project.md`

> 简历「项目经历」栏叙事母本与面试准备底稿，所有数字基于实际代码统计 — 来源：docs/，与 README 同步

| 章节 | 内容摘要 |
| --- | --- |
| 30 秒速览 | 量化亮点：核心代码 14,707 行 Python、856 测试全绿/覆盖率 48.83%、38 个 MCP 工具、多租户隔离+多副本均有自动化证据 |
| 项目职责 1~9 | ①微服务拆分 4 服务+Helm 11 模板 3 values；②HybridRetriever（向量+BM25+RRF、双索引、句子窗口）；③LangGraph 7 节点 DAG + MemoryManager 三节点记忆接入；④5 层安全护栏 + LLM-as-Judge 5 维评分 + 幻觉检测；⑤云原生体系（APISIX+RabbitMQ 4 队列 DLQ+PG 9 表+Prometheus/Grafana 12 面板 8 告警）+ GitHub Actions 流水线；⑥阿里云只读适配层（FallbackProvider 三档 source 标记）；⑦引用气泡全链路；⑧多租户 SQL 级+向量级双重隔离、空 tenant 归 default 后门封堵、RBAC 4 角色（admin/agent/viewer/user，⚠️ 与 D6 的 5 角色口径不同，见 §3 X5）；⑨JWT HS256 无状态鉴权支持多副本 |
| 项目成果 | 代码 14,707 行（90 模块 24 子包）；部署配置 2,471 行；856 passed+17 skipped；覆盖率 48.83%；RAG 评估 6 场景平均 Recall 0.6528/MRR 0.8333 |
| 可演示性 | 单进程全链路 demo 实测；WS /ws/chat 主链路；引用气泡实测（ECS 问题命中 SOP 文档）；查资源/开工单端到端实测；**能力边界：完整 12 服务栈长时间联跑尚未在本机完成**（⚠️ 滞后于 D1，见 §3 X4） |
| 技术栈表 | 与 D2 一致；PG 16 + Redis 7 + MinIO；RabbitMQ 4.0 Topic+DLX；APISIX 3.x |

### D6 ~ D22：次要资料（按主理人指令只列角色，不展开精读）

| 编号 | 角色一句话说明 |
| --- | --- |
| D6 `docs/多租户-RBAC隔离核查.md` | 2026-08-07 核查报告：多租户"架构就绪但未运行化"（实际仅 default 租户在跑）；记录 5 项风险（R1 空 tenant 后门已修复、R2 工单 API 硬编码 default、R3 WS 匿名共享空租户、R4 RBAC 无租户维度、R5 无租户管理端点）及 P0 修复实施记录 |
| D7 `docs/TECH_SHARING_2026.md` | 5 期技术分享大纲（确定性单测/异常红线/async 正确性/可观测/评审文化），面向团队带练场景，配套资产已入库 |
| D8 `docs/api.md` | 接口协议权威文档：WS /ws/chat 与 /ws/agent/{id} 消息协议（streaming_chunk 字段为 text/delta）、REST /api/v1 按域速查（auth/sessions/tickets/admin/knowledge/rbac/dashboard/evaluation/monitoring 等） |
| D9 `docs/INDEX.md` | 文档导航：按读者角色分组；声明 docs-update-1~5 为历史工作笔记"按需查阅的资料库"；文档与代码不符时以 src/ 与 api.md 为准 |
| D10 `docs/CODE_STYLE.md` | 代码规范速查卡（ruff 行宽 88、类型注解 100%、异常安全消息、确定性测试、async 纪律） |
| D11 `docs/PR_REVIEW_CHECKLIST.md` | 合并前 7 大类评审清单 + SAST 门禁规范（bandit 中高危/semgrep ERROR、# nosec 必须同行带理由） |
| D12 `docs/deployment/runbook.md` | 三道缝验证操作手册（verify_fullstack_local / verify_fullstack / verify_monitoring 三脚本判定标准、离线 wheels 构建、代理与残留容器注意事项）；⚠️ §5 验证清单勾选状态滞后于 D1 |
| D13 `overview.md` | 团队技术提升四阶段落地总览（2026-07-31）；⚠️ 部分已过时：fail_under 记为 35（现状门禁 40、实测 48.83%，见 §3 X1）；"待办"条目多为团队协作者语境 |
| D14 `改动方案.md` | 2026-07-20 改动方案 v1.0；⚠️ 部分已过时：§7.1 前端 3 页面（AdminDashboard/ConversationDetail/KnowledgeBaseAdmin）记为 ⏳ 但 D1 §0 明确"早已落地"；§1 SSE 流式描述与现状 WS 主链路口径不同（见 §3 X7）；Python 3.10+ 与现状 3.11 锁定不同 |
| D15 `团队技术提升方案.md` | 2026-07-31 团队协作体检+8 周路线图（覆盖率 80% KPI）；D1 §0 明确标注**对本项目不适用**，不得当 KPI 推；其中 5 个质量短板案例为当时代码快照 |
| D16 `docs-update-1.md ~ docs-update-5.md` | 5 份历史深度工作笔记（目录全解/架构评估/面试问答/学习笔记/微服务设计，合计约 38 万字符）；D9 定位为资料库；主理人确认部分已过时，以代码现状为准 |
| D17 `POSTGRES_LOCAL_SETUP_GUIDE.md` | 本机 PG Docker 验证手把手指南（容器起 PG 16、.env 配 STORAGE_BACKEND=postgres、验证重启不丢数据）；文末两条已知缺口已修复（commit 878ad80）；D1 §7 标注已推送 |
| D18 `capability-contract.yaml` | payments 扣款能力契约样例（幂等/错误模型/SLA/契约测试），属契约规范示例外来样例，非本系统接口 |
| D19 `capability-ticket.yaml` | 本系统 MCP 能力契约 v2.0.0：7 域 38 工具的角色矩阵、幂等策略（ticket_create/billing_deduct）、SLA（p95 100ms/可用性 99.9）、指标与契约测试定义 |
| D20 `data/docs/*.md`（13 篇） | RAG 业务语料：虚拟产品 CloudSync 的产品文档（账号/API/分页/计费/SSO/Webhook/排障等 13 篇）；角色为知识库测试语料而非项目背景资料；入库状态：KB `KBS-CD0480`、205 切片已 indexed、tenant=default（D1 §9.2） |
| D21 `docker-compose.yml` + `deploy/` + `docker/` | 部署编排现状：12 服务=apisix(+dashboard profile)/api-service(replicas:2)/ws-service(replicas:2)/agent-worker/rag-service/frontend/postgres/milvus-standalone(内存限 2G，与 D1 §3 卡点互证)/minio/redis/rabbitmq；全部服务已注入 `env_file: docker/no_proxy.env`（D1 修复①在配置层的实证）；api-service 不发布主机端口走 apisix:9080；deploy/ 含 apisix/argocd/helm/monitoring/postgres/rabbitmq 配置，docker/ 含 api/rag/worker 三 Dockerfile + no_proxy.env |
| D22 `docs/agent-project-roadmap.html` | 路线图展示页，未列入转交清单，非现状事实来源 |

---

## 3. 冲突记录

> 不同资料对同一事实描述矛盾时，**并列保留两个版本**，不做裁决。

| 编号 | 冲突主题 | 版本 A | 出处 A | 版本 B | 出处 B | 差异说明 |
| --- | --- | --- | --- | --- | --- | --- |
| X1 | 覆盖率门禁与目标 | fail_under=35（保守起步），目标上调至 80% | D13 overview.md 待办 1；D15 团队技术提升方案 §二.4 | 门禁 40%，实测 48.83%（`--cov-fail-under=40` 固化进 pytest 与 CI） | D2 README §测试与 CI；D5 §项目成果 | 时效性差异：overview/团队方案为 2026-07-31 快照，README 为 2026-08-10 现状；80% 目标被 D1 §0 判为"不适用 KPI" |
| X2 | CI 平台 | 推荐 GitLab CI + ArgoCD；`.gitlab-ci.yml` 有覆盖率门禁 | D4 §2.1/§2.3；D13 Phase 1 | 实际流水线为 GitHub Actions 4 并行 job；README 明示 `.gitlab-ci.yml` 与当前 CI 无关 | D2 §技术栈注/§测试与 CI | 方案文档推荐 vs 落地现状不一致；README 已主动澄清 |
| X3 | 前端 3 个页面完成度 | AdminDashboard / ConversationDetail / KnowledgeBaseAdmin 状态 ⏳ 未完成 | D14 改动方案.md §7.1 | "前端 3 个未完成页面早已落地"，以代码现状为准 | D1 §0 误导警告 | D14 为 2026-07-20 快照，已过时 |
| X4 | 12 服务容器栈与 Grafana 验证状态 | "完整 12 服务栈长时间联跑尚未在本机完成"；Grafana 出数"待 Docker 环境补齐" | D2 §能力边界；D5 §可演示性；D12 §5 验证清单 | Grafana 已实跑 VERIFIED（12/18 面板出数）；全栈已突破 minio 卡点、现卡 milvus 内存 | D1 §1/§2/§3 | D2/D5/D12 为 08-10 前口径，D1（08-11 晚间）为最新实测；README/runbook 待回填 |
| X5 | RBAC 角色集合 | 四级：super_admin/admin/agent/viewer | D3 §9 硬性定位③；D5 职责⑧记为 admin/agent/viewer/user 四级 | 五级：super_admin/admin/agent/viewer/supervisor + 17 权限点 | D6 §3.1（基于 2026-08-07 代码走查） | 口径/时点差异：D6 为代码走查实测，D3/D5 为文档叙述且两者彼此也不一致 |
| X6 | Python 版本基线 | Python 3.10+ | D14 改动方案.md §三 技术选型 | Python 3.11+（部署与 CI 锁定 3.11） | D2 §快速开始；D5 §技术栈 | D14 为早期方案，已被锁定 3.11 取代 |
| X7 | 对话流式通道 | SSE 流式输出（/chat/stream，REQ-007） | D14 §1.2/§5.1 | WebSocket /ws/chat 为主链路，REST /chat 仅兜底 | D8 §1/§2；D2 §系统架构 | D14 为 2026-07-20 设计，现状主链路已切 WS；api.md 为接口权威 |
| X8 | CI 阶段数 | 3 阶段流水线（lint→pytest→SAST） | D5 职责⑤ | 4 个并行 job（pytest/SAST/前端构建/infra 校验） | D2 §测试与 CI；D5 §技术栈表 | D5 内部两处口径不一致（职责节 3 阶段 vs 技术栈表 4 job），D2 与 D5 技术栈表一致为 4 |
| X9 | 多租户运行态 | 多租户+RBAC 已纳入 MVP，tenant_id 贯穿全链路（LLM 无法跨租户） | D3 §9 ③；D2 §亮点 | 运行态实际只有 default 单租户在跑；无租户管理端点；工单 API 硬编码 default | D6 §一/§2.4/§2.7/§五 | "架构就绪"与"运行化"两个层面：D3/D2 述架构能力，D6 述运行态实测；D6 建议简历如实声明 |

---

## 4. 硬指标清单

| 章节 | 硬指标 | 状态 |
| --- | --- | --- |
| §1 | 每份资料有解析状态，失败/跳过注明原因 | ✅（22 个条目全部标注；D16/D20/D22 跳过均注明依据，D13~D15 过时性已标注） |
| §2 | 每份文档按章节逐条摘要，每条标注了 `D编号，§章节` | ✅（D1~D5 按章节逐条摘要；D6~D22 按主理人收窄指令以组合条目列角色说明，条目标注编号） |
| §3 | 冲突信息并列保留，不做裁决 | ✅（X1~X9 共 9 条冲突，均并列双版本+双出处，未做裁决；时效性高的一方仅作"差异说明"提示） |

**补充说明（供下游 business-architect 消费）**：
- 事实与出处映射粒度：D1~D5 精确到文档章节号；D1 内部行号级事实（如 compose 内存 2G）已与 D21 配置原文互证。
- 缺失/待外部验证点：①milvus 内存实锤数据未拿到（D1 §3）；②`scripts/proxy_relay.py` 用途待用户确认（D1 §5）；③RAG 三 bug 端到端复验未做（D1 §9.3）；④D16（docs-update-1~5）未逐份精读，若下游需要其中具体事实需另行提取。
- 本摘要不含任何业务/技术判断结论；§3 全部冲突留待主理人与下游裁决。

---

## 附录 A：生成流程

### 流程总览

| 步骤 | 动作 | 落入章节 |
| --- | --- | --- |
| Step0 | 读取模板 + 全部原始资料 | — |
| Step1 | 盘点资料清单，标注解析状态 | §1 |
| Step2 | 逐份打开资料，按自身章节结构逐条摘要 | §2 |
| Step3 | 交叉比对不同资料，发现并记录矛盾 | §3 |
| Step4 | 逐项核验硬指标 | §4 |

```mermaid
flowchart LR
    S0[读取模板与资料] --> S1[盘点资料清单]
    S1 --> S2[逐份精读逐章节摘要]
    S2 --> S3[交叉比对记录冲突]
    S3 --> S4[硬指标自检]
```

### 整理原则

1. **逐份精读，不跨文档归并**：摘要按文档自身章节结构组织，不做跨文档的主题重组（那是下游的事）
2. **出处即章节号**：每条摘要标注 `D编号，§章节`，直接映射回原文位置
3. **冲突保留**：矛盾信息并列保留两个版本，不擅自裁决
4. **事实驱动**：以原始资料中的事实为准，不添加主观推断

---

## 附录 B：解析 Skill

- `docx`：Word 类产品/业务文档
- `pdf`：PDF 类规范、手册、报告
- `pptx`：PPT 类方案/汇报
- `xlsx`：Excel 类数据清单、指标表
- 本批资料实际类型为 `md` / `yaml` / `html` / compose 配置（无 Office/PDF 文件），均采用直接精读方式解析，未动用格式转换类 Skill
