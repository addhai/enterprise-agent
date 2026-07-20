# 📂 enterprise-agent 项目文件目录全解

> 版本：v2.0（Cloud-Native 微服务架构 + LangGraph v2.0 扁平化 + Milvus 向量库 + 业务系统升级）
> 日期：2026-07-17
> 目的：用大白话讲清楚每个文件是干什么的、每个类和方法在项目中的作用
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

---

## 📁 src/config.py — 全局配置管理器（云原生升级）

**一句话概括：** 这个文件是整个项目的"设置中心"，从 .env 和环境变量加载配置，覆盖 LLM、向量库、对象存储、消息队列、数据库等所有基础设施。

### 大白话讲解

想象你开了一家连锁咖啡店，config.py 就是你的"总店配方手册"。v0.2 时代只记录了用什么咖啡豆（LLM）、杯子多大（chunk_size）。到了 v1.0 云原生时代，连锁店扩张了——你要管理中央仓库（MinIO）、物流车队（RabbitMQ）、分店库存系统（Milvus）、会员数据库（PostgreSQL）、临时储物柜（Redis）。配方手册升级了，每种基础设施都有专属配置段。

### 核心类

#### `Settings`（全局单例，基于 pydantic-settings）
这是整个项目的"设置中心"。所有模块需要配置时都来找它要。环境变量优先级最高，会覆盖 .env 的值。

**关键字段（按功能分组）：**

| 分组 | 字段 | 说明 |
|------|------|------|
| **LLM** | `openai_api_key`, `openai_api_base`, `llm_model`, `llm_complex_model`, `embedding_model`, `embedding_dimensions` | LLM 和 Embedding 模型配置 |
| **Milvus** | `milvus_host`, `milvus_port`, `milvus_collection_name`, `vector_store_backend` | 向量数据库配置，`vector_store_backend` 支持 "chroma"/"milvus"/"auto"/"remote" |
| **MinIO/S3** | `minio_endpoint`, `minio_access_key`, `minio_secret_key`, `minio_bucket_docs`, `minio_bucket_logs`, `minio_bucket_models`, `minio_use_ssl` | 对象存储配置，三个 Bucket 分别存文档、日志、模型 |
| **RabbitMQ** | `rabbitmq_url`, `rabbitmq_exchange`, `rabbitmq_inference_queue`, `rabbitmq_persist_queue`, `rabbitmq_index_queue`, `rabbitmq_notify_queue` | 消息队列配置，四种队列对应推理、持久化、索引、通知 |
| **RAG Service** | `rag_service_url`, `rag_service_timeout` | 远程 RAG 微服务调用地址和超时 |
| **Redis** | `redis_url`, `short_term_ttl`, `short_term_max_window` | 缓存和短期记忆配置 |
| **PostgreSQL** | `database_url`, `long_term_max_per_user` | 业务数据存储配置 |
| **Chroma** | `chroma_persist_dir`, `chroma_collection_name` | 本地向量库（开发/降级用） |

---

## 📁 src/rag/ — RAG 知识库引擎（云原生升级）

这是整个项目的"知识库大脑"，负责把各种格式的文档变成向量，存进向量库，然后被人问问题时检索出来。

**v1.0 新增：** Milvus 向量存储、独立 RAG 微服务、远程客户端、多后端路由。

---

### 📄 `__init__.py` — 总出口（门面）

**一句话：** 把所有好东西统一打包出口，外部代码只需要 `from src.rag import ...` 就能拿到所有东西。导出了 50+ 个类，覆盖了 RAG 的所有功能。

---

### 📄 `types.py` — 共享类型定义

**一句话：** 定义了整个 RAG 系统用的"通用标签"，所有模块共用。

**核心类：**
- `AccessLevel`（权限等级）：public → internal → confidential → restricted。就像公司的文件分级。
- `BusinessDomain`（业务域）：product/sales/support/engineering/legal。就像公司的部门划分。
- `QualityStatus`（质量状态）：accept → reject_low_quality → reject_expired → warn_outdated。就像仓库收货时的质检流程。

---

### 📄 `data_sources.py` — 数据源抽象层

**一句话：** 定义"文件从哪里来"的统一接口。

**核心类：**
- `FileInfo`（文件信息）：封装文件的路径、名字、扩展名、大小。
- `BaseDataSource`（抽象基类）：规定所有数据源必须实现 `list_files()` 和 `read_file()`。
- `LocalDirectoryDataSource`（本地目录实现）：递归扫描目录，支持 11 种扩展名。

---

### 📄 `loader.py` — 文档加载编排器（总指挥）

**一句话：** 整个 RAG 系统的"总指挥"，协调数据源扫描 → 格式加载 → 管道处理 → 质量拦截 → 去重 → 版本记录的完整流程。

**核心类：**

#### `DocumentLoader`
- `load_directory(dir_path)`：加载目录下所有文档（最常用入口）。
- `load_file(file_path)`：加载单个文件。

**处理流程（完整流水线）：**
```
原始文件 → 数据源扫描 → 格式加载 → 管道处理 → 质量拦截 → 去重 → 返回 Document 列表
```

---

### 📄 `chunker.py` — 文档切分器

**一句话：** 把大文档切成小块，支持两种粒度——段落级和句子级。

**核心类：**
- `HybridChunker`（混合切分器）：
  - `split_standard()`：标准粒度切块，chunk_size=512，重叠 64 字符。
  - `split_sentences()`：句子粒度切块，携带前后 3 句的上下文。
  - `split_both()`：同时生成两种粒度。
- `SentenceWindowSplitter`（句子窗口切分器）：
  - `split(documents)`：切成句子级小块。
  - `expand_context(chunk)`：从小块恢复完整上下文（Small2Big 策略）。

---

### 📄 `embedder.py` — 文本向量化服务

**一句话：** 把文字变成数字向量，调用阿里百炼 DashScope Embedding API。

**关键方法：**
- `embed_text(text)`：单条文本 → 1024 维向量。
- `embed_documents(texts)`：批量文本 → 批量向量。
- `embed_query(text)`：别名，供 Chroma 调用。

---

### 📄 `vector_store.py` — 向量库管理（Chroma 适配器）

**一句话：** Chroma DB 的封装，负责向量化文档的增删查。当 `vector_store_backend=chroma` 或 Milvus 不可用降级时使用。

**核心类：**

#### `VectorStoreManager`
- `add_documents(docs)`：添加文档到向量库。
- `search(query, top_k)`：向量相似度搜索。
- `search_with_scores(query, top_k)`：带相似度分数的搜索。
- `delete_by_ids(ids)`：按 ID 删除文档。
- `delete_collection()`：删除整个集合（测试用）。

---

### 📄 `milvus_store.py` — Milvus 向量存储适配器（v1.0 新增）

**一句话：** Milvus 向量数据库的完整适配器，提供 Partition Key 多租户隔离、标量过滤 + 向量检索单语句完成、批量写入优化。

**大白话：** 以前用 Chroma 就像用书架存书，所有租户的书混在一起，靠翻目录（元数据过滤）来区分。现在用 Milvus 就像升级到智能图书馆——每个租户有自己独立的藏书区（Partition Key 隔离），想找书时直接告诉系统"我要 A 区（tenant_id=A）的、权限等级至少为 B 的书"，系统一个查询就能找到。而且支持 12 种索引类型，百万级向量也很快。

**核心类：**

#### `MilvusVectorStore`
**关键方法：**
- `connect()`：建立 Milvus 连接。
- `ensure_collection()`：自动创建 Collection（含 Partition Key 设置），幂等操作。
- `insert(documents, embeddings)`：批量写入向量（每批 1000 条，自动分批）。
- `search(query_text, top_k, tenant_id, access_levels, filter_expr)`：多租户向量检索 + 标量过滤，一个 gRPC 调用完成。
- `delete_by_filter(expr)`：按表达式批量删除。就像"把所有 A 区过期的书下架"。
- `get_stats()`：返回 Collection 统计（总文档数、索引状态等）。

**设计巧思：** Schema 设计时 `tenant_id` 字段设了 `is_partition_key=True`，这意味着 Milvus 底层按租户分区存储数据。查询时在 WHERE 里指定 `tenant_id == "xxx"`，Milvus 只会扫描该分区，不会扫描全部数据。就像图书馆按楼层分区——查 3 楼的书，不可能去 1 楼翻。

**索引策略：** 默认 `IVF_FLAT`，适合百万级数据量。nlist=128 个聚类中心，比 HNSW 省内存。如需更高性能可切换为 `IVF_SQ8`（压缩）或 `HNSW`（高速）。

**降级机制：** 如果 `pymilvus` 连接失败，自动 fallback 到 Chroma。就像正门坏了走侧门——不耽误营业。

---

### 📄 `server.py` — RAG 独立微服务（v1.0 新增）

**一句话：** 用 FastAPI 把 RAG 检索能力封装成独立 HTTP 微服务，可独立部署、独立扩容。

**大白话：** 以前 RAG 检索是嵌在 API 服务里的一个模块——就像咖啡师兼做甜点，忙起来两样都做不好。现在甜点部门独立出去开了个"甜点专卖店"（RAG Service），有自己的厨房（Milvus）、自己的收银台（FastAPI）、自己的员工（Uvicorn workers）。咖啡师只需要打个电话下单（HTTP 调用），甜点就送过来了。

**启动方式：** `uvicorn src.rag.server:app --host 0.0.0.0 --port 8001`

**核心端点：**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/search` | POST | 混合检索（向量 + BM25） |
| `/index` | POST | 索引新文档 |
| `/stats` | GET | 向量库统计（总文档数、索引状态） |
| `/metrics` | GET | Prometheus 格式指标 |

**关键类：**
- `SearchRequest`：检索请求模型（query, tenant_id, top_k, access_levels, filter_expr）。
- `SearchResponse`：检索响应模型（results, total, latency_ms）。
- `IndexRequest`：索引请求模型（doc_id, tenant_id, text, metadata, access_level）。

---

### 📄 `remote_client.py` — RAG HTTP 客户端（v1.0 新增）

**一句话：** api-service 和 agent-worker 调用 rag-service 的 HTTP 客户端，内置重试 + 超时 + 熔断降级。

**大白话：** 就像甜点店的"外卖订购系统"——咖啡师（api-service/worker）不需要跑到甜点店（rag-service），直接通过这个客户端下单。如果甜点店忙线（超时）、停电（熔断）、送错单（重试），客户端自动处理。

**核心类：**

#### `RagClient`
**关键方法：**
- `search(query, tenant_id, top_k, access_levels, filter_expr)`：同步检索。
- `search_async(query, ...)`：异步检索（async/await）。
- `index(doc_id, tenant_id, text, metadata, access_level)`：索引文档。
- `stats()`：获取向量库统计。
- `health()`：检查 RAG Service 健康状态。

**三重防护：**
1. **重试机制：** HTTP 请求失败自动重试 3 次，指数退避。
2. **超时控制：** 默认 10 秒超时，可配置。
3. **熔断器：** 连续失败 5 次后熔断 30 秒，期间直接返回空结果（不尝试请求）。就像外卖系统发现甜点店连续 5 次不接单，自动标记"暂停接单 30 秒"，避免继续浪费时间去拨号。

---

### 📄 `retriever.py` — 混合检索器（v1.0 升级多后端）

**一句话：** 最核心的检索逻辑——三路并行检索（标准向量 + BM25 + 句子向量），RRF 融合，权限过滤，版本冲突处理，多后端路由（Chroma/Milvus/Remote/Auto）。

**大白话：** v0.2 时代只有一个侦探（Chroma 本地检索）。v1.0 升级后有了四个侦探渠道可以选——本地侦探（Chroma）、总部侦探（Milvus 直连）、远程侦探（HTTP 调 rag-service）、智能侦探（Auto 模式——先试 Milvus，不行降级 Chroma）。

**核心类：**

#### `HybridRetriever`

**关键方法：**
- `search(query, top_k, expand_context, filter_by)`：混合检索（最常用入口）。
- `search_with_scores(query, ...)`：带分数的检索。

**多后端路由（`_vector_search` 方法核心逻辑）：**
```
用户请求 → HybridRetriever.search()
  → 判断 backend 模式:
     ├── "chroma":  本地 LangChain Chroma wrapper
     ├── "milvus":  pymilvus 直连 (多租户 Partition Key + 标量过滤)
     ├── "remote":  HTTP 调用 rag-service
     └── "auto":    Milvus 优先，不可用时自动降级 Chroma
```

**检索流程（完整流水线）：**
```
用户问题
  ↓
三路并行检索（标准向量 + BM25 + 句子向量）
  ↓
RRF 融合（k=60，不靠绝对分数，只靠相对排名）
  ↓
合并标准 + 句子结果（按内容去重）
  ↓
权限过滤（租户隔离 + 访问等级过滤）
  ↓
版本冲突处理（同一文档多版本 → 过滤废弃版 → 保留最新活跃版）
  ↓
Top-K 返回
```

---

### 📄 `concurrency.py` — 限流熔断 + 并发加载

**一句话：** 给所有外部 API 调用装上"限速器"和"断路器"。

**核心类：**
- `RateLimiter`（令牌桶限流器）：`acquire(tokens, timeout)` 获取令牌。
- `CircuitBreaker`（熔断器）：CLOSED → OPEN → HALF_OPEN → CLOSED 状态机。
- `GlobalLimits`（全局单例）：为 vision/ocr/safety 三类 API 分别管理限流+熔断。
- `ConcurrentLoader`（并发加载器）：线程池并发加载文件，受限流熔断保护。

---

### 📄 `metrics.py` — 指标采集

**一句话：** 给整个处理管道做"体检"，记录每个步骤的成功率、失败率、耗时分布。

**核心类：**
- `PipelineMetrics`：
  - `record_count(name, value, labels)`：记录计数器。
  - `record_duration(name, duration, labels)`：记录直方图。
  - `get_metrics()`：返回结构化指标数据（含 p50/p95/p99 百分位数）。
  - `report()`：输出人类可读的统计报告。

---

### 📄 `tracing.py` — 处理追踪

**一句话：** 给每个文件生成"处理履历"，记录经过的步骤、耗时、被谁拦截了、为什么被拦截。

**核心类：**
- `PipelineTracer`：
  - `start_trace(file_path, format)`：开始跟踪一个文件。
  - `add_step(name, duration_ms, ...)`：记录一个处理步骤。
  - `complete(total_docs, rejected_reason, quality_status)`：标记完成。
  - `flush()`：写入日志 + 按日期持久化为 JSON 文件。

---

### 📄 `sync_state.py` — 同步状态管理

**一句话：** 维护一个"文件快照表"，记录每个文件上次处理的时间、内容哈希、状态、向量库 ID。

**核心类：**
- `SyncStatus`：PROCESSED / FAILED / SKIPPED。
- `SyncStateEntry`：每个文件一条记录（路径、哈希、mtime、chunk IDs）。
- `SyncStateStore`：JSON 文件持久化存储，支持版本号和 schema 版本检查。

---

### 📄 `sync_models.py` — 同步数据模型

**一句话：** 定义同步过程中的各种数据结构和工具函数。

**核心类：**
- `ChangeType`：NEW / MODIFIED / DELETED / UNCHANGED。
- `FileChange`：描述单个文件的变更。
- `SyncResult`：汇总统计（扫描数、新增数、修改数、删除数、chunk 数、错误数、耗时）。

---

### 📄 `file_sync_manager.py` — 文件同步管理器

**一句话：** 负责增量同步——只处理变化的文件，不变化的跳过，删除的清理。

**关键方法：**
- `sync(directory, mode)`：执行同步。mode="incremental" 增量同步，"full" 全量同步。
- `scan(directory)`：扫描目录，预览即将发生的变更。

**关键设计：** 对归一化文本求哈希，不是原始字节。格式微调不触发重处理。

---

### 📄 `version_history.py` — 版本历史管理

**一句话：** 为每个处理过的文档保留完整版本历史，支持版本对比、回滚。

**核心类：**
- `VersionSnapshot`：记录每次处理的内容哈希、预览、元数据、chunk IDs。
- `VersionDiff`：对比两个版本的字段差异。
- `VersionHistory`：
  - `save_snapshot()`：保存版本快照（git commit）。
  - `get_versions(path)`：获取某文件的所有版本（git log）。
  - `compare(path, v1, v2)`：对比两个版本（git diff）。

---

### 📄 `dead_letter_queue.py` — 死信队列

**一句话：** 加载失败的文件不直接丢弃，进 DLQ 排队，支持按错误类型分类重试。

**核心类：**
- `ErrorCategory`：NETWORK（自动重试）/ FILE（不重试）/ LOAD（不重试）。
- `DLQEntry`：记录失败文件路径、错误类型、重试次数。
- `DeadLetterQueue`：SQLite 持久化。
  - `add()`：添加失败条目。
  - `get_pending()`：获取可重试的条目。
  - `retry_all()`：批量重试。

---

### 📄 `loaders/` — 格式加载插件目录

**一句话：** 每种文档格式一个加载器，通过 `@register_loader(".ext")` 装饰器自动注册。

**核心类：**
- `loaders/base.py`：
  - `BaseLoader`（抽象基类）：所有加载器必须实现 `load(info, base_meta) -> List[Document]`。
  - `LoaderRegistry`（注册表）：类级别字典。
  - `register_loader(ext)`：装饰器，自动注册。
- `loaders/markdown_loader.py`：加载 .md，提取标题层级，按章节拆分。
- `loaders/pdf_loader.py`：加载 .pdf，逐页提取文字，优先用书签构建大纲。
- `loaders/html_loader.py`：加载 .html，移除脚本/样式/导航，提取正文。
- `loaders/docx_loader.py`：加载 .docx，识别 Heading 样式，按章节分组。
- `loaders/image_loader.py`：加载图片，三级降级策略（视觉引擎 → 主 OCR → 备用 OCR）。

---

### 📄 `processors/` — 处理管道目录

**一句话：** 文档加载后经过的"加工厂"，每个处理器独立可替换，按顺序执行。

**核心类：**
- `processors/base.py`：
  - `ProcessingContext`：处理器之间的共享状态（传送带）。
  - `BaseProcessor`：逐文档处理器，`process(doc, ctx) -> Optional[doc]`。
  - `BaseBatchProcessor`：批量处理器，需要全局信息。
  - `IngestionPipeline`：摄取管道，`add(processor)` / `add_batch(batch_processor)` / `run(docs)`。
- `processors/normalize.py`：全角→半角、中文省略号标准化、合并连续空白。
- `processors/noise_filter.py`：过滤导航文本、提取页码和文档标题。
- `processors/structure_detect.py`：检测代码块、表格、列表，注入提示标签。
- `processors/content_safety.py`：PII 检测 + 合规校验 + 权限自动升级。
- `processors/metadata_enrich.py`：根据文档内容关键词标注权限等级和业务域。
- `processors/quality_check.py`：拦截低质量文档和过期文档。
- `processors/deduplicate.py`：三级去重（精确 → SimHash → 语义）。

---

### 📄 `vision_engines/` — 视觉引擎插件目录

**一句话：** 图片理解引擎的插件系统，支持多引擎可切换。

**核心类：**
- `vision_engines/base.py`：
  - `VisionResult`：content + confidence + model。
  - `VisionCircuitBreaker`：连续失败 5 次熔断，60 秒恢复。
  - `BaseVisionEngine`：`understand(image_path, image_type) -> VisionResult | None`。
  - `BaseOCREngine`：`recognize(image_path) -> str | None`。
- `vision_engines/registry.py`：引擎注册表。
- `vision_engines/qwen_vision_engine.py`：阿里百炼 Qwen-VL 视觉引擎。
- `vision_engines/openai_vision_engine.py`：OpenAI GPT-4o 视觉引擎。
- `vision_engines/paddle_ocr_engine.py`：中文 OCR 主力引擎。
- `vision_engines/tesseract_ocr_engine.py`：兜底 OCR 引擎。

---

### 📄 `safety/` — 内容安全检测（RAG 内）

**一句话：** 独立于处理管道的安全检测模块，提供 PII 检测和合规校验。

- `safety/pii_detector.py`：检测身份证、手机号、银行卡、API Key 等，支持脱敏。
- `safety/content_compliance.py`：检测政治/色情/暴力/垃圾/违禁内容，支持本地正则 + 云端 API。

---

### 📄 `outline.py` — 文档大纲提取模块

**一句话：** 从各种格式的标题层级中提取结构化大纲，构建嵌套树，按章节边界拆分文档。

**核心类：**
- `OutlineNode`：大纲树节点（text, level, children）。
- `OutlineTree`：
  - `build(headings)`：从扁平标题列表构建嵌套树。
  - `split(text)`：按章节边界拆分为多个 Document。
  - `flatten()`：返回扁平化的章节路径。

---

### 📄 `loader_utils.py` — 加载器工具函数

**一句话：** 通用工具函数（如 `detect_encoding(file_path)` 自动检测文件编码），避免循环导入。

---

### 📄 `image_context.py` — 图片上下文关联

**一句话：** 将图片与其在原文档中的上下文关联起来，提升检索相关性。`infer_image_type(image_path)` 根据文件名关键词推断图片类型。

---

## 📁 src/agent/ — ReAct Agent 模块

**一句话：** 整个客服系统的"推理大脑"，负责理解用户意图、调用工具、自主推理。

---

### 📄 `agent/agent.py` — 客服 Agent

**一句话：** 封装 LangChain `create_agent`，把 LLM + 工具 + Prompt 打包成一个可以调用的 Agent。

**核心类：**

#### `CustomerServiceAgent`
- `run(user_message)`：处理用户消息，返回最终回复。
- `run_with_trace(user_message)`：处理用户消息，返回完整推理过程。

---

### 📄 `agent/tools.py` — Agent 工具集（v1.0 权限升级）

**一句话：** 定义 Agent 能用的工具，并加上完整的权限检查中间件。v1.0 新增 PermissionCache + PermissionVersionTracker。

**大白话：** v0.2 时代只有一个 `PermissionChecker` 保安检查权限。v1.0 升级后有了"权限记忆系统"——保安不再每次查数据库（太慢），而是记住你的权限快照（PermissionCache），5 分钟检查一次有没有更新。如果中途你的权限变了（比如被降级），版本追踪器（PermissionVersionTracker）会立刻暂停当前任务——就像保安不会让你用已失效的通行证继续在 VIP 区办事。

**核心类：**

#### `PermissionChecker`（权限检查中间件）
- `check(tool_name, resource_scope)`：检查用户是否允许调用此工具。
- `validate_params(tool_name, params)`：参数级校验。

**三层防护：** 工具级权限 → 参数级校验 → 审计日志。

#### `PermissionCache`（权限缓存，v1.0 新增）
**原理：** 缓存权限快照 + 版本号，TTL 5 分钟。权限变更时推送失效事件。敏感操作前强制刷新权威数据源。缓存结构：`{snapshot: {roles, plan, access_levels}, version, ttl, expired}`。

**三种失效策略：**
1. 被动失效：TTL 到期自动过期。
2. 主动失效：权限变更时推送 `invalidate()`。
3. 半主动失效：敏感操作前强制 `refresh()`。

#### `PermissionVersionTracker`（权限版本追踪，v1.0 新增）
**原理：** 多工具任务中途权限变更检测。每个关键步骤前检查权限版本是否变化，变化则触发 `PermissionVersionChanged` 异常 → 暂停任务 + 重新规划。就像项目经理发现团队成员权限变了，立刻暂停当前任务，重新分配工作。

**三个工具：**
- `search_knowledge_base`：搜索知识库。
- `search_faq`：FAQ 关键词匹配（内置 FAQ 库，覆盖密码重置、SSO、403 等 10 个常见问题）。
- `escalate_to_human`：转人工坐席。

---

### 📄 `agent/prompt.py` — Prompt 工程

**一句话：** 构建 ReAct 系统 Prompt 模板，以及 Prompt 注入检测。

**核心函数：**
- `REACT_SYSTEM_PROMPT`：系统 Prompt 模板。
- `build_prompt(tools, memory_context)`：动态构建 Prompt。
- `detect_prompt_injection(message)`：6 类注入攻击检测（指令覆盖/角色扮演/系统伪造/信息提取/权限提升/安全绕过）。

---

## 📁 src/graph/ — LangGraph 工作流编排（v2.0 扁平化）

**一句话：** 把 Agent 的对话流程建模成有向图，v2.0 从 5 个子图重构为单层 StateGraph 直接编排 handler 函数。

**v1.0（重构前）：** 5 个子图 + 1 个父图 = 6 层 StateGraph，4 种 StateType，3 个桥接函数。
**v2.0（重构后）：** 1 个 StateGraph + 8 个 handler 函数 = 1 层，1 种 StateType，0 个桥接函数。

**新的 DAG：**
```
entry → classify → {faq_handle | rag_handle | human}
                      ↓
              reflect? → reply → END
                      ↓
              expert? → reflect → reply
```

---

### 📄 `graph/state.py` — 状态定义

**一句话：** 定义 `AgentState` TypedDict，贯穿整个工作流的所有数据。

**核心字段：** `messages`（对话历史）、`intent`（当前意图）、`retrieved_docs`（检索结果）、`needs_human`（是否转人工）、`turn_count`（当前轮次）、`memory_context`（记忆上下文）、`quality_score`（质量评分）、`hallucination_detected`（幻觉检测结果）、`emotion`（情绪检测的结果）。

---

### 📄 `graph/nodes.py` — 节点实现（v2.0 合并版）

**一句话：** 7 个处理节点的具体逻辑，每个节点接收 State → 返回更新。v2.0 中 `classify_node` 合并了原来的 `clarify_node` + `router_node`。

**7 个节点：**
- `entry_node`：注入长期记忆上下文 + 运行注入检测 + 情绪检测前置（愤怒/紧急用户直接转人工）。
- `classify_node`（v2.0 合并）：判断用户问题是否缺少关键信息 → 分析意图 → 路由。FAQ 豁免列表（密码重置、SSO 配置、403 错误）不走追问。追问仅对 `intent=technical` 触发。
- `faq_node`：关键词匹配常见问题库。
- `rag_node`：创建 CustomerServiceAgent 执行 ReAct 循环，含双重幻觉防护。
- `human_node`：准备转人工上下文。
- `reflect_node`：仅在 quality_score 不确定时才调用 LLM 审查（高质量回复直接通过，节省 60-80% LLM 调用）。
- `expert_node`（预留）：A2A 远程委托，当 RAG 检索质量过低时委托给远程专家 Agent。

---

### 📄 `graph/workflow.py` — 工作流组装（v2.0 扁平化编排）

**一句话：** 单层 StateGraph 直接编排 handler 函数，不再有子图嵌套。

**关键方法：**
- `create_workflow(retriever, memory_manager)`：组装完整的 StateGraph。

**5 条路径：**
1. FAQ 直达：entry → classify(faq) → faq → reply
2. 技术排查：entry → classify(tech) → rag → reflect → reply
3. 转人工：entry → classify(human) → human → reply
4. FAQ → RAG 升级：faq 失败 → classify → rag → reflect → reply
5. RAG → 人工升级：rag 失败 → human → reply

---

## 📁 src/memory/ — 记忆管理

**一句话：** 三层记忆架构——短期滑窗 + 中期摘要 + 长期检索，MemoryManager 统一管理。

---

### 📄 `memory/manager.py` — 记忆中枢

**一句话：** `MemoryManager` 是 LangGraph 和工作流之间的桥梁，三节点自动触发记忆操作。

**关键方法：**
- `on_entry(session_id, user_id, message)`：注入长期记忆上下文 + 用户画像。
- `on_rag_start(session_id, user_message)`：记录用户消息到短期记忆，提取对话历史。
- `on_completion(session_id, user_id, intent, response)`：持久化长期记忆 + 质量评估。

---

### 📄 `memory/short_term.py` — 短期记忆

**一句话：** 管理单次对话的短期记忆，Redis 优先 + LLM 摘要 + 内存降级。

**关键方法：**
- `add_message(role, content)`：添加消息。
- `get_window()`：返回滑动窗口内的最近消息。
- `get_summary()`：返回早期对话的摘要。
- `get_context_for_llm()`：构建注入 LLM 的完整上下文。

---

### 📄 `memory/long_term.py` — 长期记忆

**一句话：** 跨会话持久化关键事实，PG + Chroma 优先 + 内存降级。

**关键方法：**
- `add_memory(user_id, topic, content, importance)`：添加长期记忆（importance 越高越容易记住）。
- `search(user_id, query, top_k)`：检索最相关的长期记忆。
- `get_user_profile(user_id)`：聚合用户画像。
- `get_recent(user_id, limit)`：获取用户最近的记忆。

**检索策略：** Chroma 语义检索 → PG ILIKE 关键词 → 内存字典评分。

---

## 📁 src/api/ — HTTP 服务层（云原生升级）

**一句话：** FastAPI 对外暴露 REST API，v1.0 新增 Chatwoot Webhook、Prometheus 指标、监控端点。

---

### 📄 `api/server.py` — FastAPI 应用入口

**一句话：** 创建 FastAPI 应用，注册路由，处理启动/关闭生命周期。

**关键方法：**
- `create_app()`：创建 FastAPI 应用 + CORS 中间件。
- `startup()`：预编译 LangGraph 工作流（避免首次请求冷启动延迟）。
- `shutdown()`：清理过期会话。

---

### 📄 `api/routes.py` — API 路由

**一句话：** 定义 `/api/v1/chat` 和 `/api/v1/health` 两个核心端点。

**核心类：**
- `ChatRequest`：请求模型（question, user_id, tenant_id, roles, plan）。
- `ChatResponse`：响应模型（reply, needs_human, intent）。
- `chat(request)`：处理聊天请求 → 构建 AgentState → 调用工作流 → 返回回复。

---

### 📄 `api/dependencies.py` — 依赖注入

**一句话：** 管理 HybridRetriever、MemoryManager、CompiledWorkflow 的全局单例生命周期。

**关键方法：**
- `get_retriever()`：延迟初始化 HybridRetriever。
- `get_memory_manager()`：延迟初始化 MemoryManager。
- `get_workflow()`：延迟初始化并编译 LangGraph 工作流。
- `cleanup_resources()`：清理所有资源。

---

### 📄 `api/chatwoot.py` — Chatwoot Webhook 端点（v1.0 新增）

**一句话：** 接收 Chatwoot 开源客服系统通过 Webhook 发送的消息，处理后返回 AI 回复。

**大白话：** 就像公司前台多了一个"Chatwoot 专线"——客户通过 Chatwoot 发的消息自动转接到我们的 AI 客服，处理完后回复也自动发回 Chatwoot。集成了 Webhook token 验证 + Chatwoot API 自动回复。

**核心端点：**
- `POST /api/v1/chatwoot/webhook`：接收 Chatwoot 消息事件（message_created），调用 LangGraph 工作流处理后通过 Chatwoot API 回复。
- `_validate_webhook_token(token)`：验证 Webhook 请求的 access_token。
- `_send_reply_to_chatwoot(account_id, conversation_id, content, is_private)`：向 Chatwoot API 发送回复。

---

### 📄 `api/metrics.py` — Prometheus 指标库（v1.0 新增）

**一句话：** 零依赖的 Prometheus 指标采集库，提供 Counter/Histogram/Gauge 三种指标类型，纯 Python 实现，不依赖 prometheus_client 库。

**大白话：** 就像工厂的"数字仪表盘"——实时显示请求量（Counter）、响应时间分布（Histogram）、当前活跃连接数（Gauge）。所有数据存在内存字典里，`/metrics` 端点输出 Prometheus 标准格式，K8s 定期来"抄表"。

**核心函数：**
- `counter_inc(name, labels, value=1)`：计数器 +1。用于统计请求总数、错误数等累积指标。
- `histogram_observe(name, value, labels)`：记录一个延迟样本。用于统计 p50/p95/p99 延迟。
- `gauge_set(name, value, labels)`：设置瞬时值。用于记录活跃连接数、内存使用量等。
- `gauge_inc(name, value=1, labels)` / `gauge_dec(name, value=1, labels)`：增减瞬时值。
- `render_metrics()`：渲染为 Prometheus text format 输出。

**metric key 命名规则：** `name{label1="value1",label2="value2"}`。就像给每个指标贴上标签——`agent_requests_total{endpoint="/chat",status="200"}` 表示"chat 端点的 200 状态码请求数"。

---

### 📄 `api/monitoring.py` — 监控端点（v1.0 新增）

**一句话：** 对外暴露 Prometheus 指标端点 + 业务/质量/风险/系统四维指标 API，供前端监控面板和运维使用。

**大白话：** 就像公司的"数据大屏"——CEO 看业务指标（总请求、转人工率、平均延迟），CTO 看质量指标（平均质量评分）、安全官看风险指标（幻觉率）、运维看系统指标（健康状态）。所有指标由 `api/metrics.py` 和 `evaluation/tracker.py` 联合驱动。

**核心端点：**

| 端点 | 功能 |
|------|------|
| `GET /api/v1/metrics/prometheus` | Prometheus text format，被 K8s prometheus.io 注解抓取 |
| `GET /api/v1/metrics/business` | 业务指标：total_requests, escalation_rate, avg_latency_ms |
| `GET /api/v1/metrics/quality` | 质量指标：avg_quality_score |
| `GET /api/v1/metrics/risk` | 风险指标：hallucination_checks, hallucination_rate |
| `GET /api/v1/metrics/system` | 系统指标：status |
| `GET /api/v1/metrics/all` | 完整报告（聚合上面所有指标） |

---

### 📄 `api/auth.py` — 用户认证与注册（v2.0 新增）

**一句话：** 实现用户注册、登录、Token生成与验证，支持角色管理和用户状态控制。

**核心端点：**
- `POST /api/v1/auth/register`：用户注册（username/password/email/role）。
- `POST /api/v1/auth/login`：用户登录，返回 JWT Token。
- `GET /api/v1/auth/me`：获取当前登录用户信息。

**核心类：**
- `UserRole`（枚举）：super_admin / admin / agent / viewer，四级角色。
- `TokenPayload`：JWT Token 数据结构。
- `require_auth`：依赖注入，验证请求头中的 Token。

---

### 📄 `api/rbac.py` — 权限控制（v2.0 新增）

**一句话：** 基于 RBAC 模型实现细粒度权限控制，15个权限点覆盖所有管理功能。

**核心设计：**
- `Permission`（枚举）：15个权限点，如 dashboard:view、ticket:manage、customer:manage 等。
- `ROLE_PERMISSIONS`：角色-权限映射字典，每个角色对应一组权限。
- `require_permissions(...)`：依赖注入装饰器，检查当前用户是否具备指定权限。

**权限点列表：**
dashboard:view | customer:view/manage | ticket:view/manage/assign | agent:workspace | satisfaction:view | knowledge:view/manage | channel:view/manage | user:view/manage | notification:view

---

### 📄 `api/customers.py` — 客户管理（v2.0 新增）

**一句话：** 客户画像、标签管理、服务历史、时间线追踪的完整 CRUD API。

**核心端点：**
- `GET /api/v1/customers`：客户列表查询（支持按标签、状态过滤）。
- `POST /api/v1/customers`：创建客户。
- `GET /api/v1/customers/{id}`：客户详情（含画像、标签、时间线）。
- `PUT /api/v1/customers/{id}`：更新客户信息。
- `POST /api/v1/customers/{id}/tags`：添加标签。
- `GET /api/v1/customers/{id}/timeline`：服务时间线。

---

### 📄 `api/tickets.py` — 工单管理（v2.0 新增）

**一句话：** 工单全生命周期管理 API，状态机驱动，支持分配、评论、关闭。

**核心端点：**
- `POST /api/v1/tickets`：创建工单（自动触发通知给 admin/super_admin）。
- `GET /api/v1/tickets`：工单列表（支持按状态、优先级、分类过滤）。
- `GET /api/v1/tickets/{id}`：工单详情。
- `PUT /api/v1/tickets/{id}`：更新工单（自动状态机校验，closed 不可更新）。
- `POST /api/v1/tickets/{id}/comments`：添加评论。
- `POST /api/v1/tickets/{id}/assign`：分配工单。

**状态机：** open → in_progress → resolved / closed / cancelled

---

### 📄 `api/satisfaction.py` — 满意度调查（v2.0 新增）

**一句话：** CSAT 满意度评分、标签、文字留言的收集与统计 API。

**核心端点：**
- `POST /api/v1/satisfaction`：提交满意度评价（score 1-5 + tags + comment）。
- `GET /api/v1/satisfaction`：满意度列表。
- `GET /api/v1/satisfaction/stats`：满意度统计（平均分、分布）。

---

### 📄 `api/notifications.py` — 通知中心（v2.0 新增）

**一句话：** 系统消息推送、已读管理，支持按角色和用户精准推送。

**核心端点：**
- `GET /api/v1/notifications`：获取当前用户通知列表。
- `POST /api/v1/notifications/{id}/read`：标记已读。
- `POST /api/v1/notifications/read-all`：全部标记已读。

**内部函数：**
- `add_notification(type, level, title, message, target_roles, target_users, link)`：跨模块调用，统一创建通知。

---

### 📄 `api/dashboard.py` — 数据仪表盘（v2.0 新增）

**一句话：** KPI 聚合、实时活动监控、客服绩效排行的数据 API。

**核心端点：**
- `GET /api/v1/dashboard/kpi`：核心 KPI（总会话、今日活跃、AI解决率、人工介入率、工单统计、满意度）。
- `GET /api/v1/dashboard/realtime`：实时活动（最近会话、等待人工队列、人工会话列表）。
- `GET /api/v1/dashboard/agents`：客服绩效排行（会话量、平均评分）。
- `GET /api/v1/dashboard/intents`：意图分布统计。

---

### 📄 `api/admin.py` — 人工客服工作台（v2.0 新增）

**一句话：** 人工坐席接收转接、查看 AI 上下文、回复用户、关闭服务的 API。

**核心端点：**
- `GET /api/v1/admin/handoff/queue`：获取等待人工接入的会话队列。
- `POST /api/v1/admin/handoff/{session_id}/accept`：客服接受转接。
- `POST /api/v1/admin/handoff/{session_id}/reply`：客服回复用户。
- `POST /api/v1/admin/handoff/{session_id}/close`：客服关闭服务。

**AI 上下文摘要：** 包含转接原因、紧急程度、已尝试方案、用户画像、当前卡点。

---

## 📁 src/safety/ — 安全护栏（五层纵深防御）

**一句话：** 五层纵深防御的前三层——输入检测、输出校验、Observation 清洗。

---

### 📄 `safety/input_guard.py` — 输入护栏

**核心类：** `InputGuard`，正则模式匹配 6 类注入攻击。`check(message)` 检查用户输入是否安全。

### 📄 `safety/output_guard.py` — 输出护栏

**核心类：** `OutputGuard`，三步检测——敏感信息检测、幻觉引用检测、指令泄露检测。

### 📄 `safety/sanitizer.py` — Observation 清洗器

**关键函数：** `sanitize_observation(text)`，清洗外部文档，去掉注入指令和可疑链接。

---

## 📁 src/evaluation/ — 评估监控（v1.0 新增 tracker）

**一句话：** 多维评估体系——RAG 检索指标 + LLM-as-Judge + 在线抽样 + 幻觉检测 + 评估追踪器。

---

### 📄 `evaluation/metrics.py` — 评估指标

**关键功能：**
- RAG 离线指标：`evaluate_retrieval()`、`mean_reciprocal_rank()`。
- LLM-as-Judge：`DialogueJudge` 多维质量评分（相关性、准确性、完整性、安全性、语气）。
- 在线抽样：`should_sample(user_id)` 按概率抽样。
- 幻觉检测：`check_hallucination(agent_response, retrieved_docs)`。

---

### 📄 `evaluation/tracker.py` — 评估追踪器（v1.0 新增）

**一句话：** 记录每次对话的质量评估结果，聚合汇总统计，供 `api/monitoring.py` 的 `/metrics` 端点读取。

**大白话：** 就像学校的"成绩登记簿"——每次考试（对话）后，老师把成绩（质量评分、延迟、是否转人工）登记在簿子上。期末时（/metrics 查询），老师翻翻登记簿就能算出平均分、转人工率、平均响应时间。登记簿只保留最近 100 条记录用于滚动统计，不无限增长。

**核心类：**

#### `EvaluationTracker`
**关键方法：**
- `record_chat(session_id, intent, latency_ms, quality_score, needs_human)`：记录一次对话评估。就像老师在成绩簿上登记一行。
- `stats()`：返回汇总统计（total_requests, avg_latency_ms, avg_quality_score, escalation_rate, uptime_seconds）。

**全局单例：** `get_evaluation_tracker()` 返回全局唯一的 EvaluationTracker 实例。

---

## 📁 src/protocols/ — 协议适配层

**一句话：** 把 Agent 的能力标准化暴露出去——MCP 工具互联 + A2A Agent 协作。

---

### 📄 `protocols/mcp_server.py` — MCP Server

**一句话：** 把 3 个客服工具注册为 MCP HTTP Server，任意 MCP 兼容 Agent 都能调用。

- `build_mcp_server()`：构建 MCP Server，注册 3 个工具。
- `serve(host, port)`：启动 HTTP 服务器。

---

### 📄 `protocols/a2a_server.py` — A2A Server

**一句话：** 把客服 Agent 发布为 A2A 服务，支持 Agent 发现 + 任务委托。

- `build_a2a_server()`：构建 A2A Server，注册 Agent Card。
- `delegate_to_expert(agent_url, task)`：客户端委托函数。

---

### 📄 `protocols/demo_protocols.py` — 协议演示

**一句话：** 演示 MCP 工具注册和 A2A 委托流程的概念脚本。

---

## 📁 src/worker/ — Agent Worker 模块（v1.0 新增）

**一句话：** 从 REST API 中解耦出来的异步推理消费者，通过 RabbitMQ 接收推理任务，执行 LangGraph 编排，结果回写 Redis 或 WebSocket 推送。

**大白话：** 以前用户发消息 → API 同步处理 → 返回结果（就像去柜台办业务，必须等着柜员办完才能走）。现在升级为异步——用户发消息 → API 快速确认 → 消息放到 RabbitMQ 队列 → Worker 后台处理 → 结果通过 WebSocket 推送或 Redis 轮询返回（就像去银行办事，先取号（确认），然后等着叫号（WebSocket 推送），不用一直排着队）。

---

### 📄 `worker/consumer.py` — Agent Worker RabbitMQ 消费者

**一句话：** 消费 `agent.inference.*` 队列消息，执行 CustomerServiceAgent LangGraph 工作流，支持优雅关闭和 DLQ 死信处理。

**核心类：**

#### `AgentWorker`
**关键方法：**
- `connect()`：建立 RabbitMQ 连接 + 声明交换机（topic 类型，durable）+ 声明队列 + 绑定路由键 + 设置 prefetch_count=1（公平分发，每个消费者一次只取一条消息）。
- `disconnect()`：优雅关闭（发送 stop_consuming 信号）。
- `start()`：启动消费循环，注册 SIGTERM/SIGINT 信号处理（收到关闭信号后完成当前消息再退出）。
- `_on_message(channel, method, properties, body)`：消息处理回调 → 解析 JSON → 调用 CustomerServiceAgent → 结果回写 Redis → 发送 ACK。

**队列拓扑：**
```
Exchange: agent.tasks (topic, durable)
  ├── agent.inference.queue (routing_key: agent.inference.*)
  ├── memory.persist.queue
  ├── rag.index.queue
  └── notify.push.queue
```

**设计巧思：** prefetch_count=1 确保慢消费者不会被新消息淹没——就像银行柜员一次只叫一个号，处理完再叫下一个。

---

## 📁 src/infrastructure/ — 基础设施客户端模块（v1.0 新增）

**一句话：** 封装 Redis 分布式锁、MinIO/S3 对象存储等基础设施的客户端工具。

---

### 📄 `infrastructure/redis_lock.py` — Redis 分布式锁

**一句话：** 基于 Redis SET NX EX 的轻量级分布式锁，Lua 脚本原子释放，3 种预设锁工厂（index / memory / quota），支持自动续期和上下文管理器。

**大白话：** 就像公司保险柜的"钥匙管理系统"——同时只能一个人拿钥匙开保险柜（分布式锁）。钥匙有有效期（TTL=30s），到期自动作废（防止死锁）。拿钥匙的人会定期续期（auto_renew），防止操作没完成钥匙就过期。还钥匙时用 Lua 脚本原子操作，确保只有钥匙的主人才能还（防止 A 拿了钥匙，B 去还了 A 的钥匙）。有三种预设钥匙类型——索引更新锁、记忆去重锁、租户配额锁。

**核心类：**

#### `RedisLock`
**关键方法：**
- `acquire(blocking=True, timeout=None)`：获取锁。blocking=True 阻塞等待（retry_times + retry_delay），blocking=False 立即返回。
- `release()`：Lua 原子释放（先检查 owner 是否匹配，再删除 key）。防止误释放。
- `extend()`：手动续期 TTL。
- `__enter__()` / `__exit__()`：上下文管理器支持。

**Lua 原子释放脚本：**
```lua
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
```

**三种预设锁工厂：**
- `index_lock(resource_id, ttl)`：锁前缀 `lock:index:`，用于知识库索引更新防止并发写入。
- `memory_lock(session_id, ttl)`：锁前缀 `lock:memory:`，用于长期记忆去重防止同一会话并发写入。
- `quota_lock(tenant_id, ttl)`：锁前缀 `lock:quota:`，用于租户配额扣减防止并发超扣。

**关键属性：**
- `_owner_id`：锁持有者唯一标识（uuid + 时间戳），用于防止误释放。
- `auto_renew`：是否自动续期（默认 True，每 TTL*0.7 秒续期一次）。
- `_acquired`：当前是否持有锁。

**局限性标注（代码内置）：** 不适用于严格 CP 场景（Redis 是 AP）—— 用 PG advisory lock 替代；不适用于长时间持锁（TTL 默认 30s）。

---

### 📄 `infrastructure/minio_client.py` — MinIO/S3 客户端

**一句话：** MinIO S3 客户端的完整封装，支持 Bucket 管理、文件上传/下载/列表、预签名 URL、版本控制、备份/恢复，以及独立的 CLI 命令行工具。

**大白话：** 就像公司的"中央仓库管理系统"——管理三个仓库（doc 文档库、log 日志库、model 模型库）。仓库支持文件上传/下载、生成临时访问链接（预签名 URL）、自动开启版本控制（每次修改都保留历史，不怕误删）、命令行工具可以独立运行脚本操作仓库。

**核心类：**

#### `MinioClient`
**关键方法：**

**Bucket 管理：**
- `ensure_bucket(bucket_name)`：确保 Bucket 存在，不存在则创建 + 自动开启版本控制。
- `list_buckets()`：列出所有 Bucket。

**文件操作：**
- `upload(bucket, file_path, object_name)`：上传文件，自动检测 MIME 类型。
- `download(bucket, object_name, file_path)`：下载文件到本地。
- `list_objects(bucket, prefix)`：列出 Bucket 中的对象（支持按前缀过滤）。

**预签名 URL：**
- `presign_url(bucket, object_name, expires)`：生成临时下载链接（默认 7 天有效）。就像给客户发一个"临时访问密码"，过期作废。

**备份：**
- `backup(bucket, object_name)`：生成备份文件名（带时间戳），复制对象到备份路径。

**属性：**
- `client`：惰性初始化 Minio 客户端（第一次调用时才创建连接）。

**CLI 模式（`python -m src.infrastructure.minio_client`）：**
- `upload --bucket <bucket> --file <path> [--object <name>]`
- `download --bucket <bucket> --object <name> [--output <path>]`
- `list --bucket <bucket> [--prefix <prefix>]`
- `presign --bucket <bucket> --object <name> [--expires <days>]`
- `backup --bucket <bucket> --object <name>`

---

## 📁 src/channels/ — 多渠道接入模块（v1.0 新增，v2.0 精简）

**一句话：** 支持 Web、飞书、Chatwoot 等渠道消息接入，统一转换为内部标准格式后交给调度中枢路由。

**v2.0 变更：** 移除微信（wechat.py）和电话 IVR（phone.py）渠道，保留 Web、飞书、Chatwoot 三大渠道。

---

### 📄 `channels/__init__.py` — 渠道模块标记

---

### 📄 `channels/feishu.py` — 飞书接入（v2.0 新增）

**一句话：** 接收飞书 Bot 的 Webhook 事件，验证签名后转换为 NormalizedMessage 交给调度中枢。

**大白话：** 就像公司前台多了一个"飞书专线"——客户通过飞书群或私聊联系 Bot，飞书服务器推送事件到我们的接口。我们先验证请求签名（确保是飞书发的），然后解析消息内容，转成内部标准格式（NormalizedMessage），最后交给调度中心处理。

**核心函数：**
- `feishu_callback(request)`：接收飞书事件回调（URL 验证 + 消息事件处理）。
- `_verify_feishu_sign(request)`：验证飞书请求签名。
- `_send_feishu_reply(receive_id, content)`：向飞书用户发送回复。

**配置：** 需要设置 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。

---

### 📄 `channels/chatwoot.py` — Chatwoot Web 客服接入

**一句话：** 通过 Chatwoot 开源客服系统的 Web Widget 或 Webhook 接入用户消息。

**核心端点：**
- `POST /api/v1/chatwoot/webhook`：接收 Chatwoot 消息事件。

---

## 📁 src/dispatch/ — 调度中枢模块（v1.0 新增）

**一句话：** 多渠道消息归一化 + 智能路由到对应 Agent 子图。

---

### 📄 `dispatch/__init__.py` — 调度模块标记

---

### 📄 `dispatch/normalizer.py` — 消息标准化器（v1.0 新增）

**一句话：** 将 web / wechat / phone / chatwoot 四个渠道的原始消息统一转换为 `NormalizedMessage` 标准格式。

**大白话：** 就像公司的"邮件收发室"——不管客户是通过邮件、微信、电话还是 Chatwoot 联系公司，收发室都统一翻译成内部工单格式：谁发的（user_id）、通过什么渠道（channel）、说了什么（content）、附带哪些原始信息（raw_payload）。然后这张工单流转到调度中心，调度中心决定派给谁处理。

**核心类：**

#### `NormalizedMessage`
标准化消息数据类，统一字段：
- `message_id`：消息唯一 ID（UUID）。
- `channel`：来源渠道（web / wechat / phone / chatwoot）。
- `user_id`：用户标识。
- `tenant_id`：租户标识。
- `session_id`：会话 ID。
- `content`：纯文本内容。
- `content_type`：内容类型（text / image / voice / event）。
- `raw_payload`：原始消息体（保留用于审计）。
- `metadata`：额外元数据。
- `timestamp`：消息时间戳。

#### `MessageNormalizer`
**关键方法：**
- `register(channel, normalizer)`：注册渠道标准化器。
- `normalize(channel, raw)`：将渠道原始消息标准化。已注册渠道走专属 normalizer，未注册渠道走默认逻辑（提取 content 字段）。

**全局单例：** `get_message_normalizer()` 返回全局唯一的 MessageNormalizer 实例。

---

### 📄 `dispatch/arbitrator.py` — 仲裁器（占位）

**一句话：** 多渠道消息路由到对应 Agent 子图的占位模块，当前仅做标记。

---

## 📁 src/websocket/ — WebSocket 长连接模块（v1.0 新增）

**一句话：** 独立的 WebSocket 微服务，管理用户 AI 对话 + 人工坐席工作台的双向实时通信，支持流式输出、转接分发、多模态消息。

---

### 📄 `websocket/__init__.py` — 模块标记

---

### 📄 `websocket/server.py` — WebSocket 独立服务入口

**一句话：** FastAPI 应用入口，注册 WebSocket CORS 中间件，启动/关闭时管理会话管理器生命周期。

**启动方式：** `uvicorn src.websocket.server:app --host 0.0.0.0 --port 8000` 或 `python -m src.websocket.server`

**核心端点：**
- `GET /ws/health`：WebSocket 服务健康检查。
- `GET /health`：通用健康检查。
- `GET /metrics`：Prometheus 指标。

---

### 📄 `websocket/protocol.py` — 消息协议定义

**一句话：** WebSocket 通信统一 JSON 消息格式，定义所有消息类型常量和构建函数。

**消息类型一览：**

| 方向 | 类型 | 说明 |
|------|------|------|
| 客户端 → 服务端 | `chat_message` | 用户发送聊天消息 |
| 客户端 → 服务端 | `heartbeat` | 心跳保活 |
| 客户端 → 服务端 | `ack` | 确认收到消息 |
| 客户端 → 服务端 | `agent_login` | 人工坐席登录 |
| 客户端 → 服务端 | `agent_send_reply` | 坐席回复用户 |
| 客户端 → 服务端 | `agent_logout` | 坐席登出 |
| 服务端 → 用户客户端 | `streaming_chunk` | 流式输出片段 |
| 服务端 → 用户客户端 | `typing_indicator` | 打字指示器 |
| 服务端 → 用户客户端 | `session_ready` | 会话就绪 |
| 服务端 → 用户客户端 | `transfer_notice` | 转接通知 |
| 服务端 → 用户客户端 | `error` | 错误信息 |
| 服务端 → 人工坐席 | `new_transfer` | 新转接通知 |
| 服务端 → 人工坐席 | `session_update` | 会话状态变更 |
| 服务端 → 人工坐席 | `copilot_suggestion` | AI 建议回复 |

**核心函数：**
- `build_streaming_chunk(session_id, text, ...)`：构建流式输出事件。
- `build_typing_indicator(session_id, is_typing, label)`：构建打字指示器事件。
- `build_transfer_notice(...)`：构建转交通知事件。
- `build_handoff_context(...)`：构建转接上下文（人工坐席可见）。
- `build_error(session_id, code, message)`：构建错误事件。
- `build_session_update(session_id, mode, ...)`：构建会话状态变更事件。
- `build_copilot_suggestion(...)`：构建 AI 建议回复事件。

---

### 📄 `websocket/session_manager.py` — WebSocket 会话管理器

**一句话：** 维护所有活跃的 WebSocket 连接，按 session_id 路由消息，按 agent_id 路由到人工坐席，支持心跳检测和自动断开。

**核心数据结构：**
```
WebSocketSessionManager
├── _sessions: session_id → SessionState
├── _agents: agent_id → WebSocket
└── _queues: session_id → asyncio.Queue
```

**核心类：**

#### `SessionMode`（会话模式枚举）
AI_CHAT → AI_THINKING → WAITING_HUMAN → HUMAN_CHAT → ESCALATED → CLOSED。就像客服系统的状态机——AI 在聊、AI 在思考、等人工、人工在聊、已转接、已关闭。

#### `SessionState`（会话状态）
记录每个会话的完整信息：session_id, user_id, tenant_id, mode, turn_count, needs_human, assigned_agent, conversation_history, handoff_context, message_queue, heartbeat_timeout。

#### `WebSocketSessionManager`
**关键方法：**
- `start()` / `stop()`：启动/停止心跳检测后台任务。
- `create_session(session_id, user_id, tenant_id)`：创建新会话。
- `register_agent(agent_id, websocket)`：注册人工坐席 WebSocket 连接。
- `get_session(session_id)`：获取会话状态。
- `route_to_session(session_id, message)`：向指定会话推送消息。
- `route_to_agent(agent_id, message)`：向指定坐席推送消息。
- `get_online_agents()`：获取在线坐席列表。

**全局单例：** `get_session_manager()` 返回全局唯一的 WebSocketSessionManager 实例。

---

### 📄 `websocket/routes.py` — WebSocket 路由

**一句话：** 处理两个 WebSocket 端点——用户端 `/ws/chat` 和人工坐席端 `/ws/agent/{agent_id}`。

**核心端点：**
- `/ws/chat`：用户客户端 WebSocket。流程——连接 → 创建会话 → 接收 `chat_message` → 标准化 → 触发 LangGraph → 流式推送 `streaming_chunk` → 完成。
- `/ws/agent/{agent_id}`：人工坐席工作台 WebSocket。流程——`agent_login` → 接收 `new_transfer` 通知 → `agent_send_reply` 回复用户 → `agent_logout`。

---

### 📄 `websocket/dispatcher.py` — 转接通知与分发系统

**一句话：** AI 检测到需要转人工时，构建转接上下文、通知在线坐席、管理转接队列、执行会话迁移。

**核心类：**

#### `TransferDispatcher`
**关键方法：**
- `dispatch(session_id, context, urgency)`：分发转接请求。有在线坐席 → 立即推送 `new_transfer`；无坐席 → 进入排队队列。
- `accept(transfer_id, agent_id)`：坐席接受转接 → 会话从 AI_CHAT 迁移到 HUMAN_CHAT。
- `get_queue_length()`：获取当前排队人数。

#### `TransferRecord`
转接记录：transfer_id, session_id, user_id, context, urgency, created_at。

#### `TransferQueue`
转接队列：排队兜底（deque 实现），支持按紧急度排序。

---

### 📄 `websocket/handoff.py` — 转接上下文构建器

**一句话：** 将 AgentState 中的丰富信息压缩为人工客服可读的转接摘要。

**关键函数：**
- `build_handoff_context(state)`：从 AgentState 提取对话摘要（启发式，无额外 LLM 调用）、用户画像（从 memory_context）、已尝试方案（从 RAG 中间步骤）、紧急度评估、完整对话记录。

**输出的转接摘要包含：**
1. 对话摘要（LLM 生成或启发式）
2. 用户画像
3. 已尝试方案（从 RAG 搜索历史提取）
4. 紧急度评估
5. 完整对话记录

---

### 📄 `websocket/streaming.py` — 流式输出引擎

**一句话：** 将 LangGraph DAG 的执行过程转化为流式 WebSocket 事件（typing_indicator → streaming_chunk × N）。

**核心类：**

#### `StreamingEngine`
**关键方法：**
- `stream(llm_stream, session_id, node_label)`：将 LLM 异步流转化为 WebSocket 事件。累积缓冲（chunk_size=3 token），减少推送频率。

---

### 📄 `websocket/multimodal.py` — 多模态消息处理器

**一句话：** 接收前端传来的 base64 图片/音频，通过视觉引擎或语音引擎处理后，将结果转换为文本注入到 Agent 的消息中。

**核心函数：**
- `_save_base64_image(base64_data, suffix)`：保存 base64 图片到临时文件。
- `_save_base64_audio(base64_data, suffix)`：保存 base64 音频到临时文件。
- `process_multimodal_message(content_type, base64_data)`：分发到视觉引擎（Qwen-VL）或语音引擎（Whisper）。

**数据流：**
```
前端 base64 图片 → 保存到临时文件 → Qwen-VL 理解 → 文本注入 Agent
前端 base64 音频 → 保存到临时文件 → Whisper 转录 → 文本注入 Agent
```

---

## 📁 deploy/ — 部署配置目录（v1.0 新增）

**一句话：** 完整的云原生部署基础设施配置——API 网关、消息队列、数据库、监控栈、Helm Charts、ArgoCD。

---

### 📁 `deploy/apisix/` — API 网关

| 文件 | 功能 |
|------|------|
| `apisix.yml` | APISIX 路由规则：`/api/*` → api-service:8000，`/ws/*` → ws-service:8000，`/` → frontend:80 |
| `config.yaml` | APISIX 独立模式配置（不依赖 etcd），适合单机/开发环境 |
| `dashboard-conf.yaml` | APISIX Dashboard 管理界面配置 |

**大白话：** APISIX 就像公司的"总机接线员"——所有外部请求先打到接线员这里，接线员根据路径转接：`/api/*` 转给 API 部门，`/ws/*` 转给实时通信部，`/` 转给前端接待。支持限流、鉴权、TLS 加密等高级功能。

---

### 📁 `deploy/rabbitmq/` — 消息队列配置

| 文件 | 功能 |
|------|------|
| `definitions.json` | RabbitMQ 拓扑定义（交换机 agent.tasks、4 个队列、绑定关系） |
| `rabbitmq.conf` | RabbitMQ 运行时配置（管理插件、指标采集间隔） |

---

### 📁 `deploy/postgres/init/` — 数据库初始化

| 文件 | 功能 |
|------|------|
| `init/` 目录下的 SQL 脚本 | PostgreSQL 初始化：建表（sessions, memory, tenants 等）、索引、初始数据 |

---

### 📁 `deploy/helm/enterprise-agent/` — Helm Chart（K8s 部署）

| 文件 | 功能 |
|------|------|
| `Chart.yaml` | Chart 元数据（名称 enterprise-agent，版本 0.1.0） |
| `values.yaml` | 默认配置值（镜像仓库、副本数、资源限制、环境变量） |
| `values-staging.yaml` | 预发布环境覆盖值（2 副本、小规格、staging 域名） |
| `values-prod.yaml` | 生产环境覆盖值（5 副本、大规格、生产域名、HPA 启用） |
| `templates/configmap.yaml` | ConfigMap 模板（非敏感配置） |
| `templates/secrets.yaml` | Secrets 模板（API Key、数据库密码等敏感信息） |
| `templates/api-deployment.yaml` | API-Service Deployment + Service（端口 8000，健康检查 /api/v1/health） |
| `templates/rag-deployment.yaml` | RAG-Service Deployment + Service（端口 8001，健康检查 /health） |
| `templates/worker-deployment.yaml` | Agent-Worker Deployment（不暴露 Service，仅消费 MQ） |
| `templates/ws-deployment.yaml` | WebSocket-Service Deployment + Service |
| `templates/frontend-deployment.yaml` | Frontend Deployment + Service（Nginx 静态服务） |
| `templates/apisix-deployment.yaml` | APISIX Gateway Deployment + Service（端口 9080/9443/9092） |
| `templates/hpa.yaml` | HorizontalPodAutoscaler（CPU > 70% 触发扩容，api/worker/rag 各 2-10 副本） |
| `templates/ingress.yaml` | Ingress 规则（TLS + 域名路由） |
| `templates/_helpers.tpl` | Helm 模板辅助函数（标签生成、镜像地址拼接等） |

**大白话：** Helm Chart 就像连锁店的"分店装修标准手册"——不管你是在北京还是上海开分店，按这个手册装修，配置一模一样。`values.yaml` 是默认手册，`values-prod.yaml` 是大店升级版（更多员工、更大空间），`values-staging.yaml` 是试运营版。

---

### 📁 `deploy/monitoring/` — 可观测性栈

| 文件/目录 | 功能 |
|------|------|
| `prometheus/prometheus.yml` | Prometheus 抓取配置（scrape_interval: 15s，抓取 api/rag/apisix/rabbitmq/postgres/redis 的 /metrics） |
| `prometheus/alerts.yml` | 告警规则（CPU > 80%、内存 > 90%、错误率 > 5%、P99 延迟 > 2s） |
| `grafana/dashboards/` | Grafana 仪表板 JSON 模板（业务概览、系统健康、RAG 检索质量等） |
| `grafana/datasources.yaml` | Grafana 数据源配置（连接 Prometheus） |
| `promtail-config.yaml` | Loki 日志采集配置（容器日志 → Loki） |

---

### 📁 `deploy/argocd/` — GitOps 持续部署

| 文件 | 功能 |
|------|------|
| `applications.yaml` | ArgoCD Application 定义（监听 Git 仓库 + Helm Chart 路径 + 自动 sync 策略） |

---

## 📁 docker/ — 容器镜像构建（v1.0 新增）

**一句话：** 为三个微服务构建独立的 Docker 镜像，利用多阶段构建和层缓存优化。

---

### 📄 `docker/api/Dockerfile` — API 服务镜像

**一句话：** 基于 `python:3.11-slim-bookworm`，安装依赖后复制代码，暴露 8000 端口，健康检查 `/api/v1/health`，2 个 Uvicorn workers。

**关键层：**
1. 依赖层：`pip install -r requirements.txt`（利用 Docker 层缓存，依赖不变时跳过安装）。
2. 代码层：`COPY src/ scripts/`。
3. 启动命令：`uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --workers 2`。

---

### 📄 `docker/worker/Dockerfile` — Worker 消费者镜像

**一句话：** 和 API 共用基础镜像，额外安装 `pika`（RabbitMQ 客户端），不暴露 HTTP 端口，启动命令 `python -m src.worker.consumer`。

**大白话：** Worker 不需要 HTTP 端口——它不接客，只埋头干活（消费 MQ）。就像一个在后台默默搬砖的工人。

---

### 📄 `docker/rag/Dockerfile` — RAG 服务镜像

**一句话：** 轻量镜像，额外安装 `pymilvus` + `minio` + `pika`，只复制 RAG 相关代码（`src/rag/` + `src/config.py`），1 个 Uvicorn worker，暴露 8001 端口。

**大白话：** RAG 服务是独立部署的，不需要整个项目的代码，只需要 RAG 模块 + 配置文件。就像只派甜点师去分店——不需要带咖啡师和收银员的全套装备。

---

## 📄 `docker-compose.yml` — 12 服务编排文件（v1.0 新增）

**一句话：** 定义完整的本地云原生环境，12 个服务一键启动：APISIX 网关、4 个业务微服务、5 个数据/中间件、1 个前端。

**12 个服务清单：**

| 层 | 服务名 | 镜像/构建 | 端口 | 功能 |
|------|------|------|------|------|
| 网关 | `apisix` | apache/apisix:3.14.1 | 9080/9443/9092 | API 网关 + TLS + Prometheus metrics |
| 网关 | `apisix-dashboard` | apache/apisix-dashboard:3.0.1 | 9000 | 网关管理 UI（profile: dashboard 按需启动） |
| 业务 | `api-service` | docker/api/Dockerfile | 8000 | REST API 入口 |
| 业务 | `agent-worker` | docker/worker/Dockerfile | — | 异步推理消费者 |
| 业务 | `rag-service` | docker/rag/Dockerfile | 8001 | RAG 独立检索服务 |
| 业务 | `ws-service` | docker/api/Dockerfile | — | WebSocket 长连接服务 |
| 数据 | `postgres` | postgres:16-alpine | 5432 | 业务结构化数据 |
| 数据 | `milvus-standalone` | milvusdb/milvus:v2.5.9 | 19530/9091 | 向量数据库（内嵌 etcd） |
| 数据 | `minio` | minio/minio | 9000/9001 | 对象存储（S3 API + Web Console） |
| 数据 | `redis` | redis:7-alpine | 6379 | 缓存 + 分布式锁 + 会话 |
| 中间件 | `rabbitmq` | rabbitmq:4.0-management-alpine | 5672/15672 | 消息队列（AMQP + Management UI） |
| 前端 | `frontend` | nginx:1.27-alpine | 80 | React SPA 静态服务 |

**6 个持久化卷：** pg_data, milvus_data, minio_data, redis_data, rabbitmq_data。

**网络：** `agent-net` 桥接网络，所有服务互联。

---

## 📄 `docker-compose.dev.yml` — 本地开发热重载覆盖文件（v1.0 新增）

**一句话：** 覆盖 `docker-compose.yml` 中的配置，启用热重载（uvicorn --reload）、源码绑定挂载、关闭 Milvus/MinIO（用 Chroma 替代）、debugpy 远程调试端口。

**启动方式：** `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`

**关键差异：**
- api-service / rag-service：启用 `--reload` + 绑定挂载源码，代码修改即时生效。
- 关闭 Milvus/MinIO：开发阶段用 Chroma 本地向量库，不依赖额外基础设施。
- debugpy 端口：5678 远程调试。

---

## 📄 `docker-compose.monitoring.yml` — 监控栈编排（v1.0 新增）

**一句话：** 可选的监控栈——Prometheus（指标采集）、Grafana（可视化面板）、PostgreSQL Exporter、Redis Exporter、Loki（日志聚合）、Promtail（日志采集）。

**启动方式：** `docker compose -f docker-compose.monitoring.yml up -d`

**服务清单：**

| 服务 | 端口 | 功能 |
|------|------|------|
| `prometheus` | 9090 | 指标采集（15 天数据留存） |
| `grafana` | 3000 | 可视化面板（预置 Dashboard） |
| `postgres-exporter` | — | PG 指标导出到 Prometheus |
| `redis-exporter` | — | Redis 指标导出到 Prometheus |
| `loki` | 3100 | 日志聚合 |
| `promtail` | — | 日志采集（容器日志 → Loki） |

---

## 📄 `.gitlab-ci.yml` — 6 阶段 CI/CD 流水线（v1.0 新增）

**一句话：** 从代码提交到生产部署的完整自动化流水线——Lint → Unit Test → SAST → Build → Deploy Staging → Deploy Prod。

**6 个阶段：**

| 阶段 | Job | 内容 |
|------|------|------|
| **Stage 1: Lint** | `python-lint` | ruff check + ruff format check（src/ + tests/） |
| | `frontend-lint` | npm run lint（React 前端） |
| **Stage 2: Test** | `python-test` | pytest + coverage（PostgreSQL + Redis 服务容器） |
| | `frontend-test` | vitest（初期不阻断） |
| **Stage 3: SAST** | `python-security` | bandit + semgrep 安全扫描 |
| | `container-scan` | trivy 容器镜像漏洞扫描（HIGH/CRITICAL） |
| **Stage 4: Build** | `build-api` | Docker Build + Push api-service（docker:27-dind） |
| | `build-rag` | Docker Build + Push rag-service |
| | `build-worker` | Docker Build + Push agent-worker |
| | `build-frontend` | Vite 构建前端静态文件（artifacts） |
| **Stage 5: Deploy Staging** | `deploy-staging` | ArgoCD 自动 sync（Git 仓库更新 image tag） |
| **Stage 6: Deploy Prod** | `deploy-prod` | **手动审批** → ArgoCD sync 生产环境 |

**前提条件：**
1. GitLab Container Registry 已启用
2. K8s 集群已部署（或 Docker Compose 本地验证）
3. ArgoCD 已安装并连接 Git 仓库
4. GitLab CI Variables：REGISTRY_USER / REGISTRY_PASSWORD / KUBECONFIG

**大白话：** 就像汽车工厂的"全自动流水线"——代码提交后自动检查格式（Lint）、跑测试（Test）、安全检查（SAST）、打包成镜像（Build）、自动部署到预发布环境（Staging）、最后手动审批后部署到生产环境（Prod）。任何一步失败都会阻断后续步骤——就像流水线上任何一个质检站发现缺陷，生产线就暂停。

---

## 📄 `Makefile` — 35+ 开发命令（v1.0 新增）

**一句话：** 本地开发常用命令的统一入口，覆盖 Docker Compose 管理、开发热重载、测试、代码质量、Chroma→Milvus 迁移、数据操作、Shell 连接、CI/CD 验证、Helm 验证。

**命令分组：**

| 分组 | 代表命令 | 功能 |
|------|------|------|
| **Docker Compose** | `make up`, `make down`, `make build`, `make logs SVC=api-service` | 服务管理 |
| **开发环境** | `make dev`, `make dev-rag`, `make dev-worker` | 本地无 Docker 开发（热重载） |
| **测试** | `make test`, `make test-cov`, `make test-api`, `make test-rag` | 单元测试 + 覆盖率 |
| **代码质量** | `make lint`, `make lint-fix`, `make format` | ruff 检查/修复/格式化 |
| **迁移** | `make migrate-dry`, `make migrate`, `make migrate-verify` | Chroma → Milvus 迁移 |
| **数据操作** | `make ingest`, `make ingest-incremental` | 知识库入库/增量索引 |
| **Shell 连接** | `make shell-api`, `make pg-connect`, `make redis-connect`, `make mq-console`, `make minio-console` | 容器 Shell + 数据库连接 |
| **CI 本地验证** | `make ci-lint`, `make ci-test`, `make ci-sast`, `make ci-full` | 本地跑完整 CI 流水线 |
| **Helm/K8s** | `make helm-lint`, `make helm-template`, `make helm-template-prod` | Helm Chart 验证 |
| **综合验证** | `make validate` | helm-lint + check-imports |

---

## 📄 `config.yaml` — 配置文件（说明）

项目使用 Pydantic Settings + `.env` 文件管理配置，不再依赖 YAML 配置文件。所有配置项在 `src/config.py` 中定义，通过环境变量或 `.env` 文件覆盖。

---

## 📁 src/models/ — 共享模型与枚举（v2.0 新增）

**一句话：** 存放全项目共享的数据模型和枚举定义，避免循环导入，统一类型规范。

---

### 📄 `models/common.py` — 共享枚举与基础模型

**一句话：** 定义用户角色、通知类型、工单状态等跨模块共享的枚举和 Pydantic 模型。

**核心枚举：**
- `UserRole`：super_admin / admin / agent / viewer
- `TicketStatus`：open / in_progress / resolved / closed / cancelled
- `TicketPriority`：low / medium / high / urgent
- `TicketCategory`：api / billing / technical / account / feature / bug / other
- `NotificationType`：system / handoff / ticket
- `NotificationLevel`：info / warning / error

---

## 📁 src/seed.py — 演示数据注入（v2.0 新增）

**一句话：** 自动生成演示数据（工单、客户、满意度、用户、通知），方便前端展示和功能测试。

**核心函数：**
- `seed_demo_data()`：主入口，调用所有子模块的数据注入。
- `_seed_tickets()`：生成 8 条示例工单（覆盖不同状态、优先级、分类）。
- `_seed_customers()`：生成 5 条示例客户（含标签、画像、时间线）。
- `_seed_satisfaction()`：生成 6 条满意度评价（覆盖 1-5 星分布）。
- `_seed_users()`：生成 4 个角色用户（super_admin/admin/agent/viewer）。
- `_seed_notifications()`：生成 5 条示例通知。

**设计特点：** 幂等注入——如果已有数据则不重复生成；数据之间有业务关联（工单关联客户、满意度关联工单）。

---

## 📁 frontend/src/components/ — 前端管理后台（v2.0 新增）

**一句话：** React + TypeScript 实现的多标签页管理后台，覆盖仪表盘、工单、客户、权限、渠道、通知等模块。

---

### 📄 `components/AdminDashboard.tsx` — 管理后台主组件

**一句话：** 多标签页管理后台，支持仪表盘、工单看板、客户管理、权限管理、渠道配置、通知中心六大功能模块。

**标签页结构：**
- **仪表盘**：KPI 指标卡片（总会话、今日活跃、AI解决率、人工介入率）、实时活动列表、意图分布饼图。
- **工单看板**：工单列表（支持状态筛选）、工单详情、新建工单表单。
- **客户管理**：客户列表、客户画像、标签管理、服务时间线。
- **权限管理**：用户列表、角色分配、权限矩阵。
- **渠道配置**：Web、飞书、Chatwoot 渠道状态管理和配置。
- **通知中心**：通知列表、已读管理、消息推送设置。

**核心设计：**
- `requirePermission(permission)`：前端权限守卫，根据当前用户角色控制按钮/菜单显示。
- `StatCard`：通用统计卡片组件，支持颜色主题。
- `StatusBadge`：状态标签组件（工单状态、优先级可视化）。

---

> 本文档覆盖 src/ 下约 90+ 个 Python 源文件 + frontend/ 前端组件 + deploy/ 部署配置 + docker/ 容器构建 + docker-compose 编排 + CI/CD 流水线 + Makefile，按功能模块分层组织。
> 每个文件用"一句话概括" + "大白话讲解" + "核心类/方法说明" 的结构说明。
> 每个大白话讲解都用了生活中的类比，方便非技术人员理解。
> 版本：v2.0（Cloud-Native 微服务架构 + 业务系统升级），覆盖全部模块。
