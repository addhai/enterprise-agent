# Enterprise Agent 面试问答手册

> 项目：enterprise-agent — 企业级智能客服系统
> 版本：v2.0（云原生微服务架构 + 业务系统升级）
> GitHub：github.com/addhai/enterprise-agent
> 更新时间：2026-07-17

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

## 一、项目概述类

### Q1：简单介绍一下这个项目？

**参考答案：**

这是我独立开发的企业级智能客服 Agent，经历了从单体到云原生微服务的完整演进。

**当前技术栈：** LangGraph + LangChain + FastAPI + Milvus（向量）+ PostgreSQL（业务）+ Redis（缓存/锁）+ RabbitMQ（消息队列）+ MinIO（对象存储）+ APISIX（网关）+ 阿里百炼 Qwen。

**部署方案：** Docker Compose（开发环境，12 个服务一键启动）/ K3s + Helm（生产环境）+ GitLab CI + ArgoCD（GitOps）。

**核心功能：** 用户问一个问题 → APISIX 网关路由到 API 服务 → 系统自动判断意图（FAQ 直达 / 技术排查 / 转人工 / A2A 远程委托）→ 走对应的处理流程 → 返回回复。

项目覆盖了 Agent 开发的全部核心模块：**RAG 知识库引擎**（三层解耦插件化架构 + Milvus 生产级向量库）、**ReAct 自主推理**、**LangGraph 工作流编排**（v2.0 扁平化为 8 节点单层 StateGraph）、**高级记忆管理**（三层架构 + Redis 优先降级）、**Agent 评估监控**（LLM-as-Judge + Prometheus + Grafana）、**智能体安全防护**（五层纵深防御）、**MCP 工具互联 + A2A Agent 协作**。

**代码规模：** 14,707 行 Python，90 个模块，24 个子包；2,471 行部署配置（YAML/SQL/JSON），30 个配置文件；测试 48 个（45 passed, 0 failed, 3 skipped）。

**面试要点：** 强调你从"单体 RAG 聊天机器人"演进到"云原生微服务架构"的完整工程能力——不只写代码，还做了容器化、CI/CD、监控、备份。

---

### Q2：为什么做这个项目，不是直接用 ChatGPT 套壳？

**参考答案：**

ChatGPT 不知道我们公司的产品文档、没有实时记忆、不会调用工具、不能按规则路线走流程。

这个项目的核心不是"回答问题"，而是企业级 Agent 的能力闭环：**网关路由（APISIX）** --> **检索私有知识（Milvus RAG）** --> **自主推理（ReAct）** --> **可控流程（LangGraph）** --> **异步解耦（RabbitMQ）** --> **持久记忆（PG + Redis）** --> **质量评估（LLM-as-Judge）** --> **安全防护（五层护栏）** --> **可观测性（Prometheus + Grafana）** --> **CI/CD（GitLab CI + ArgoCD）**。

特别是我做了从 Chroma（开发 PoC）到 Milvus（生产级分布式向量库）的迁移、从 Nginx 到 APISIX（动态路由 + 限流熔断）的网关升级、从 docker-compose 到 K3s + Helm 的部署升级。这些是企业级工程能力，不是调个 API 能做到的。

**面试要点：** 展示你对"企业级"和"玩具项目"区别的理解——工程化能力包括微服务拆分、服务治理、可观测性、CI/CD、数据备份。

---

### Q3：项目是你从头写的还是改的开源项目？

**参考答案：**

完全从零自己写的。项目用了 LangChain/LangGraph/PyMilvus 这些框架和 SDK，但它们提供的是底层能力，不是整套客服系统。

具体做了什么：设计了三层解耦的 RAG 架构（支持 5 种格式 + Milvus Partition Key 多租户隔离）、定义了 LangGraph 工作流（v2.0 扁平化 8 节点 0 子图）、实现了混合检索（向量+BM25+RRF 融合）+ 双索引、三层记忆架构（Redis 优先 + PG 持久化 + LLM 摘要）、五层安全护栏、APISIX 网关动态路由（4 条路由 + 限流/熔断/鉴权插件）、RabbitMQ 4 队列异步任务系统、Redis 分布式锁（Lua 脚本原子释放）、K3s + Helm 部署、GitLab CI 6 阶段流水线 + ArgoCD GitOps、Prometheus + Grafana 监控体系、数据备份策略。这些架构设计都是自己做的。

**面试要点：** 区分"框架提供的能力"和"自己做的架构设计"。面试官想听到的是你的**架构决策**。

---

## 二、技术架构类

### Q4：整体架构是怎么设计的？

**参考答案：**

当前架构经历了从单进程到云原生微服务的演进。整体六层架构：

1. **接入层（APISIX 网关）**：动态路由（4 条路由规则）、限流（按用户 20 req/s）、熔断（连续失败 5 次触发）、Prometheus 指标导出、审计日志回调
2. **业务服务层（6 个微服务）**：api-service（REST API + LangGraph 编排）、ws-service（WebSocket 长连接）、rag-service（独立 RAG 检索服务）、agent-worker（RabbitMQ 异步消费推理任务）、frontend（React SPA）、memory/channel 内嵌模块
3. **消息中间件层（RabbitMQ）**：Topic Exchange + 4 个业务队列（推理/记忆持久化/文档索引/推送通知）+ DLQ 死信队列
4. **编排层（LangGraph）**：v2.0 扁平化单层 StateGraph，8 节点 0 子图
5. **能力层**：RAG 检索（Milvus + 三层解耦管道）+ 记忆管理（三层架构）+ 工具调用 + 安全护栏
6. **数据层**：Milvus（向量）+ PostgreSQL 16（业务结构化数据，9 张表）+ Redis 7（缓存/分布式锁/限流）+ MinIO（对象存储：文档/日志/模型/备份）

**核心设计原则：** LangGraph 管流程（大方向），ReAct 管执行（小自由）。编排层和能力层通过接口解耦——向量库从 Chroma 切到 Milvus，编排层一行代码不用改。开发环境用 Chroma（本地零配置），生产环境用 Milvus（分布式 + 多租户 Partition Key 隔离）。

**面试要点：** 展示"分层解耦 + 开发/生产分离"的设计思想。提到 Milvus Partition Key 多租户隔离是加分项。

---

### Q5：五种对话路径是什么？怎么设计出来的？

**参考答案：**

分析真实客服对话后，定义了五种路径，v2.0 扁平化后通过单层 StateGraph 的条件边实现：

| 路径 | 场景 | 占比 | 耗时 |
|------|------|------|------|
| FAQ 直达 | "怎么重置密码" | 50% | <1s |
| ReAct 技术排查 | "API 返回 403 怎么办" | 30% | 2-5s |
| 直接转人工 | "我要投诉" | 10% | <1s |
| FAQ → 升级 RAG | FAQ 没匹配到 | 5% | 3-5s |
| RAG → 转人工 | 排查失败升级 | 5% | 3-5s |

v2.0 重构后增加了 A2A 远程委托路径：当本地知识库无法回答时，可以委托给外部专家 Agent。

关键技术点：后两条升级路径通过 LangGraph 条件边实现二次路由，传统 Router Chain 做不到。v2.0 将追问逻辑融合进 classify_node，先意图分类再决定是否追问（FAQ 豁免），解决了"怎么重置密码 → 系统反问 SDK 版本"的 bug。

**面试要点：** 这个设计是区分"用过 LangGraph"和"真理解 LangGraph"的关键。

---

## 三、RAG 技术类（重点，v0.4 重构后）

### Q6：RAG 子系统是怎么设计的？

**参考答案：**

RAG 子系统在 v0.4 重构为**三层解耦架构**，v0.5 升级为多后端支持：

```
数据源层 (data_sources.py)    → 统一文件扫描和读取接口
加载器插件 (loaders/)         → 按格式注册，新格式只需加一个类 + 装饰器
处理管道 (processors/)        → 链式处理器，每个独立可替换
向量存储适配层 (存储后端)     → Chroma（开发）/ Milvus（生产）/ Remote（远程 RAG Service）
```

**多后端策略：**
- 开发环境：`VECTOR_STORE_BACKEND=chroma`，本地零配置，不依赖 Milvus
- 生产环境：`VECTOR_STORE_BACKEND=milvus`，Milvus Standalone 单容器，使用 IVF_FLAT 索引 + COSINE 度量 + Partition Key 多租户隔离
- 远程模式：`VECTOR_STORE_BACKEND=remote`，api-service 通过 HTTP 调用独立的 rag-service
- 自动降级：Milvus 不可用时自动降级到 Chroma（`HybridRetriever.milvus_store` 懒加载失败时 fallback）

**数据流（文档入库）：**
```
原始文件 → MinIO 对象存储 → 数据源扫描 → 格式加载器 → 管道处理 → 质量拦截 → 去重 → 文档切块 → 向量化 → Milvus/Chroma
```

**数据流（在线检索）：**
```
用户问题 → 向量化 → Milvus 向量检索 + 标量过滤（tenant_id + access_level）→ 双索引并行检索 → RRF 融合 → Top-K 返回
```

支持 5 种格式（Markdown/PDF/HTML/DOCX/图片），每种通过 `@register_loader` 装饰器自动注册。新增格式的成本是"写一个类 + 加一行 import"。

**面试要点：** 强调"多后端"和"开发/生产环境分离"的工程实践。Milvus Partition Key 多租户隔离是加分项。

---

### Q7：混合检索是怎么实现的？

**参考答案：**

经历了三次演进：

**第一版：纯向量检索。** 上线后发现精确查询场景经常漏召回——用户搜"ERR_403_TIMEOUT"，向量模型把它当语义理解，返回的是《API 鉴权概述》而不是具体的错误码文档。根因是 Embedding 模型对专有名词不敏感。

**第二版：混合检索。** 向量检索 + BM25 关键词检索 + RRF 融合。向量负责语义泛化（"删除"="移除"），BM25 负责精确匹配（"ERR_403_TIMEOUT"）。

**第三版（v0.4+）：双索引 + 三路并行 + Milvus 标量过滤。** 标准粒度索引（段落级）+ 句子粒度索引（Small2Big）+ BM25。三路并行检索，RRF 融合标准结果，合并句子结果。Milvus 模式下还支持标量过滤（tenant_id + access_level）和向量检索在单条语句中完成——这是 Chroma 做不到的。

**RRF 融合的核心思想：** 不依赖绝对分数（向量 0.9 vs BM25 15.2 不可比），只关心相对排名。`score(doc) = sum(1 / (k + rank))`，k=60。

**面试要点：** 讲清楚"为什么从 A 换到 B"比"用了 B"重要十倍。

---

### Q8：Small2Big 句子窗口切块是什么？

**参考答案：**

核心洞察：检索时需要"精准定位"（句子级），但 LLM 生成时需要"完整上下文"（前后 N 句）。

工作流程：
1. 文档按句子边界切分，每个句子独立成块 → 存入句子级索引
2. 每个句子的 metadata 中保存前后 N 句（默认 window=3）
3. 检索命中句子后，通过 `expand_context()` 恢复完整段落给 LLM

**为什么有效：** 用户搜"ERR_403_TIMEOUT 怎么解决"，句子级索引能精确匹配到包含这个错误码的句子，然后展开前后 3 句给 LLM——LLM 看到的是完整的排查段落，而非孤立的一句话。

**面试要点：** 展示你理解"检索精度"和"生成质量"之间的矛盾。

---

### Q9：文档切块策略是什么？

**参考答案：**

不是简单的"按 512 字符切"。用的是 `HybridChunker`，同时生成两种粒度：

**标准粒度：** `RecursiveCharacterTextSplitter`，按 H2/H3/H4 标题层级优先断开，chunk_size=512, chunk_overlap=64。保证每个主题完整。

**句子粒度：** 按中文/英文句子边界切分（。！？；.!?），每个句子独立成块。

Token 硬上限是 text-embedding-v4 的 8192 token，但实际切块控制在 512 字符，因为短块检索更精准。

**面试要点：** 如果面试官追问"为什么不是简单的固定大小"，回答：固定大小切块会把"这个问题怎么解决"和"解法段落"切到两个块里。

---

### Q10：权限管控是怎么做的？

**参考答案：**

两层权限过滤，在 Milvus 层面做了强化：

**第一层：入库时标注。** `MetadataEnrichProcessor` 通过关键词分类文档的 `access_level`（public/internal/confidential/restricted）和 `business_domain`。`ContentSafetyProcessor` 根据 PII 检测结果自动升级权限。

**第二层：检索时过滤。**
- Milvus 模式：在向量检索时直接用标量过滤表达式 `access_level in ["public", "internal"]`，在数据库层面就过滤掉了——比 Chroma 的检索后过滤高效得多
- Chroma 模式：检索后通过 metadata 二次过滤租户和权限

权限等级优先级：public(0) < internal(1) < confidential(2) < restricted(3)。

**面试要点：** 展示"标注+过滤"的双层设计，以及 Milvus 标量过滤比 Chroma 后置过滤的性能优势。

---

### Q11：增量同步是怎么实现的？

**参考答案：**

`FileSyncManager` 维护一个 JSON 持久化的同步状态表，每个文件记录 content_hash（SHA-256 of normalized text）、mtime、chunk IDs。

**增量同步流程：**
1. 加载同步表
2. 扫描目录，计算每个文件的 content_hash + mtime
3. 分类：NEW / MODIFIED / UNCHANGED / DELETED
4. DELETED → 删除 chunk IDs → 从表中移除
5. NEW/MODIFIED → load → chunk → add_documents → 更新表
6. 持久化同步表

**关键设计：** 对归一化文本求哈希，而不是原始文件字节。格式微调（如 Markdown 空格增减）不触发重新处理。

**确定性 doc_id：** `doc:{path}:{hash}:{type}:{index}`，保证幂等重处理。

**面试要点：** "为什么对归一化文本求哈希"是一个很好的深度问题。

---

### Q12：并发加载和限流熔断是怎么做的？

**参考答案：**

四级防护体系：

**第一级：令牌桶限流（RateLimiter）。** 控制 API 吞吐速率。桶容量 = burst，令牌产生速率 = rate。

**第二级：熔断器（CircuitBreaker）。** 状态机：CLOSED → OPEN → HALF_OPEN → CLOSED。连续失败 N 次后打开熔断，等待 recovery_timeout 后进入 HALF_OPEN 探测。

**第三级：全局单例（GlobalLimits）。** 为 vision/ocr/safety 三类 API 分别管理独立的限流+熔断参数。

**第四级：APISIX 网关层熔断。** `api-breaker` 插件在网关层做第二道防线——连续 5 次 5xx 触发熔断（最长 30 秒），连续 3 次 200 恢复。

**ConcurrentLoader：** `ThreadPoolExecutor` 并发加载，每个文件加载受全局限流熔断保护。

**面试要点：** 展示你对"外部 API 不可靠"的工程认知——限流防打满，熔断防雪崩，网关层和应用层双重防护。

---

## 四、LangGraph 工作流类

### Q13：LangGraph 是什么？为什么用它？

**参考答案：**

LangGraph 是把对话建模成有向状态图的框架。三个核心概念：State（对话状态对象）、Node（处理函数）、Edge（节点间连线）。

经历了四次方案淘汰：
- 第一版线性 Chain：所有问题一条路，不能分流
- 第二版 Router Chain：能分流了，但 FAQ 失败后不能自动跳转到 RAG
- 第三版自由 Agent：灵活但不可控
- 第四版多子图架构：5 个子图嵌套 6 层 StateGraph，桥接函数在 6 种 State 之间转换，状态混乱

v2.0 重构为**单层 StateGraph + 8 节点 + 0 子图**：entry → classify → {faq_handle | rag_handle | human} → reflect? → reply → END。删除了 5 个子图和所有桥接函数，LLM 调用减少 60-80%。

**面试要点：** 展示你对"多智能体"本质的理解——职责分离，不是子图嵌套。

---

### Q14：LangGraph 的 State 是怎么设计的？

**参考答案：**

State 是贯穿整个工作流的 TypedDict 对象，v2.0 扁平化后包含：

```
messages（对话消息列表，add_messages Reducer 追加模式）
intent（当前意图：faq/technical/human/casual）
retrieved_docs（RAG 检索结果）
needs_human（是否转人工）
turn_count（当前轮次）
final_response（最终回复）
user_id / session_id / tenant_id（多租户隔离键）
faq_match（FAQ 匹配结果）
memory_context（长期记忆注入上下文）
quality_score（对话质量评分）
sentiment（情绪检测结果）
delegation_target（A2A 远程委托目标）
```

关键设计决策：messages 字段用了 LangGraph 的 `add_messages` Reducer（新消息追加，不是覆盖）。每个节点只返回自己改动的字段。

踩过的坑：最初忘了给 retrieved_docs 设 Reducer，rag_node 查到的文档被后续节点覆盖成空列表了。

**面试要点：** 说出 "Reducer 踩坑" 这个具体细节，证明你真正写到过这个 bug。

---

## 五、ReAct Agent 类

### Q15：ReAct 是什么？怎么工作的？

**参考答案：**

ReAct = Reasoning + Acting。循环：Thought（思考当前情况）→ Action（调用工具）→ Observation（观察结果）→ Thought...直到信息够了输出 Final Answer。

底层本质：LLM 在做 token 预测，Function Calling 是训练出来的模式——模型在训练数据中学到了"遇到需要外部信息的问题 → 输出 JSON 格式的工具调用"。不是魔法，是模式匹配。

agent-worker 通过 RabbitMQ 异步消费推理任务，结果通过回调或 WebSocket 推送给用户。这样做的好处是 API 服务不阻塞在 LLM 调用上（3-10 秒），保持 HTTP 接口低延迟响应。

**面试要点：** 说出"Function Calling 不是魔法，是训练出来的模式匹配"，证明你理解底层。

---

### Q16：Agent 无限循环怎么办？

**参考答案：**

三层控制：

1. **Prompt 层：** 加停止条件——"如果进行 2 次不同搜索都没找到相关信息，告知用户并建议转人工"
2. **架构层：** 硬性上限 max_turns + **动态 max_turns**——FAQ 类 1 轮、技术排查 5 轮、复杂工单 8 轮
3. **编排层：** Observation 里注入元信号——RAG 返回空时，Observation 本身包含降级提示

**面试要点：** 这个问题 90% 的 Agent 面试都会问。三层控制的回答展示了你从 Prompt、架构、编排三个层面思考问题。

---

### Q17：Agent 的"蝴蝶效应"是什么？

**参考答案：**

同一个问题，两次回答质量天差地别。根因是 LLM 的随机性——temperature 设为 0.3 时，同样的输入两次采样产生微小差异。在 ReAct 多轮循环里，第一轮的差异被后续轮次放大。

修复：关键节点（意图分类、FAQ 匹配）temperature=0；用 LangGraph 路由节点替代 LLM 做流程决策。

**面试要点：** 能讲出"蝴蝶效应"这个概念，面试官就知道你真实跑过 Agent 系统。

---

## 六、记忆管理类

### Q18：怎么管理对话记忆？

**参考答案：**

三层记忆架构，每层都有降级策略：

1. **短期记忆：** Redis 7 优先（会话级滑动窗口 + LLM 结构化摘要，TTL 1h），Redis 不可用时自动降级为进程内存
2. **长期记忆：** PostgreSQL 持久化 + Milvus/Chroma 语义检索优先，不可用时降级为内存字典 + 关键词匹配。同 topic 自动 upsert，90 天时间衰减加权
3. **MemoryManager 接入层：** 三节点自动触发 — entry_node 注入长期记忆上下文 → rag_node 提取对话历史 → reply_node 持久化 + 在线评估抽样

关键是增量摘要 + 定期全量重摘要——日常增量（省 token），每 10 轮全量重摘要（截断误差累积链）。

**面试要点：** 说出"摘要退化"和"降级策略"这些细节，证明你不是纸上谈兵。

---

### Q19：Lost in the Middle 是什么？

**参考答案：**

这是 Transformer 架构的固有问题——LLM 对 Prompt 中不同位置的注意力分布不均匀：开头和结尾注意力高，中间注意力低。对话超过 5 轮后，早期轮次的关键信息被挤到了注意力"洼地"。

解决方案：不把全量历史塞给 LLM，而是用三层记忆——滑窗保证近期高注意力，摘要保留远期关键脉络，检索式记忆让 Agent 需要时才查。

---

## 七、安全防护类

### Q20：Agent 怎么防 Prompt 注入？

**参考答案：**

核心原则：**LLM 本身不是安全边界，安全必须靠 LLM 外部的多层架构。**

五层纵深防御 + 网关层额外防护：
1. 输入规则过滤（正则 + 语义检测）— 1ms
2. APISIX 网关限流（按用户 20 req/s，防暴力攻击）
3. 编排护栏（工具白名单 + 参数校验）
4. Agent 护栏（Observation 清洗 + 参数二次校验）
5. 输出护栏（PII 检测 + 幻觉引用检测）
6. 审计告警（所有操作记录到 PostgreSQL audit_logs 表）

单层绕过率约 20%，五层叠加后理论上降到 0.0045%。

**面试要点：** 说出"LLM 本身不是安全边界"这句话，证明你有安全意识。

---

### Q21：RAG 系统中的安全检测是怎么做的？

**参考答案：**

在 RAG 管道层加入了内容安全检测：

**PII 检测（PiiDetector）：** 6 种模式 + 渐进验证。身份证有校验码验证，银行卡有 Luhn 算法验证。检测到 PII 后自动脱敏，并根据严重程度升级文档权限等级。

**合规检测（ContentComplianceChecker）：** 5 类本地正则检测（政治/色情/暴力/垃圾/违禁）+ 风险评分（每类 0.3 分，>=0.6 自动阻断）+ 云端 API 预留。

**权限自动升级：** 安全检测在入库时就拦截敏感内容——"安全左移"设计。

**面试要点：** 展示"安全左移"的设计思维——在数据入库时就做安全检测。

---

## 八、技术选型类

### Q22：为什么选 Chroma 不选 Pinecone / Milvus？

**参考答案：**

我最初确实选择了 Chroma 作为开发环境的向量库，因为 Chroma 起步零配置、Python 原生集成、pip install 就能跑。但在生产环境评估后，已经迁移到了 Milvus。

**为什么迁移：**
- Chroma 不支持分布式部署，单机扩展有上限
- 没有原生多租户隔离能力，需要手动分区
- 没有标量过滤 + 向量检索的融合查询（Milvus 一条语句搞定）
- 没有 Prometheus 原生 metrics 导出

**Milvus 带来的收益：**
- Partition Key 实现多租户物理隔离（`tenant_id` 作为 partition key）
- 标量过滤表达式在向量检索时同时生效（如 `access_level in ["public", "internal"]`）
- MinIO 对象存储持久化向量数据，不怕本地磁盘损坏
- 12 种索引类型可选（当前用 IVF_FLAT，适合百万级数据）

**架构上的抽象：** 编排层不直接依赖任何向量库，而是依赖统一的检索接口。通过 `vector_store_backend` 配置项在 Chroma/Milvus/Remote 之间切换。开发环境用 Chroma（docker-compose.dev.yml 中禁用 Milvus），生产环境用 Milvus。

**面试要点：** 展示你有"为未来迁移做抽象"的思维，以及"开发/生产环境分离"的工程实践。

---

### Q23：为什么选阿里百炼不选 OpenAI？

**参考答案：**

在国内 OpenAI API 需要翻墙访问，不稳定。阿里百炼在国内直接可用，中文效果更好，有免费额度，且完全兼容 OpenAI 接口格式——只需改 `base_url` 和 `model` 参数即可切换。

实际踩坑：LangChain 的 `OpenAIEmbeddings` 封装层会把文本拿去做 tokenize 再发给 API。OpenAI 支持 tokenized 格式，但阿里百炼的兼容接口只接受原始文本字符串。最终方案是用原生 `openai` 客户端直接调 API，绕过了 LangChain 的 tokenize 步骤。

当前项目支持多模型：api-service 用 qwen-plus（日常对话），复杂推理用 qwen-max，Embedding 用 text-embedding-v4（1024 维），视觉理解用 qwen-vl-plus。

**面试要点：** 说出"踩坑+解决"的过程比单纯说"选了 XX"更有说服力。

---

## 九、2026 年 Agent 工程热点

### Q24：你了解 2026 年 Agent 领域的热点吗（Harness/Loop/MCP/A2A）？

**参考答案：**

了解，而且在我的项目里都做了工程落地。

**Harness Engineering：** 我用 LangGraph 控制流程，工具按节点裁剪（faq_node 只给 search_faq、rag_node 才给 search_knowledge_base），加上五层安全护栏 + APISIX 网关层防护，这就是 Harness 的实践。

**Loop Engineering：** 做了三层收敛控制（max_turns 硬上限 + Prompt 停止条件 + Observation 元信号），动态 max_turns（FAQ=1 轮/Technical=5 轮），Reflection 自我反思节点。

**MCP：** 三个工具注册成 MCP Server（HTTP 模式），已验证 initialize → tools/list → tools/call 完整协议流程。

**A2A：** 客服 Agent 发布了 Agent Card（3 个 Skill），实现委托函数 `delegate_to_expert()`。v2.0 的 expert_delegate 节点支持将复杂问题委托给外部专家 Agent。

**面试要点：** 能说出具体怎么实现的，而不只是概念。

---

## 九、业务系统模块面试问答（v2.0 新增）

### Q43：你们系统的权限模型是怎么设计的？为什么选 RBAC？

**面试官意图：** 考察权限设计能力，是否考虑过度授权和最小权限原则。

**参考答案：**

我们采用 RBAC（Role-Based Access Control）模型，设计了 4 级角色：
- **Super Admin**：全权限，系统初始化时自动创建
- **Admin**：除用户管理外的全部管理权限
- **Agent**：客服权限，工单处理 + 工作台 + 查看数据
- **Viewer**：只读权限，看数据但不能操作

定义了 15 个细粒度权限点（如 `ticket:manage`、`customer:view`、`agent:workspace`），通过 `ROLE_PERMISSIONS` 字典映射角色到权限。每个 API 端点用 `require_permissions(...)` 依赖注入守卫。

**选 RBAC 的原因：**
1. 客服场景角色边界清晰（管理员/客服/观察员），不需要 ABAC 的复杂属性表达式
2. 实现简单，查询高效（角色→权限是 O(1) 字典查找）
3. 前后端对齐容易，前端用同样的角色-权限映射做按钮显隐控制

**如果用户量大、需要动态权限：** 可以升级到 RBAC + 资源属主（Owner）模型，比如"客服只能看自己分配的工单"。

---

### Q44：工单系统的状态机是怎么设计的？如何保证数据一致性？

**面试官意图：** 考察状态机设计、数据一致性保障、边界情况处理。

**参考答案：**

工单有 5 个状态：`open` → `in_progress` → `resolved/closed/cancelled`。

**状态转换规则：**
- open 可以 → in_progress / cancelled
- in_progress 可以 → resolved / closed / open（重开）
- resolved / closed / cancelled 是终态，不可再更新

**数据一致性保障：**
1. **不可变约束**：更新 API 中检查 `if ticket.status in (resolved, closed): raise HTTPException`，从业务层防止非法更新
2. **幂等创建**：支持 `idempotency_key`，重复提交返回已有工单
3. **评论独立**：工单关闭后仍可添加评论（历史记录补充），但状态不变

**如果上生产：** 会把状态机持久化到 PostgreSQL，用数据库事务保证原子性，加上乐观锁（version 字段）防止并发修改。

---

### Q45：数据仪表盘的数据是怎么聚合的？实时性如何保证？

**面试官意图：** 考察数据聚合方案、性能优化、实时性设计。

**参考答案：**

仪表盘有 4 个核心 API：KPI 聚合、实时活动、客服绩效、意图分布。

**数据聚合方式：**
1. **会话数据**：从 `SessionManager` 的内存字典实时聚合（总会话、活跃会话、等待人工数）
2. **工单数据**：从工单存储按状态/优先级统计
3. **满意度**：从满意度记录计算平均分和分布
4. **意图分布**：从会话历史按 `intent` 字段分组计数

**实时性：** 目前是内存实时聚合，每次请求时计算，延迟 < 100ms。如果数据量大，可以：
1. 引入 Redis 计数器（INCR 统计请求量、人工介入数）
2. 用 Prometheus Counter/Gauge 暴露指标，Grafana 面板直接读取
3. 定时任务（如每 5 分钟）把聚合结果写入缓存，仪表盘读缓存

**生产优化：** 接入 ClickHouse 或 Prometheus 做时序存储，支持历史趋势分析。

---

### Q46：人工客服工作台的设计思路是什么？AI 上下文摘要怎么生成？

**面试官意图：** 考察人工转接的完整流程、AI 辅助设计、用户体验。

**参考答案：**

**工作台核心流程：**
1. 用户点击"转人工"或系统判定需要人工 → 会话进入 `WAITING_HUMAN` 队列
2. 客服打开工作台 → SSE 实时推送等待队列
3. 客服点击"接受" → 会话状态变为 `HUMAN_CHAT`，用户收到"客服已接入"
4. 客服查看 AI 整理的上下文摘要 → 针对性回复
5. 客服点击"关闭服务" → 会话结束，推送满意度调查

**AI 上下文摘要包含：**
- 转接原因（用户主动/AI 判定/未解决）
- 紧急程度（基于用户情绪和问题类型）
- 已尝试方案（从对话历史提取 AI 尝试过的解决路径）
- 用户画像（VIP 等级、历史工单数）
- 当前卡点（AI 无法解决的具体障碍）

**设计要点：**
- 客服不需要翻完整对话历史，30 秒快速上手
- SSE 推送保证低延迟，不需要客服轮询
- 支持多客服并发，各自处理不同会话

---

### Q47：演示数据注入的设计考虑了什么？如何避免污染生产环境？

**面试官意图：** 考察开发效率工具设计、环境隔离意识。

**参考答案：**

`src/seed.py` 自动生成 5 类演示数据：工单（8 条）、客户（5 条）、满意度（6 条）、用户（4 角色）、通知（5 条）。

**设计考虑：**
1. **幂等注入**：每次启动检查 `if existing: return`，不重复生成
2. **业务关联**：工单关联客户、满意度关联工单，数据之间有真实业务逻辑
3. **覆盖全状态**：工单覆盖 open/in_progress/resolved/closed/cancelled，满意度覆盖 1-5 星
4. **独立模块**：只在 `server.py` 启动时调用，不耦合业务代码

**环境隔离：**
- 通过 `SEED_DEMO_DATA=false` 环境变量关闭
- 生产环境默认不注入，只在开发/测试环境启用
- 数据存储在内存（开发环境），重启即清空，不会持久化污染

---

## 十、简历话术模板

### 专业技能（推荐直接复制到简历）

```
- 熟练掌握 Python，熟悉 LangChain、LangGraph 等 Agent 开发框架，独立设计并实现企业级智能客服系统
- 深入理解 RAG 系统全链路：三层解耦插件化架构、5 种格式加载、混合检索（向量+BM25+RRF 融合）、双索引（标准粒度+句子窗口 Small2Big）、Milvus Partition Key 多租户隔离、增量同步、限流熔断
- 掌握 ReAct Agent 范式与 Loop Engineering：Function Calling 机制、推理循环收敛控制、动态 max_turns、蝴蝶效应治理
- 熟练使用 LangGraph 进行有状态工作流编排：v2.0 扁平化 8 节点单层 StateGraph、条件路由、Reflection 自我反思节点
- 实践云原生微服务架构：6 个微服务拆分、APISIX 网关（路由/限流/熔断）、RabbitMQ 异步解耦（4 队列+DLQ）、K3s + Helm 部署、GitLab CI + ArgoCD GitOps
- 精通 Agent 记忆管理架构：Redis 优先短期记忆（自动降级进程内存）、PG 持久化 + Milvus/Chroma 语义检索长期记忆、MemoryManager 三节点接入、90 天时间衰减加权
- 掌握 Agent 评估方法论：RAG 检索指标（Recall/Precision/MRR/F1）+ LLM-as-Judge 5 维评分 + 在线抽样 + 幻觉检测
- 实现 MCP 协议标准化 + A2A Agent 互联：HTTP MCP Server 3 工具注册、A2A Server Agent Card 3 Skill 发布、全链路验证
- 熟悉向量数据库：Chroma（开发）+ Milvus（生产，IVF_FLAT + COSINE + Partition Key），Chrom→Milvus 迁移脚本 + 双写验证
- 熟悉基础设施：PostgreSQL（9 表租户隔离）、Redis（分布式锁 Lua 脚本）、RabbitMQ（Topic Exchange + DLQ）、MinIO（对象存储+备份）
- 掌握可观测性体系：Prometheus（8 采集目标 + 8 告警规则）+ Grafana（12 面板 Dashboard）+ Loki 日志聚合
- 了解 Prompt Injection 攻击向量与防御体系、五层纵深防御 + 网关层限流防护
```

### 项目经历（推荐直接复制到简历）

> **企业级智能客服 Agent** | 独立开发 | 2026.06 - 2026.07
>
> 从零设计并实现了企业级智能客服系统，完成从单体 RAG 聊天机器人到云原生微服务架构的完整演进。覆盖 LangGraph 编排 + ReAct 推理 + RAG 检索 + 记忆管理 + 评估监控 + 安全防护 + MCP 工具互联 + A2A Agent 协作 + 云原生基础设施。
>
> **云原生微服务架构** — 将单体应用拆分为 6 个微服务（api-service / ws-service / rag-service / agent-worker / frontend / memory），通过 APISIX 网关统一入口（动态路由 + 限流 + 熔断 + Prometheus 指标），RabbitMQ 异步解耦（4 队列 Topic Exchange + DLQ 死信队列），K3s + Helm 部署（11 templates + 3 values files），GitLab CI 6 阶段流水线（lint/test/SAST/build/deploy-staging/deploy-prod）+ ArgoCD GitOps（staging 自动同步 / production 手动审批）。
>
> **RAG 知识库引擎（v0.4 三层解耦 + v0.5 多后端）** — 三层解耦插件化 RAG 架构：数据源层 → 加载器插件层（5 种格式装饰器自动注册）→ 处理管道层（链式处理器）。多后端支持：Chroma（开发零配置）/ Milvus（生产 IVF_FLAT + COSINE + Partition Key 多租户隔离）/ Remote HTTP。双索引混合检索（标准粒度+句子窗口 Small2Big + BM25 + RRF 融合），支持增量同步、限流熔断、PII 检测+权限自动升级。
>
> **LangGraph 工作流编排（v2.0 扁平化）** — 从 5 子图 6 层嵌套重构为 8 节点单层 StateGraph，0 子图 0 桥接函数。实现了动态 max_turns（FAQ=1 轮/Technical=5 轮/Complex=8 轮）、Reflection 自我反思节点、FAQ 豁免追问列表、A2A 远程委托扩展点。LLM 调用减少 60-80%。
>
> **ReAct + Loop Engineering** — 思考-行动-观察循环，按节点白名单暴露工具，并行工具调用。蝴蝶效应治理（router_node temperature=0）+ 收敛控制（硬性上限 + Prompt 停止条件 + Observation 元信号注入）。
>
> **三级记忆架构（Context Engineering）** — 短期记忆（Redis 7 优先 + LLM 摘要，内存 fallback）→ 长期记忆（PG 持久化 + Milvus/Chroma 语义检索 + 用户画像自动聚合）→ MemoryManager 三节点接入。
>
> **五层安全纵深防御 + 网关防护** — 输入规则检测 → APISIX 网关限流 → 编排护栏（节点级工具白名单）→ Agent 护栏（Observation 清洗）→ 输出校验（PII + 幻觉检测）+ 审计日志（PG audit_logs 表）。
>
> **MCP 工具互联 + A2A Agent 协作** — HTTP MCP Server 3 工具注册（已验证全链路）。A2A Server Agent Card 3 Skill 发布 + REST message/send 委托全链路验证 + delegate_to_expert() 跨 Agent 任务分发。
>
> **多维评估体系 + 可观测性** — RAG 检索指标（Recall/Precision/MRR/F1）+ LLM-as-Judge 5 维评分 + 在线抽样 + 幻觉检测。Prometheus（8 采集目标 + 8 告警规则）+ Grafana（12 面板 Dashboard）。
>
> **业务系统模块（v2.0）** — 4 级 RBAC 权限体系（Super Admin/Admin/Agent/Viewer，15 个权限点），工单全生命周期管理（状态机 open→in_progress→resolved/closed/cancelled，不可变约束），客户画像与标签管理，CSAT 满意度调查（1-5 星 + 标签 + 文字留言），通知中心（按角色/用户精准推送），数据仪表盘（KPI 聚合 + 实时活动 + 客服绩效排行），人工客服工作台（SSE 实时队列 + AI 上下文摘要 + 回复/关闭）。React + TypeScript 前端管理后台，多标签页 + 权限守卫。
>
> **数据架构** — PostgreSQL 16（9 表，tenant_id 租户隔离）+ Milvus Standalone（向量）+ MinIO（文档/日志/备份）+ Redis 7（缓存/分布式锁 Lua 脚本/限流）。
>
> **代码规模**：14,707+ 行 Python，90+ 模块，24 子包；前端 2,000+ 行 TypeScript/React；2,471 行部署配置，30 配置文件；3 Dockerfiles；12 服务 docker-compose；48 测试（45 passed）
>
> **技术栈**：Python / LangGraph / LangChain / FastAPI / React / TypeScript / Milvus / Chroma / PostgreSQL / Redis / RabbitMQ / MinIO / APISIX / Docker / K3s / Helm / GitLab CI / ArgoCD / Prometheus / Grafana / 阿里百炼 Qwen / MCP / A2A
>
> **GitHub**：github.com/addhai/enterprise-agent

---

## 十一、行为面试问题

### Q25：项目中遇到的最大技术难点是什么？

**参考答案：**

有两个：

**第一个是 RAG 子系统的重构**——从单体 DocumentLoader 到三层解耦插件化架构。分析了数据流，识别出三个独立关注点（数据源/加载器/处理管道），通过装饰器自动注册和链式管道重构。结果：新增格式的成本从"改核心类"降到"加一个类 + 一行 import"。

**第二个是 v2.0 多智能体架构扁平化**——发现 5 个子图嵌套 6 层 StateGraph 的问题：桥接函数在 6 种 State 之间转换导致状态混乱，FAQ 子图和 tools.py 功能重复，追问在路由之前执行导致 FAQ 被误判。修复：合并 classify_node + 合并 FAQ handler + 追问仅对 technical 意图生效。结果：净减 ~700 行代码，LLM 调用减少 60-80%。

**面试要点：** 按"发现问题 → 排查过程 → 修复方案 → 结果"的结构讲。展示架构思维。

---

### Q26：如果重新做这个项目，你会怎么做？

**参考答案：**

三个改进方向：

1. **测试覆盖前置：** RAG 重构后有 90 个源文件，但测试还是 48 个。应该在重构前就建立集成测试基线。

2. **可观测性先行：** LangSmith 集成得太晚了。应该在第一行业务代码之前就配好 Tracing + Prometheus metrics，这样早期的 Agent 行为问题可以更快定位。

3. **从一开始就做好微服务边界：** 第一版是把所有能力塞进一个 FastAPI 进程。如果重来，一开始就按业务边界拆——api-service（接口层）、rag-service（检索层）、agent-worker（推理层），用 RabbitMQ 解耦。这比事后拆分省很多返工。

**面试要点：** 说"应该先做 X"比说"我做了 X"展示更深的理解力——因为你知道为什么顺序重要。

---

## 十二、云计算与微服务架构

### Q27：你的项目从多子图架构改成了什么？

**参考答案：**

v2.0 做了重大架构重构——把 **5 个独立 LangGraph 子图 + 1 个编排父图** 扁平化为 **1 个单层 StateGraph + 8 个节点**。

**重构前的问题：**
- 5 个子图（FAQ/RAG/Reflect/Chat/Expert）各自独立 StateGraph，嵌套了 6 层
- 桥接函数在 6 种 State 之间来回转换，状态混乱
- FAQ 子图和 tools.py 的 `search_faq` 功能重复
- 追问逻辑在路由之前执行，FAQ 问题被误判为需要追问
- 子图编译带来不必要的 State 序列化开销

**重构后的架构：**
```
entry → classify → {faq_handle | rag_handle | human}
                           ↓
                   reflect? → reply → END
                           ↓
                   expert? → reflect → reply

8 个节点，0 个子图，0 个桥接函数
```

**核心改进：**
1. 合并 classify 节点 — 把 clarify_node + router_node 合并为一个，先意图分类再决定是否需要追问
2. FAQ 豁免列表 — 密码重置、SSO 配置、403 错误等不触发追问
3. 情绪检测前置 — 愤怒/紧急用户直接标记
4. 追问仅对 technical 意图生效
5. Handler 是普通函数 — 不再编译为 StateGraph
6. 保留 expert_delegate — A2A 远程委托作为扩展点

**面试要点：** 展示你理解"多智能体"的本质是职责分离，不是子图嵌套。LLM 调用减少 60-80%。

---

### Q28：多智能体架构中，什么时候该用子图，什么时候不该用？

**参考答案：**

**用子图的场景：**
- 子图内部有复杂的循环（比如 RAG 的 ReAct 多轮推理）
- 子图需要独立部署或独立扩展（比如专家委托服务）
- 子图需要独立的状态管理和 checkpoint

**不该用子图的场景：**
- 只是简单的关键词匹配（FAQ 就是个 dict 查找，不值得编译成 StateGraph）
- 逻辑简单且不会被独立调用（闲聊回复直接一个 if 语句就够了）
- 子图之间只是顺序调用，没有独立的状态管理需求

**我的判断标准：**
> 如果一个子图内部超过 3 个节点、有循环、需要独立部署，就用子图。否则就是一个普通函数。

**面试要点：** 展示你有架构权衡的思维，不是盲目追求"多智能体"的形式。

---

### Q29：追问逻辑的 bug 是怎么发现的？怎么修的？

**参考答案：**

**Bug 现象：** 用户说"怎么重置密码"，系统反问"请提供 SDK 版本和操作系统"。

**根因分析：**
- `clarify_node` 在 `router_node` 之前执行
- `_detect_missing_info` 看到"怎么"就认为是"排查类问题"，要求提供技术环境
- 但"重置密码"是标准 FAQ，不需要追问

**修复方案：**
1. 合并 `clarify_node` + `router_node` → `classify_node`，先意图分类再决定追问
2. 加 FAQ 豁免列表，密码重置、SSO 配置、403 错误等不走追问
3. 追问仅对 `intent=technical` 触发，FAQ 和 casual 直接放行

**面试要点：** 能说出具体 bug 和修复过程，证明你真实调试过系统。

---

### Q30：重构后架构有什么优势？

**参考答案：**

1. **代码更少** — 删除 5 个子图（~700 行），净减 ~700 行
2. **调试更容易** — 一个 StateGraph，打断点就能走完全流程
3. **LLM 调用更少** — reflect_handler 只在 quality_score 不确定时调用 LLM，减少 60-80%
4. **职责更清晰** — 每个 handler 文件定义一个 Agent 的职责，workflow.py 定义执行流程
5. **扩展性更好** — 如果某个 handler 变复杂，可以随时升级为独立子图
6. **与微服务架构协同** — 扁平化的编排层更适合被 agent-worker 通过 RabbitMQ 异步消费

**面试要点：** 展示你不仅会写代码，还会做架构决策和权衡。

---

## 十三、云原生与微服务架构

### Q31：为什么把单体拆成 6 个微服务？怎么决定拆分边界的？

**参考答案：**

按照 **业务边界 + 数据所有权 + 独立变更频率 + 资源需求差异** 四个维度拆：

| 服务 | 职责 | 拆分理由 | 扩容策略 |
|------|------|----------|----------|
| api-service | REST API + LangGraph 编排 | 同步入口，I/O 密集 | HPA by CPU 70% |
| ws-service | WebSocket 长连接管理 | 连接状态与 HTTP 无关，内存占用不同 | HPA by 连接数 |
| rag-service | 文档加载/切块/嵌入/检索 | CPU 密集（Embedding 计算），变更频率低 | HPA by QPS |
| agent-worker | RabbitMQ 异步消费推理任务 | LLM 调用 3-10s，必须异步解耦；资源需求最大（CPU/内存） | KEDA by 队列深度 |
| frontend | React SPA 静态文件 | 无状态，与业务逻辑完全无关 | 多副本 |
| memory（内嵌） | 记忆管理 | 当前内嵌在 api-service，独立后可独立扩容 + 读写分离 | 未来独立 |

**拆分边界判断标准：**
- 变更频率不同 → 拆（rag-service 的检索逻辑很少变，api-service 的路由频繁变）
- 资源需求不同 → 拆（agent-worker 需要 4G 内存跑 LLM，frontend 只需要 128M）
- 数据所有权不同 → 拆（rag-service 独有向量库，其他服务不直接访问 Milvus）
- 故障隔离 → 拆（rag-service 挂了不影响 WebSocket 连接）

**为什么不是 50 个微服务？** 微服务不是越细越好。这个项目 QPS < 100，6 个服务已经是合理粒度。过度拆分会带来服务间通信开销、分布式事务复杂性、运维负担。判断标准：一个服务是否能由一个小团队（或一个人）独立维护？如果能，就别再拆。

**面试要点：** 展示你对"合理的微服务粒度"有判断力——不是微服务越多越好。

---

### Q32：APISIX 网关相比 Nginx 有什么区别？为什么选 APISIX？

**参考答案：**

项目最初用的是 Nginx 做反向代理，在生产化过程中替换为 APISIX。核心区别：

| 维度 | Nginx | APISIX |
|------|-------|--------|
| 配置变更 | 需要 reload（有损，丢连接） | 热加载，毫秒级生效，不丢流量 |
| 动态路由 | 不支持（需 OpenResty+Lua 扩展） | 原生支持，Admin API 动态下发 |
| 限流熔断 | 需要额外模块（limit_req 仅 IP 维度） | 内置 limit-count / api-breaker 插件 |
| 鉴权 | 需 Lua 脚本 | 内置 jwt-auth / key-auth 插件 |
| 可观测性 | 需额外 nginx-module-vts | 内置 prometheus 插件 |
| 插件生态 | 弱，Lua 开发门槛高 | 丰富，支持 Lua/Java/Python/Go/Wasm 多语言 |

**APISIX 在本项目中的实际配置：**
- 4 条路由：前端静态文件（/* 兜底）、REST API（/api/v1/chat，限流 20req/s/user + 熔断）、通用 API（/api/v1/*，限流 50req/s）、WebSocket（/ws/*，长连接超时 86400s）
- 全局插件：prometheus（指标导出）、http-logger（审计日志回调到 api-service）
- Standalone 模式：不依赖 etcd 集群，适合小规模部署（K3s 单机），未来可切换到 etcd 模式
- 内部服务间调用：Consumer + key-auth 鉴权

**为什么没选 Kong / Traefik：** Kong 需要 PostgreSQL 做配置存储（多一个依赖），Traefik 的插件生态不如 APISIX 丰富。APISIX 的 standalone 模式不需要 etcd，和 K3s 单机部署完美契合。

**面试要点：** 展示你对网关选型有实际对比，不只是"会用 Nginx 配 proxy_pass"。

---

### Q33：RabbitMQ 在你的系统里做什么？为什么不用 Kafka？

**参考答案：**

**RabbitMQ 在系统中的角色：**

用一个 Topic Exchange（`agent.tasks`）路由 4 条业务队列：

| 队列 | Routing Key | 消费者 | 任务 |
|------|-------------|--------|------|
| agent.inference.queue | agent.inference.* | agent-worker | LLM 推理（3-10s 耗时任务） |
| memory.persist.queue | memory.persist | memory-service | 长期记忆持久化 |
| rag.index.queue | rag.index.* | rag-service | 文档入库、向量化 |
| notify.push.queue | notify.* | channel-service | 微信/邮件推送通知 |

每条队列都配置了 DLQ（死信队列）：`agent.dlx` Topic Exchange + 对应 `.dlq` 队列。消息处理失败后自动转入 DLQ，保留 24 小时（TTL 86400000ms），人工排查后重放。

**优先级支持：** `agent.inference.queue` 配置 `x-max-priority: 10`，紧急用户请求可以插队处理。

**为什么不用 Kafka：**

| 维度 | RabbitMQ | Kafka | 本项目场景 |
|------|----------|-------|------------|
| 消息量 | 万/秒 | 百万/秒 | 百/秒 → RabbitMQ 绰绰有余 |
| 延迟 | 毫秒级 | 百毫秒级 | 客服对话需要低延迟 |
| 运维复杂度 | 简单（单节点即可生产） | 复杂（ZK/KRaft + Broker 集群） | 小团队，一个人维护 |
| 消息重试 | 原生 DLX + TTL + 死信队列 | 需自行实现 | 这正是我们需要的 |
| 消息优先级 | 原生支持（x-max-priority） | 不支持 | 紧急消息需要插队 |
| 协议 | AMQP 0-9-1（标准协议） | 自定义协议 | 多语言生态友好 |

**核心判断：** Kafka 是"大数据管道"（日志/埋点/流处理），RabbitMQ 是"任务分发器"（业务消息/任务调度）。一个客服系统的推理任务队列不需要 Kafka 的吞吐量，但需要 RabbitMQ 的灵活路由、优先级、DLQ 重试机制。

**面试要点：** 展示你理解"选型取决于场景"——不是哪个热门用哪个。

---

### Q34：K3s 和完整 K8s 的区别？为什么用 K3s 而不是直接用 Docker Compose 上生产？

**参考答案：**

**K3s vs 完整 K8s：**

| 维度 | K3s | 完整 K8s (kubeadm) |
|------|-----|---------------------|
| 二进制大小 | < 100MB | > 1GB |
| 内存占用 | ~512MB | ~2GB+ |
| 数据库 | 内置 SQLite（可切换 etcd） | etcd 集群 |
| 组件 | 精简合并为一个二进制 | 多组件独立部署 |
| 安装 | `curl -sfL https://get.k3s.io | sh` 一行命令 | 复杂多步骤 |
| 适用 | 边缘计算 / 单机生产 / 小团队 | 大型集群 / 多租户 |

K3s 是 CNCF 沙箱项目，通过了完整的 K8s 一致性认证——所以它就是一个"轻量但完全兼容的 K8s"。

**为什么不是 Docker Compose 上生产：**

Docker Compose 适合开发和单机测试，但生产环境缺了关键能力：
- 没有自愈能力（Pod 挂了不会自动重启到健康状态）
- 没有滚动更新（更新需要停机，或手动蓝绿部署）
- 没有 HPA 自动伸缩（流量上来只能手动扩容）
- 没有配置管理（ConfigMap / Secret 的版本控制和热更新）
- 没有统一的资源调度（CPU/内存限制和请求无法全局规划）

**本项目的实际部署演进：**

```
Docker Compose（开发阶段）→ K3s + Helm（单机生产）
```

Docker Compose 仍在用——开发环境 `docker compose up -d` 一键启动全部 12 个服务。但在 K3s 上通过 Helm Chart 部署生产环境：
- values.yaml（基础配置）+ values-staging.yaml（测试覆盖）+ values-prod.yaml（生产覆盖）
- 生产配置：api-service 3 副本 + HPA（min 3 / max 10）、agent-worker 3 副本 + HPA（min 3 / max 10）
- 测试配置：全部 1 副本，不启用 HPA，资源缩到最小

**面试要点：** 展示你理解 Docker Compose 和 K8s 各自的适用场景——不是 K8s 适合一切。

---

## 十四、向量库迁移

### Q35：为什么从 Chroma 迁移到 Milvus？迁移过程怎么保证数据一致性？

**参考答案：**

**为什么要迁移：**

| 维度 | Chroma | Milvus |
|------|--------|--------|
| 分布式 | 单机 | 天然分布式 |
| 多租户 | 需手动分区 | Partition Key 原生物理隔离 |
| 索引类型 | HNSW 单一 | IVF_FLAT / HNSW / DiskANN 等 12 种 |
| 持久化 | 本地 SQLite 文件 | S3/MinIO 对象存储 |
| 混合查询 | 检索后 Python 侧过滤 | 标量过滤 + 向量检索一条语句 |
| 监控 | 无 | Prometheus 原生 metrics 端点 |
| 生产就绪 | PoC 级别 | 企业级（Zilliz 商业支持） |

核心痛点：Chroma 的 SQLite 文件存在本地磁盘，单机挂了数据就没了。Milvus 用 MinIO 做对象存储，数据持久性和可靠性高一个量级。

**迁移脚本：** `scripts/migrate_chroma_to_milvus.py`

**四步迁移策略：**

**Step 1 — Dry Run：** 预览所有文档，不实际写入
```
python scripts/migrate_chroma_to_milvus.py --dry-run
```

**Step 2 — 正式迁移：** 从 Chroma 读取所有文档 + metadata，用同一个 Embedder 重新向量化（因为 Chroma 不暴露原始向量），批量写入 Milvus

**Step 3 — 双写验证：** 用 7 个预定义查询对比 Chroma 和 Milvus 的 Top-5 检索结果。通过标准：60% 以上重叠（重 Embed 后分数有微小差异，不比较分数只比较内容）

**Step 4 — 人工确认 + 清理：** 验证通过率 >= 80% 后，保留 Chroma 数据 30 天作为回滚保险

**为什么需要重 Embed：** Chroma 的 `collection.get()` 可以拿到 embeddings，但因为 Chroma 内部对 embedding 可能有精度损失，稳妥做法是用同一个 Embedder 重跑。保证一致性。

**面试要点：** 展示你考虑了迁移的风险控制——dry-run → 迁移 → 双写验证 → 回滚保险，而不是一把梭。

---

### Q36：Milvus 的 Partition Key 是怎么做多租户隔离的？

**参考答案：**

Milvus 的 Partition Key 是一种物理隔离机制——指定某个字段为 Partition Key 后，Milvus 会根据该字段的哈希值将数据分配到不同的分区（Partition），每个分区物理独立存储。

**本项目的 Schema 设计：**

```python
FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=100,
            is_partition_key=True,  # 关键：声明为 Partition Key
            description="租户 ID")
```

**检索时的自动隔离：**

```python
# 查询时只需加过滤条件，Milvus 自动路由到对应分区
expr = f'tenant_id == "{tenant_id}" and access_level in ["public", "internal"]'
results = coll.search(data=[query_embedding], anns_field="embedding",
                       expr=expr, limit=top_k, ...)
```

**为什么比 Chroma 的方案好：**

- **Chroma：** 所有租户数据存在一个 Collection 里，通过 metadata 字段 `tenant_id` 做检索后过滤——数据量大了之后，需要扫描全量数据再过滤，性能线性下降
- **Milvus Partition Key：** 查询时直接路由到对应租户的分区，只扫描该租户的数据——等效于每个租户独占一个逻辑分区，O(1) 定位

**额外好处：** `delete_by_tenant(tenant_id)` 可以直接删除整个租户的所有向量数据，符合 GDPR "被遗忘权"要求。

**面试要点：** 展示你理解"逻辑隔离"（Chroma metadata 过滤）和"物理隔离"（Milvus Partition Key）的区别，以及 GDPR 合规考量。

---

## 十五、分布式系统

### Q37：Redis 分布式锁怎么实现的？Lua 脚本保证了什么？

**参考答案：**

封装了 `RedisLock` 类（`src/infrastructure/redis_lock.py`），基于 Redis `SET NX EX` 实现。

**加锁：**
```python
acquired = client.set(lock_key, owner_id, nx=True, ex=ttl)
# 仅当 key 不存在时设置（NX），并设过期时间（EX）
```

**释放锁（Lua 脚本保证原子性）：**
```lua
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
```

**Lua 脚本解决了什么问题：**

如果不用 Lua，释放锁需要两步操作：
```python
# 危险！非原子操作
value = redis.get(key)
if value == my_owner_id:
    redis.delete(key)  # 在这两步之间锁可能过期，删了别人的锁
```

Lua 脚本在 Redis 服务端原子执行，保证"检查归属者"和"删除"之间不会被其他命令插入——这是 Redlock 算法的核心思想。

**三个应用场景：**
1. **知识库索引更新锁** (`lock:index:{kb_id}`，TTL 120s，自动续期)：防止并发写入导致向量重复
2. **长期记忆去重锁** (`lock:memory:{session_id}:round_{n}`，TTL 30s)：防止同一轮对话被多次持久化
3. **租户配额扣减锁** (`lock:quota:{tenant_id}:{resource}`，TTL 10s)：防止并发扣减导致配额超扣

**特性：**
- 自动续期（renew_interval = TTL * 0.7，长时间操作不会锁过期）
- 锁持有者标识（UUID + 时间戳，防止误释放）
- 非阻塞模式 + 重试模式（默认重试 3 次，间隔 0.1s）
- 上下文管理器支持（`with RedisLock(...) as acquired:`）

**局限性（诚实说明）：** Redis 是 AP 系统，不适用于严格的一致性场景。如果需要 CP 保证，用 PostgreSQL Advisory Lock。

**面试要点：** 说出"为什么需要 Lua 脚本"——非原子的 get + delete 会误删别人的锁。这是 Redis 分布式锁面试的核心考点。

---

### Q38：你的系统有哪些降级策略？

**参考答案：**

系统在多个层面实现了降级：

**1. 向量库降级（Milvus → Chroma → 内存）**

```python
# HybridRetriever 懒加载 Milvus，失败自动降级
@property
def milvus_store(self):
    try:
        return MilvusVectorStore(host=..., port=...)
    except Exception:
        logger.warning("Milvus unavailable, fallback to Chroma")
        return self.vector_store  # 降级到 Chroma
```

**2. 短期记忆降级（Redis → 进程内存）**

```
Redis 优先（会话缓存 + LLM 摘要）
  → Redis ping 失败 → 自动降级为进程内存字典
```

**3. 长期记忆降级（PG + Milvus/Chroma → 内存字典 + 关键词匹配）**

```
PG 优先（持久化）→ PG 不可用时降级为内存字典
Chroma/Milvus 优先（语义检索）→ 不可用时降级为 TF + 时间衰减关键词匹配
```

**4. LLM 摘要降级（LLM → 关键词提取）**

```
LLM 结构化摘要优先 → LLM API 不可用时降级为关键词提取
```

**5. 网关层熔断降级**

```
APISIX api-breaker: 连续 5 次 5xx → 熔断 30 秒 → 直接返回 503
（避免请求打到已经故障的后端，保护系统）
```

**6. RAG 远程调用降级**

```
RagClient: HTTP 调用 rag-service → 重试 3 次 → 熔断器打开 → 返回空结果
（api-service 收到空结果后走"无相关知识"的回复逻辑）
```

**7. OCR 管线降级**

```
阿里百炼 Qwen-VL 视觉理解优先 → API 不可用时降级到 Paddle OCR → 再降级到 Tesseract
```

**设计原则：** 每个外部依赖都有 fallback。核心链路（对话回复）不能因为一个依赖挂了就完全不可用——优雅降级比直接报错好。

**面试要点：** 展示你对分布式系统"部分失败"的认知——在微服务架构中，依赖方不可用是常态而非异常。

---

## 十六、CI/CD 与 GitOps

### Q39：GitLab CI 的 6 阶段流水线是怎么设计的？

**参考答案：**

完整流水线在 `.gitlab-ci.yml` 中定义，6 个阶段：

```
代码提交 (Push/MR to main)
  │
  ▼
Stage 1: Lint (代码检查)
  ├── python-lint: ruff check + ruff format --check
  └── frontend-lint: oxlint
  │
  ▼
Stage 2: Test (单元测试)
  ├── python-test: pytest -v --cov=src (Redis + PG service containers)
  └── frontend-test: vitest run
  │
  ▼
Stage 3: SAST (安全扫描)
  ├── python-security: bandit + semgrep scan
  └── container-scan: Trivy config scan (HIGH/CRITICAL 阻断)
  │
  ▼
Stage 4: Build (Docker 构建)
  ├── build-api:    docker build + push (tag: commit SHA + latest)
  ├── build-rag:    docker build + push
  ├── build-worker: docker build + push
  └── build-frontend: npm run build (产物 archive)
  │
  ▼
Stage 5: Deploy Staging (自动)
  ├── 更新 values-staging.yaml 中的 image tag
  ├── git commit + push → ArgoCD 检测到变更 → 自动 sync
  └── 触发条件: push to main
  │
  ▼
Stage 6: Deploy Production (手动审批)
  ├── 更新 values-prod.yaml 中的 image tag
  ├── git commit + push → ArgoCD Application 手动触发 sync
  ├── 触发条件: git tag v*.*.* (语义化版本)
  └── when: manual (需要人工点击确认)
```

**关键设计决策：**
- **ruff 替代 flake8+black：** 速度 10x，一个工具同时做 lint + format
- **BuildKit 构建：** `DOCKER_BUILDKIT=1`，多阶段构建 + 层缓存，每次构建增量 30s 内完成
- **镜像标签策略：** commit SHA（不可变 + 可追溯）+ latest（开发环境自动拉取）
- **Staging 自动部署、Production 手动审批：** 分离部署权限，防止误操作直接上生产
- **缓存策略：** `.pip-cache/` 和 `frontend/node_modules/` 按 `CI_COMMIT_REF_SLUG` 缓存

**面试要点：** 展示你理解 CI/CD 流水线的每个阶段的意图——不是把命令堆在一起。

---

### Q40：ArgoCD 的 GitOps 流程是什么？staging 和 production 有什么区别？

**参考答案：**

**GitOps 核心理念：** Git 仓库是唯一的真理来源（Single Source of Truth）。集群状态 = Git 仓库中声明的期望状态。

**完整流程：**

```
开发者 push 代码到 GitLab main 分支
  │
  ▼
GitLab CI 触发流水线 (lint → test → SAST → build → push image)
  │
  ▼
GitLab CI 更新 deploy/helm/.../values-staging.yaml (改 image tag)
  │
  ▼
GitLab CI git commit + push 到 main
  │
  ▼
ArgoCD 每 3 分钟 Poll Git 仓库
  │
  ▼
检测到 values 文件变更（diff）
  │
  ▼
ArgoCD 自动 sync → kubectl apply → 滚动更新 Pod
  │
  ▼
健康检查 (Readiness Probe) 通过 → 部署完成
```

**Staging 和 Production 的核心区别：**

| 维度 | Staging | Production |
|------|---------|------------|
| syncPolicy.automated | `prune: true, selfHeal: true` | `automated: {}`（不自动同步） |
| 触发方式 | 自动（GitLab CI 触发 hard refresh） | 手动（GitLab CI `when: manual`） |
| 触发条件 | push to main | git tag v*.*.* 格式 |
| namespace | agent-staging | agent-prod |
| values file | values-staging.yaml | values-prod.yaml |
| 资源配额 | 最小（1 副本，128Mi） | 生产（3 副本，512Mi-2Gi） |
| HPA | 关闭 | 开启（min 3 / max 10） |
| LLM 模型 | qwen-plus | qwen-max |
| LangSmith Tracing | 开启 | 开启 |
| 在线评估抽样率 | 30% | 10% |
| 证书 | letsencrypt-staging | letsencrypt-prod |
| sync retry | 5 次 (3min max) | 3 次 (5min max) |
| selfHeal | 开启（自动修复配置漂移） | 关闭（手动控制变更） |

**为什么 production 不启用 auto-sync：** 生产环境不能允许 Git 变更自动应用到集群——需要人工确认部署窗口、观察监控指标、准备回滚方案。ArgoCD 的 `automated: {}`（空对象）+ GitLab CI `when: manual` 实现双重人工审批。

**面试要点：** 展示你理解 GitOps 的本质是"Git 作为真理来源"，以及 staging/production 的策略差异化。

---

## 十七、可观测性与监控

### Q41：你的 Prometheus 监控了哪些指标？Grafana Dashboard 上最关注什么？

**参考答案：**

**Prometheus 采集的 8 个目标：**

| 采集目标 | 来源 | 关键指标 |
|----------|------|----------|
| APISIX | apisix:9092/metrics | HTTP 请求量/延迟/状态码、限流/熔断状态 |
| api-service | api-service:8000/api/v1/metrics | 对话请求量、LLM 调用次数/成功率、RAG 检索延迟 |
| rag-service | rag-service:8001/metrics | 检索 QPS、检索延迟、文档索引状态 |
| ws-service | ws-service:8000 | WebSocket 活跃连接数 |
| Milvus | milvus:9091/metrics | Collection 实体数、搜索延迟、内存使用 |
| PostgreSQL | pg-exporter:9187 | 连接数、查询延迟、慢查询 |
| Redis | redis-exporter:9121 | 内存使用率、命中率、连接数 |
| RabbitMQ | rabbitmq:15692/metrics | 队列深度、消息速率、消费者数 |

**Grafana Dashboard 12 面板布局（最关注的 5 个）：**

1. **Services Status（顶部横幅）：** `count(up == 1) / count(up)` — 一眼看到有没有服务挂了
2. **API Latency P50/P95/P99：** P95 > 2s 触发告警 — 95% 的用户请求延迟是最重要的 SLO
3. **LLM Call Success Rate（仪表盘）：** < 90% 黄灯，< 90% 红灯 — LLM API 是最脆弱的依赖
4. **RabbitMQ Queue Depth（时序图）：** agent.inference.queue 堆积 > 100 → 触发告警 → 需要扩容 worker
5. **API Error Rate（5xx 占比）：** > 5% 触发 critical 告警 — 5xx 是用户直接感知到的故障

**其他面板：** HTTP Status Distribution（状态码分布堆叠图）、Active WebSocket Connections（连接数趋势，>800 告警）、RAG Search Latency（检索 P95 延迟）、Milvus Collection Stats（总切片数）、Redis Memory Usage（内存使用率仪表盘）、Conversation Quality Score（LLM-as-Judge 评分趋势）、Alert Events（最近 1 小时告警表格）

**面试要点：** 展示你不只是"配了 Prometheus + Grafana"，而是知道看什么、什么指标对应什么业务含义。

---

### Q42：告警规则是怎么设计的？什么情况会触发告警？

**参考答案：**

告警规则文件 `deploy/monitoring/prometheus/alerts.yml`，两层粒度：

**Critical 级别（需要立即响应）：**

| 告警 | 触发条件 | 持续时间 |
|------|----------|----------|
| ServiceDown | `up == 0`（任何服务挂了） | 2 分钟 |
| HighErrorRate | API 5xx 错误率 > 5% | 5 分钟 |
| CircuitBreakerOpen | APISIX 熔断器触发 | 1 分钟 |

**Warning 级别（需要关注，但不需要半夜叫醒）：**

| 告警 | 触发条件 | 持续时间 |
|------|----------|----------|
| HighLatency | API P95 延迟 > 2秒 | 5 分钟 |
| LLMCallFailures | LLM API 调用失败率 > 10% | 3 分钟 |
| QueueBacklog | 推理队列积压 > 100 条消息 | 10 分钟 |
| RedisHighMemory | Redis 内存使用 > 85% | 5 分钟 |
| HighWSConnections | WebSocket 连接数 > 800（上限 1000） | 5 分钟 |

**设计原则：**

1. **告警分级：** Critical 级别需要立即响应（服务挂了、熔断了），Warning 级别可以在工作时间处理（延迟上升、队列积压）
2. **消除抖动：** 每个告警都有 `for` 持续时间（1-10 分钟），防止瞬时抖动误报
3. **面向排障：** 告警的 `description` 中包含具体数值和建议操作。例如 "推理队列积压 {{ $value }} 条消息，可能需要扩容 worker"
4. **覆盖全链路：** 网关层 → 服务层 → 中间件层（RabbitMQ/Redis）→ 数据层（Milvus/PG），每一层都有监控
5. **暂不接 Alertmanager：** 当前项目个人维护，告警通过 Grafana 面板直接查看。未来多副本生产环境再接入 Alertmanager + 钉钉/飞书通知

**面试要点：** 展示你的告警设计不是"想到什么配什么"，而是有分级、有持续时间、有 actionable description。

---

## 十八、数据架构

### Q43：PostgreSQL 的 9 张表分别存什么？租户隔离怎么做的？

**参考答案：**

Schema 文件：`deploy/postgres/init/01-schema.sql`

| 表名 | 存储内容 | 关键字段 |
|------|----------|----------|
| tenants | 租户基本信息 | id, slug, plan (free/pro/enterprise), settings (JSONB) |
| users | 租户下的用户账号 | tenant_id (FK), external_id, roles, access_levels, profile (JSONB) |
| knowledge_bases | 租户的知识库 | tenant_id (FK), doc_count, chunk_count, status |
| conversations | 对话会话记录 | tenant_id (FK), user_id (FK), session_id, channel (web/wechat/phone), status |
| messages | 每条对话消息 | tenant_id (FK), conversation_id (FK), role, content, intent, metadata (JSONB) |
| long_term_memories | 用户级长期记忆 | tenant_id (FK), user_id (FK), topic, content, importance (0-1), expired_at |
| quality_evaluations | LLM-as-Judge 评分 | tenant_id (FK), conversation_id (FK), score_overall/accuracy/completeness/safety/helpfulness, flags |
| audit_logs | 安全审计日志 | tenant_id (FK), user_id (FK), action, resource_type, ip_address, severity, details (JSONB) |
| rate_limits | 限流记录（PG 备选） | tenant_id (FK), user_id (FK), endpoint, window_start, request_count |

**租户隔离策略：**

- **每张表都有 `tenant_id` 列：** 作为逻辑外键关联到 `tenants` 表
- **应用层过滤：** 所有查询自动带上 `WHERE tenant_id = $current_tenant_id`，通过 SQLAlchemy session 的事件监听器注入
- **索引优化：** 所有高频查询的索引都以 `tenant_id` 为前缀（如 `idx_users_tenant`、`idx_conv_tenant` 等），保证租户内查询高效
- **为什么不用 RLS（Row Level Security）：** RLS 是 PG 层面的行级安全策略，但会带来额外的查询规划开销。对于本项目 QPS < 100 的场景，应用层过滤足够 + 更灵活（可以跨租户查询做运维分析）
- **Milvus 侧的租户隔离：** `tenant_id` 作为 Partition Key 实现物理隔离（见 Q36），与 PG 的逻辑隔离互补

**面试要点：** 展示你对 PG RLS vs 应用层过滤的取舍有清晰判断，以及 PG + Milvus 双层租户隔离的完整方案。

---

### Q44：数据备份策略是什么？

**参考答案：**

备份脚本：`scripts/backup.sh`，支持三种备份模式：

**1. PostgreSQL 备份：**
- Schema-only dump（DDL 结构定义）
- Full data dump（custom 格式，compress=9 压缩）
- 自动上传到 MinIO `agent-backups` bucket，路径 `backups/postgres/{YYYY-MM-DD_HHmmss}/`
- 本地保留 7 天，MinIO 侧启用版本控制（无限期保留历史版本）

**2. MinIO 备份：**
- 跨 bucket 快照：将 `agent-docs`、`agent-logs`、`agent-models` 三个 bucket 的对象拷贝到 `agent-backups`
- 每次备份限制 1000 个对象

**3. Milvus 备份：**
- 因为 Milvus Standalone 数据实际存储在 MinIO 中（`milvus-bucket`），所以 MinIO 备份已经覆盖了向量数据
- 额外导出 Collection Schema + 统计信息（总切片数、时间戳）作为元数据备份

**自动化：**
- `bash scripts/backup.sh cron` → 设置 crontab，每天凌晨 2:00 自动执行全量备份
- 备份日志写入 `logs/backup.log`

**恢复流程：**
1. 从 MinIO `agent-backups` 下载最近的备份文件
2. PG 恢复：`pg_restore -d agent data.dump` + `psql -d agent -f schema.sql`
3. MinIO 恢复：从 `agent-backups` 拷贝回对应 bucket
4. Milvus 恢复：数据在 MinIO 中，Milvus 重启后自动加载

**备份范围：** PostgreSQL（业务数据）+ MinIO（文档/日志/模型）+ Milvus（向量数据，通过 MinIO 间接备份）。不备份 Redis（缓存，可重建）。

**面试要点：** 展示你对"什么该备份、什么不该备份"有判断——备份业务数据（PG + MinIO），不备份缓存（Redis）。

---

## 附录：面试高频概念速查

| 概念 | 一句话解释 |
|------|-----------|
| RAG | 给 LLM 外挂"产品文档查询能力"，弥补训练数据没有私有知识的问题 |
| Embedding | 把文本变成向量，意思越近的两个文本向量距离越近 |
| HNSW | 向量检索底层算法：建高速公路 → 快速逼近 → 局部精细搜索 |
| IVF_FLAT | Milvus 索引：先聚类（IVF）再精确搜索（FLAT），适合百万级，比 HNSW 省内存 |
| Partition Key | Milvus 物理分区机制，按字段哈希值将数据分配到独立分区，实现多租户隔离 |
| ReAct | LLM 的思考-行动-观察循环，让 Agent 会"查资料"而不是"凭空编" |
| Function Calling | LLM 被训练出"遇到需要外部信息时输出 JSON 工具调用"的模式 |
| LangGraph | 把 Agent 对话建模成有向状态图，控制流程走向 |
| State | 在 LangGraph 所有节点间共享的对话状态对象 |
| Checkpoint | State 的快照，支持断点续传和对话回溯 |
| LLM-as-Judge | 用另一个 LLM 评估 Agent 回复质量，成对比较比绝对打分更可靠 |
| Prompt Injection | 用户输入覆盖 System Prompt，因为 LLM 分不清"指令"和"数据" |
| Lost in the Middle | LLM 对中间位置的注意力最弱，对话长了早期信息容易被忽略 |
| RRF | Reciprocal Rank Fusion，不靠绝对分数只看排名来融合两组检索结果 |
| Cross-Encoder | 把问题和文档一起喂给模型，直接打分，慢但精准 |
| BM25 | 经典的词频-逆文档频率关键词检索算法，精确匹配能力强 |
| Small2Big | 小粒度检索 + 大上下文生成，句子级索引携带前后 N 句上下文 |
| Harness Engineering | 模型外面的编排骨架——工具管理+状态控制+故障恢复，好编排>好模型 |
| Loop Engineering | Agent 循环的工程可靠性——收敛控制+代价管理+路径确定性+自我纠错 |
| Context Engineering | 在正确时间给正确信息——滑窗+摘要+检索+画像，不是调 Prompt |
| MCP | Agent 连工具的"USB-C"标准协议——跨框架跨语言统一接口 |
| A2A | Agent 连 Agent 的标准协作协议——发现+委托+回复+回退 |
| Circuit Breaker | 熔断器——连续失败 N 次后暂时不再调用该服务 |
| Token Bucket | 令牌桶限流算法，固定容量固定速率补充，超过就排队/拒绝 |
| 纵深防御 | 多层护栏叠加，每层挡自己能挡的，最终绕过率极低 |
| DLQ | Dead Letter Queue，消息处理失败后的"停尸房"，人工排查后重放 |
| GitOps | Git 仓库是唯一真理来源，集群状态 = Git 声明的期望状态 |
| HPA | Horizontal Pod Autoscaler，K8s 根据 CPU/内存自动扩缩 Pod 数量 |
| K3s | 轻量级 K8s 发行版，< 100MB 二进制，512MB 内存，单机生产首选 |
| Helm | K8s 的包管理器，一个 Chart 描述整个应用的所有 K8s 资源 |
| APISIX | Apache 开源 API 网关，动态路由 + 插件体系，替代 Nginx 做网关层 |
| MinIO | 兼容 S3 协议的对象存储，本项目用于文档/日志/备份/Milvus 底层存储 |
| SET NX EX | Redis 分布式锁的核心命令：SET key value NX（不存在才设）EX（设置过期时间） |
| Partition Key | Milvus 物理分区隔离 |
| DLX | Dead Letter Exchange，RabbitMQ 中定义死信转发规则 |

---

> 文件基于 enterprise-agent 项目实际代码和架构生成
> 版本: v2.0（云原生微服务架构）
> 代码: 14,707 行 Python, 90 模块, 24 子包
> 测试: 48 个 (45 passed, 0 failed, 3 skipped)
> 配置: 2,471 行 YAML/SQL/JSON, 30 配置文件
> GitHub: github.com/addhai/enterprise-agent
