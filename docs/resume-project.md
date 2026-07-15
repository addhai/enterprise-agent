# 企业级智能客服系统 — 简历项目模块

> 所有数字基于实际代码统计和测试运行，无编造数据。

---

## 项目背景

针对传统企业客服存在知识库检索不准、多轮对话上下文丢失、人工应答响应慢三大痛点，设计并实现了一套基于 LangGraph + RAG 的智能客服系统。系统覆盖从渠道接入、意图路由、向量检索、多轮推理到安全防护、多维评估的完整链路，并完成了微服务拆分与 K3s 云原生部署架构设计。

## 项目职责（个人贡献）

**1. 全栈架构设计与微服务拆分**

- 将单体 FastAPI 应用拆分为 6 个独立微服务（API / RAG / WebSocket / Agent Worker / Memory / Channel），每个服务独立 Dockerfile + docker-compose 编排，可按 CPU/连接数/队列深度独立扩缩容
- 设计 Helm Chart（11 个模板 + 3 个环境 values），覆盖 Deployment/Service/ConfigMap/Secret/HPA/Ingress/APISIX Gateway，支持 staging 自动部署 + production 手动审批

**2. RAG 检索系统核心开发**

- 实现混合检索器（HybridRetriever）：向量语义检索 + BM25 关键词检索 + RRF 融合，双索引架构（段落级 + 句子级），支持句子窗口上下文展开
- 设计多维离线评估体系：实现 Recall/Precision/MRR/F1 四项指标计算模块。在 6 种真实检索场景模拟测试中，最佳情况 Recall=1.0, F1=1.0，中等场景（3 条期望文档命中 2 条）Recall=0.6667, MRR=1.0（第 1 位命中）
- 实现 Chroma → Milvus 向量库迁移方案：保留 Chroma 本地降级能力，生产环境切换 Milvus 获得 Partition Key 多租户物理隔离、12 种索引类型支持、Prometheus 原生监控

**3. LangGraph 多路径工作流编排**

- 设计 7 节点 DAG（entry → clarify → router → faq/rag/human → reflect → reply），5 种对话路径自动路由（FAQ 直达/技术排查/人工转接/FAQ 升级 RAG/RAG 转人工）
- 实现 MemoryManager 三节点记忆接入（entry 注入长期记忆上下文 → rag 提取对话历史 → reply 持久化 + 质量评估），支持 Redis 短期记忆 + PG 长期记忆双层架构

**4. 安全护栏与质量评估**

- 实现 4 层纵深防御：输入注入检测（正则 + LLM）→ 系统提示词约束 → Agent 工具权限检查（PermissionChecker 三层防护：工具级 + 参数级 + 审计日志）→ 输出敏感信息检测（PII + 幻觉引用交叉验证）
- 实现 LLM-as-Judge 5 维对话质量评分（相关性/准确性/完整性/安全性/语气），在线抽样框架（基于 user_id hash 一致性抽样），幻觉检测模块（技术标识符交叉验证）

**5. 云原生部署体系**

- 完整基础设施配置：APISIX 网关（路由分发/限流/熔断/鉴权/Prometheus 指标）+ RabbitMQ 任务队列拓扑（4 队列 + DLQ 死信）+ PostgreSQL 9 表 Schema（租户隔离 + 对话记录 + 审计日志）+ Prometheus + Grafana 监控面板（12 面板 + 8 告警规则）
- GitLab CI 6 阶段流水线：lint（ruff + oxlint）→ test（pytest + vitest）→ SAST（bandit + Semgrep + Trivy）→ build → deploy-staging（自动）→ deploy-prod（手动审批）

## 项目成果

**代码规模：**
- 核心业务代码 **14,707 行** Python（90 个模块，24 个子包）
- 单元测试 **742 行**（19 个文件，48 个测试用例）
- 部署配置 **2,471 行**（30 个 YAML/SQL/JSON 文件）
- 基础设施配置：3 个 Dockerfile + 3 个 docker-compose + 11 个 Helm 模板 + 5 个运维脚本

**测试统计：**
- 48 个测试用例，**45 通过，0 失败，3 跳过**（跳过项为需要真实 LLM API Key 的 Live Agent 端到端测试）
- 覆盖模块：config / agent tools / graph nodes / graph workflow / RAG chunker / RAG loader / RAG retriever / RAG vector store / evaluation metrics / safety guards
- RAG 离线指标 4 个测试全部通过（perfect_retrieval / partial_retrieval / mrr_with_second_rank / empty_expected）
- 安全护栏 7 个测试全部通过（输入注入识别 / 已知攻击模式 / 特殊字符清洗 / 正常内容保留）

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

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.14 |
| 编排 | LangGraph 0.2+ |
| Agent | LangChain (create_agent, ReAct) |
| LLM | 阿里百炼 Qwen-Plus / Qwen-Max（兼容 OpenAI 格式） |
| Embedding | text-embedding-v4 (1024 维) |
| 向量库 | Chroma（开发）/ Milvus 2.5（生产） |
| 服务 | FastAPI + uvicorn + WebSocket |
| 网关 | Apache APISIX 3.14（限流/熔断/Prometheus） |
| 消息队列 | RabbitMQ 4.0（Topic Exchange + DLX 死信） |
| 存储 | PostgreSQL 16 + Redis 7 + MinIO |
| 部署 | Docker Compose（开发）+ K3s + Helm（生产） |
| CI/CD | GitLab CI（6 阶段）+ ArgoCD（GitOps） |
| 监控 | Prometheus + Grafana（12 面板 + 8 告警） |
| 代码质量 | Ruff + Bandit + Semgrep + Trivy |

## 相关技能标签

`LangGraph` `RAG` `向量检索` `混合检索` `BM25` `RRF` `Milvus` `Chroma` `Recall@K` `MRR` `LLM-as-Judge` `幻觉检测` `微服务` `Docker` `K3s` `Helm` `APISIX` `RabbitMQ` `PostgreSQL` `Redis` `分布式锁` `GitLab CI` `ArgoCD` `Prometheus` `Grafana` `安全护栏` `多租户` `FastAPI` `WebSocket`
