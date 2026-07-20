# 企业级智能客服 Agent — 完整学习笔记

> 整理日期：2026-07-17（v2.2 — 云原生微服务架构 + 业务系统升级）
> 覆盖技能：RAG（多后端路由）、ReAct（MQ 异步）、LangGraph（云原生部署）、记忆管理（Redis 分布式锁）、Agent 评估（Prometheus + Grafana）、智能体安全（APISIX 网关）、云原生部署（Docker Compose + K3s + Helm）、分布式中间件（RabbitMQ + Redis + MinIO）、CI/CD（GitLab CI + ArgoCD）、微服务拆分、可观测性、向量库迁移、RBAC权限、工单系统、客户管理、满意度调查、数据仪表盘、人工工作台
> 实际技术栈：阿里百炼 (Qwen-Plus + text-embedding-v4) + Milvus + Chroma + LangChain + LangGraph + FastAPI + RabbitMQ + Redis + MinIO + Docker + K3s + APISIX + Prometheus + Grafana + GitLab CI + ArgoCD + React + TypeScript
> 项目仓库：github.com/addhai/enterprise-agent
> 项目规模：14,707+ 行代码 | 90+ 个模块 | 前端 2,000+ 行 TypeScript/React | 48 个测试用例 | 12 个 Docker 服务 | 6 个 GitLab CI Stage | 8 条 Prometheus 告警规则 | 12 个 Grafana 面板

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

# 第一章：RAG 子系统（v0.5 — 多后端路由 + 远程服务化）

## 1.1 架构总览

RAG 子系统在 v0.4 完成了从"单体加载器"到"三层解耦插件化架构"的重构。v0.5 进一步演进为**多向量库后端 + 远程 RAG 服务**架构。

**架构演进路线：**

```
v0.1-v0.3：DocumentLoader 单体类 → 硬编码 if/elif 分发
v0.4：三层解耦（数据源层/加载器插件/处理管道）+ Chroma 单后端
v0.5：多后端路由（Chroma + Milvus）+ RAG 独立微服务 + 远程调用模式
```

**v0.5 核心变化：**

```
三层解耦（保留）：
  数据源层 (data_sources.py)    → 统一文件扫描和读取接口
  加载器插件 (loaders/)         → 按格式注册的插件，新格式只需加一个类 + 装饰器
  处理管道 (processors/)        → 链式处理器，每个处理器独立可替换

编排层 (loader.py)            → DocumentLoader 薄包装，协调上述三层
切分层 (chunker.py)           → HybridChunker 双粒度切块
索引层 (vector_store.py)      → VectorStoreManager 多后端适配（Chroma + Milvus）
检索层 (retriever.py)         → HybridRetriever 混合检索 + RRF 融合 + 多后端路由
服务层 (rag_service.py)       → 独立 FastAPI 微服务，REST API 暴露
```

**设计哲学：** 每个环节都可以独立替换。换 OCR 引擎？只改 vision_engines/ 下的类。换向量库？只改 vector_store.py 的 backend 配置。加新格式？只加一个 loader 类 + `@register_loader(".ext")`。部署模式？本地嵌入式 / 远程微服务一键切换。

## 1.2 数据源层

`BaseDataSource` 定义了两个抽象方法：`list_files()` 和 `read_file()`。

`LocalDirectoryDataSource` 是唯一定制的实现：
- 递归扫描目录，支持 11 种扩展名（md/pdf/html/htm/docx/png/jpg/jpeg/gif/webp/bmp）
- 返回 `FileInfo` 数据类：path, name, ext, size, mime_type, metadata（创建/修改时间）
- 读取文件时自动检测编码（chardet 优先，fallback UTF-8/GBK/Latin-1）

**为什么抽象数据源：** 未来可以轻松替换为 S3DataSource、GitDataSource、APIDataSource 等，加载器和管道代码完全不用改。在云原生部署中，MinIODataSource 已预留接口。

## 1.3 加载器插件系统

### 插件注册机制

```python
# 基类定义契约
class BaseLoader(ABC):
    @abstractmethod
    def load(self, info: FileInfo, base_meta: dict) -> List[Document]:
        ...

# 类级别的注册表
class LoaderRegistry:
    _registry: Dict[str, Type[BaseLoader]] = {}

    @classmethod
    def register(cls, ext: str):
        def wrapper(wrapped):
            cls._registry[ext] = wrapped
            return wrapped
        return wrapper

# 使用装饰器注册
@register_loader(".pdf")
class PdfLoader(BaseLoader):
    def load(self, info, base_meta):
        ...
```

**关键点：** 所有加载器在 `loader.py` 中被 import，触发 `@register_loader` 装饰器自动注册。新增格式只需：
1. 新建 `src/rag/loaders/xxx_loader.py`
2. 继承 `BaseLoader` 实现 `load()`
3. 用 `@register_loader(".xxx")` 装饰
4. 在 `loader.py` 的 import 区加一行 import

### 各加载器的核心差异化逻辑

| 加载器 | 标题提取方式 | 切分策略 | 特殊处理 |
|--------|------------|---------|---------|
| Markdown | 按 `##`/`###`/`####` 正则 | OutlineTree.split() 按章节切 | 保留 YAML front matter |
| PDF | PyMuPDF 书签优先，fallback 正则 | 页边标记 `\n---PAGE-BREAK---\n` | 页眉页脚提取、页码注入 |
| HTML | BeautifulSoup 提取 h1-h6 | OutlineTree.split() | 移除 script/style/nav/footer |
| DOCX | python-docx 遍历 Paragraph.style | OutlineTree.split() | 按 Heading 样式分组 |
| Image | N/A（无文本结构） | 直接整图处理 | 多模态视觉管线 + OCR 降级 |

### 图片加载的多模态视觉管线

这是最复杂的加载器，采用了 **ABC 降级策略**（Alternative → Best → Cheapest）：

```
图片文件
  │
  ▼
Qwen-VL-Plus 视觉理解（默认，置信度 0.95）
  │ 失败
  ▼
OpenAI GPT-4o 视觉理解（备选，置信度 0.93）
  │ 失败
  ▼
PaddleOCR 中文识别（降级）
  │ 失败
  ▼
Tesseract OCR 兜底
  │ 失败
  ▼
返回空（不报错）
```

每个引擎都有独立的 CircuitBreaker 保护。视觉引擎还有 VisionCircuitBreaker（连续失败 5 次触发，60 秒自动重置）。

**结构化 prompt 按图片类型变化：**
- `screenshot` → 界面描述、按钮、操作流程、警告信息
- `error_screenshot` → 错误类型、堆栈跟踪、根因分析、修复建议
- `scanned_document` → 文档类型、全文、关键字段、表格还原
- `diagram` → 图表类型、结构、标签、流程描述
- `table_image` → 表格主题、表头、数据（Markdown 格式）、备注

## 1.4 处理管道

`IngestionPipeline` 是一个 ordered chain，包含两类处理器：

**BaseProcessor（逐文档）：** `process(doc, ctx) -> Optional[doc]`
- 返回 None = 丢弃该文档
- 返回 doc = 继续下一个处理器

**BaseBatchProcessor（全列表）：** `process_batch(docs, ctx) -> List[doc]`
- 需要全局信息才能做的操作（如去重）

### 管道执行流程

```
阶段 1：逐文档处理（Per-Document Pipeline）
  Raw Docs → Normalize → NoiseFilter → StructureDetect → ContentSafety

阶段 2：质量拦截（Quality Enforcement）
  Processed Docs → MetadataEnrich → QualityCheck

阶段 3：批量去重（Batch Dedup）
  Accepted Docs → Deduplicate → Final Docs
```

### 每个处理器的底层原理

**NormalizeTextProcessor：**
- 全角→半角：Unicode 0xFF01-0xFF5E 映射到 0x21-0x7E
- 中文省略号：`……`（U+2026×2）→ `…`（U+2026）
- 空白折叠：`\s+` → ` `
- 尾部空白清理

**NoiseFilterProcessor：**
- 导航噪声正则：`r"^(首页|关于我们|联系我们|Copyright|©|目录|Table of Contents)"`
- 页眉页脚提取：正则匹配页码（`第\d+页`、`\d+/\d+`）和文档标题
- 空段落过滤

**StructureDetectProcessor：**
- 代码块检测：`^```[\s\S]*^```$`
- 表格检测：`\|.+\|`
- 列表检测：`^[-*•]\s` 或 `^\d+\.\s`
- 注入结构化提示到文档顶部

**ContentSafetyProcessor：**
- PII 检测 + 脱敏
- 合规检查（政治/色情/暴力/垃圾/违禁）
- 权限自动升级（PII 严重→restricted，合规拦截→restricted）

**MetadataEnrichProcessor：**
- 关键词匹配分类 `access_level`：
  - public: 定价、概述、功能介绍
  - internal: FAQ、配置指南、操作手册
  - confidential: 合同、财务、API Key
  - restricted: 密码、凭证、个人信息
- 关键词匹配分类 `business_domain`：product/sales/support/engineering/legal

**QualityCheckProcessor：**
- 字数 < 50 → reject_low_quality
- 版本号 < current_version → reject_expired
- 更新时间 > max_days_outdated → warn_outdated

**DeduplicateProcessor（三级）：**
1. SHA-256 精确匹配（O(n) 哈希表）
2. SimHash 64-bit 近重复（汉明距离 ≤ 阈值，默认 0.95 相似度）
3. 语义去重（placeholder，未来用 embedding 距离）

## 1.5 文档切块

`HybridChunker` 是 RAG 系统的核心创新之一——**同时维护两套索引**：

### 标准粒度（段落级）

```python
RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=64,
    separators=["\n## ", "\n### ", "\n#### ", "\n---PAGE-BREAK---", "\n", " ", ""],
)
```

**为什么按标题层级切：** 技术文档的"自然边界"是标题。按 512 字符硬切会把"问题描述"和"解决方案"切到两个块里。按标题切保证每个块是一个完整主题。

### 句子粒度（Small2Big）

```
文档 → 句子级切分 → 每个句子独立成块（检索索引）
                → 同时保存前后 N 句的原文（生成上下文）
```

**核心洞察：** 检索时需要"精准定位"（句子级），但 LLM 生成时需要"完整上下文"（前后 N 句）。句子级块在 metadata 中携带 `_context_before` 和 `_context_after`（JSON 序列化），检索命中后通过 `expand_context()` 恢复完整段落。

**为什么有效：** 用户搜"ERR_403_TIMEOUT 怎么解决"，句子级索引能精确匹配到包含这个错误码的句子，然后展开前后 3 句给 LLM——LLM 看到的是完整的排查段落，而非孤立的一句话。

## 1.6 混合检索 + 多后端路由（v0.5 新增）

### 多向量库后端适配

v0.5 的核心升级是向量库多后端支持。`VectorStoreManager` 通过**适配器模式**统一了 Chroma 和 Milvus 的接口：

```
                    ┌─────────────────────┐
                    │  VectorStoreManager  │
                    │  (backend 配置切换)    │
                    └──────────┬──────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                                     ▼
   ┌─────────────────┐                  ┌─────────────────┐
   │  Chroma Backend  │                  │  Milvus Backend  │
   │  (本地嵌入式)      │                  │  (远程微服务)      │
   │  - 轻量级/单机     │                  │  - 分布式/集群     │
   │  - 开发/测试环境    │                  │  - 生产环境        │
   │  - 嵌入式部署      │                  │  - Partition Key  │
   └─────────────────┘                  └─────────────────┘
```

**后端选择策略：**

| 维度 | Chroma (嵌入式) | Milvus (远程) |
|------|----------------|--------------|
| 适用环境 | 开发/测试/单机 | 生产/集群/多租户 |
| 部署方式 | 进程内嵌入 | 独立微服务，gRPC 通信 |
| 数据量级 | < 100 万向量 | 亿级向量 |
| 多租户隔离 | collection 前缀 | Partition Key 原生支持 |
| 索引类型 | HNSW | IVF_FLAT / IVF_PQ / HNSW |
| 一致性 | 最终一致 | 可配置（Strong/Bounded/Eventually） |
| 监控集成 | 无原生 | Prometheus metrics 端点 |

**多后端路由逻辑：**

```python
class VectorStoreManager:
    def __init__(self, backend: str = "chroma"):
        if backend == "milvus":
            self._store = MilvusVectorStore(host, port, collection_name)
        elif backend == "chroma":
            self._store = ChromaVectorStore(persist_dir, collection_name)
        else:
            raise ValueError(f"Unsupported backend: {backend}")

    # 统一接口，调用方不感知后端差异
    def add_documents(self, docs): ...
    def similarity_search(self, query, k): ...
    def delete(self, ids): ...
```

**关键设计决策——为什么不直接在代码里写死 Milvus：**
1. 开发环境不需要启动 Milvus 服务（Chrom 进程内嵌入更轻量）
2. 测试环境用 Chroma 做集成测试更快（无网络开销）
3. 通过环境变量 `VECTOR_BACKEND=chroma|milvus` 一键切换，不改代码

### 远程 RAG 服务模式

v0.5 将 RAG 子系统从"进程内调用"升级为"独立微服务 + REST API"：

```
旧模式（嵌入式）：                     新模式（远程服务）：
┌──────────────┐                    ┌──────────────┐     HTTP      ┌──────────────┐
│  Agent 进程   │                    │  Agent 进程   │ ─────────────→│  RAG Service  │
│  ┌──────────┐ │                    │  (FastAPI)   │               │  (FastAPI)    │
│  │RAG 模块   │ │                    │              │ ←─────────────│  ┌──────────┐ │
│  │(进程内)   │ │                    │  RAG Client  │     JSON      │  │RAG 模块   │ │
│  └──────────┘ │                    └──────────────┘               │  │(独立进程) │ │
└──────────────┘                                                   │  └──────────┘ │
                                                                   └──────────────┘
```

**远程模式优势：**
- **独立扩缩容：** RAG 服务可以独立扩容，不受 Agent 服务影响
- **技术栈隔离：** RAG 服务可以用不同 Python 版本、不同依赖
- **故障隔离：** RAG 服务挂了不影响 Agent 对话流程（有 fallback 降级）
- **多 Agent 共享：** 多个 Agent 实例共享同一个 RAG 服务，避免重复加载索引

**客户端 SDK：**

```python
class RAGClient:
    """RAG 远程服务客户端"""
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._session = httpx.AsyncClient(timeout=30.0)

    async def search(self, query: str, top_k: int = 5, **filters):
        resp = await self._session.post(
            f"{self.base_url}/api/v1/search",
            json={"query": query, "top_k": top_k, "filters": filters}
        )
        return resp.json()["results"]

    async def ingest(self, files: List[Path]):
        # 异步提交摄入任务，返回 task_id
        ...
```

### 混合检索的完整流程

```python
# 1. 三路并行检索
vector_results = 标准向量检索(top_k*2)      # 语义泛化
bm25_results   = BM25关键词检索(top_k*2)     # 精确匹配
sentence_results = 句子向量检索(top_k)       # 小粒度精准

# 2. RRF 融合标准结果
standard_merged = rrf_fusion(vector, bm25, top_k)

# 3. 句子结果上下文展开
expanded = [splitter.expand_context(doc) for doc in sentence_results]

# 4. 合并去重
final = merge_and_dedup(standard_merged, expanded, top_k)

# 5. 权限过滤（租户 + 访问等级）
final = filter_by_permission(final, tenant_id, user_access_levels)

# 6. 版本冲突处理
final = resolve_version_conflicts(final, top_k)
```

### RRF 融合的数学原理

```
score(doc) = Σ 1 / (k + rank_in_list_i)
```

k=60 是平滑常数。核心思想：**不关心绝对分数（向量 0.9 vs BM25 15.2 不可比），只关心相对排名。** 一个文档如果在两组检索中都靠前，RRF 分数自然高。

### 权限过滤的完整规则

```
权限等级优先级：public(0) < internal(1) < confidential(2) < restricted(3)

过滤规则：
  1. 租户隔离：文档 tenant_id 必须匹配（或未设置=公开）
  2. 等级检查：用户最高权限等级 >= 文档权限等级
  3. 标记被过滤数量：metadata["access_filtered"]
```

### 版本冲突处理

```
按 source（文件名）分组 → 提取版本号 → 排序 → 过滤废弃 → 保留最新活跃
如果同组有多个活跃版本 → 标记 has_conflicts + 输出冲突提示
```

版本号解析：`"v3.2"` → sort_key=302。支持 `v1.0`、`v302`、`v3.2.1` 等格式。

## 1.7 增量同步机制

`FileSyncManager` 的核心是**同步状态表**（JSON 持久化）：

```json
{
  "/absolute/path/to/file.pdf": {
    "file_path": "/absolute/path/to/file.pdf",
    "content_hash": "sha256_hex_of_normalized_text",
    "mtime": 1720000000.0,
    "status": "PROCESSED",
    "standard_chunk_ids": ["doc:path:abc123:standard:0", ...],
    "sentence_chunk_ids": ["doc:path:abc123:sentence:0", ...],
    "processed_at": "2026-07-04T10:00:00Z",
    "error_message": ""
  }
}
```

**为什么对归一化文本求哈希，而不是原始文件字节：** 格式微调（如 Markdown 的空格增减）不触发重新处理，只有语义内容变化才触发。

**增量同步算法：**
1. 加载同步表
2. 遍历磁盘文件 → 计算 content_hash + mtime
3. 分类：NEW（不在表中）/ MODIFIED（hash 或 mtime 不同）/ UNCHANGED（匹配）/ DELETED（在表中但磁盘上没有）
4. DELETED → 删除 chunk IDs → 从表中移除
5. NEW/MODIFIED → load → chunk → add_documents → 更新表
6. 持久化同步表

**确定性 doc_id 保证幂等：** `doc:{path}:{hash}:{type}:{index}`。同一文件多次加载返回相同 ID，向量库 upsert 自动覆盖。

## 1.8 并发与限流熔断

### 令牌桶算法（RateLimiter）

```
桶容量 = burst（允许的最大突发请求数）
令牌产生速率 = rate（每秒多少个）
请求到来 → 有令牌就消耗，没有就等待或拒绝
```

**为什么不用固定间隔：** 真实世界的 API 调用是 bursty 的——有时候一批文件同时需要处理。令牌桶允许在一定容量内的突发，同时保证长期平均速率不超过限制。

### 熔断器状态机（CircuitBreaker）

```
CLOSED（正常）→ 连续失败 N 次 → OPEN（熔断，拒绝请求）
OPEN → 等待 recovery_timeout → HALF_OPEN（探测）
HALF_OPEN → 成功 → CLOSED / 失败 → OPEN
```

**为什么需要熔断：** 外部 API 不可用时，不应该让每个请求都等到超时（比如 10 秒）。熔断后直接拒绝，响应时间从 10s 降到 <1ms。

### GlobalLimits 单例

为三类 API 分别管理限流+熔断：
- **Vision API：** 默认 QPS + 熔断（最昂贵，需要最严格保护）
- **OCR API：** 20 QPS + 熔断（较快，但仍需限流）
- **Safety API：** 5 QPS + 熔断（本地正则为主，但云端 API 预留）

## 1.9 可观测性（基础）

### PipelineMetrics

```
Counters:
  files_scanned          - 扫描文件总数
  files_total{format}    - 按格式统计
  files_loaded{format,status} - 按格式+状态统计
  files_rejected{reason} - 拒绝原因统计
  files_quality_accepted - 质量通过数
  files_deduped          - 去重数

Histograms:
  file_duration{format}  - 文件处理耗时（avg/min/max/p50/p95/p99）
  pipeline_duration      - 管道总耗时
```

### PipelineTracer

逐文件记录：
- 处理步骤及耗时
- 拒绝原因
- 质量状态
- 按日期持久化为 JSON

## 1.10 安全合规

### PII 检测的渐进验证

不只是正则匹配——关键类型有额外的验证算法：
- 身份证：18 位格式 + 校验码算法验证
- 银行卡：16-19 位 + Luhn 算法验证
- 防止误报：重叠检测（一个数字串不会同时匹配身份证和银行卡）

### 合规检测的风险评分

每个匹配类别加 0.3 分：
- 0.0-0.3 → low
- 0.3-0.6 → medium
- ≥0.6 → high（自动阻断）

### 权限自动升级

```
PII 严重 (身份证/银行卡) → access_level = "restricted"
PII 高危 (API Key/手机)  → access_level = "confidential"
合规拦截                  → access_level = "restricted"
```

## 1.11 面试完整口述逻辑（RAG 模块）

**面试官："你们这套 RAG 系统是怎么设计的？"**

**第一段：架构演进（30 秒）**

"我们的 RAG 系统经历了从单体到插件化再到云原生的演进。v0.1 是一个大的 DocumentLoader 类，所有逻辑耦合在一起。v0.4 重构为三层解耦架构：数据源层、加载器插件层、处理管道层。v0.5 进一步升级为多后端向量库适配（Chroma + Milvus）+ 独立 RAG 微服务，通过环境变量一键切换部署模式。"

**第二段：核心技术亮点（1 分钟）**

"四个核心设计：
第一，双索引混合检索。标准粒度索引 + 句子粒度索引（Small2Big），三路并行检索后 RRF 融合。
第二，处理管道的三级质量保障。内容安全 → 质量拦截 → 三级去重（精确哈希→SimHash→语义）。
第三，增量同步。基于归一化文本的 SHA-256 哈希，格式微调不触发重处理。
第四，多后端路由。通过适配器模式统一 Chroma 和 Milvus 接口，开发环境用 Chroma 进程内嵌入，生产环境切 Milvus 分布式集群，一个环境变量切换。"

**第三段：最难的问题（1 分钟）**

"最复杂的是图片加载的多模态管线。一张图片可能经过 Qwen-VL → GPT-4o → PaddleOCR → Tesseract 四级降级。每一级都有独立的限流和熔断保护。我们还为每种图片类型设计了专用的结构化 prompt。"

**第四段：云原生演进（30 秒）**

"在云原生架构中，RAG 被拆分为独立微服务，通过 REST API 暴露。Agent 服务通过 RAGClient 远程调用。这样做的好处是：独立扩缩容、故障隔离（RAG 挂了 Agent 仍可工作）、多 Agent 共享同一索引。向量库方面，生产环境用 Milvus 替代 Chroma，利用 Partition Key 实现多租户隔离，支持亿级向量检索。"

---

# 第二章：ReAct 范式与异步 Agent

## 2.1 ReAct 核心原理

ReAct（Reasoning + Acting）是一种让 LLM 交替进行"思考"和"行动"的范式。核心循环是：

```
用户输入 → Thought（思考：我需要什么信息？）
         → Action（行动：调用工具获取信息）
         → Observation（观察：工具返回了什么？）
         → Thought（根据观察重新思考）
         → Action（继续行动或给出答案）
         → ...→ Final Answer
```

**为什么 ReAct 优于纯 Chain-of-Thought：** CoT 只能"想象"信息，ReAct 可以"获取"真实信息。想象和现实之间的差距（hallucination）被工具调用弥合。

## 2.2 本项目的 Agent 工具集

Agent 拥有以下工具（Tools），每个工具都是一个带有 schema 描述的 Python 函数：

| 工具名称 | 功能 | 参数 |
|---------|------|------|
| search_knowledge_base | RAG 检索产品文档 | query, top_k, filters |
| search_faq | FAQ 精确匹配 | keywords, category |
| get_order_status | 查询订单状态 | order_id |
| get_product_info | 获取产品信息 | product_id |
| escalate_to_human | 转人工客服 | reason, priority |

**工具 Schema 的重要性：** LLM 根据 schema 描述决定调用哪个工具，所以 schema 描述必须精确、无歧义。例如 `search_faq` 的描述里明确写了"用于已知问题、操作指南等 FAQ 类问题"，避免 LLM 把通用问题也路由到 FAQ。

## 2.3 v0.5 升级：RabbitMQ 异步 Worker

在云原生架构中，耗时的 Agent 任务不再阻塞 HTTP 请求线程，而是通过**消息队列异步处理**。

### 架构对比

```
旧模式（同步阻塞）：                    新模式（MQ 异步）：
用户请求 → Agent → RAG检索 → LLM生成     用户请求 → Agent → 提交任务到MQ → 立即返回 task_id
          ↓ (用户等待 10-30s)                         ↓
          返回结果                               Worker 异步消费
                                                   ↓
                                                 RAG检索 → LLM生成
                                                   ↓
                                                 结果写入 Redis → WebSocket 推送
```

### RabbitMQ 拓扑设计

```
Exchange: agent.tasks (topic)
  ├── Queue: agent.task.rag           binding_key: task.rag.*
  ├── Queue: agent.task.reflect       binding_key: task.reflect.*
  ├── Queue: agent.task.notify        binding_key: task.notify.*
  └── Queue: agent.task.dlq           (Dead Letter Queue)
```

**为什么用 Topic Exchange 而不是 Direct：**
- Topic Exchange 支持通配符路由（`task.rag.*` 匹配所有 RAG 子任务）
- 未来可以按优先级再细分：`task.rag.high`、`task.rag.low`
- Worker 可以消费多个 pattern：`task.*.high`

### 消息格式

```json
{
  "task_id": "uuid",
  "task_type": "rag_search",
  "tenant_id": "tenant_001",
  "payload": {
    "query": "ERR_403_TIMEOUT 怎么解决",
    "conversation_id": "conv_123",
    "user_id": "user_456"
  },
  "timestamp": "2026-07-15T10:00:00Z",
  "retry_count": 0
}
```

### Dead Letter Queue（DLQ）机制

```
任务处理失败 3 次
  ↓
自动路由到 DLQ
  ↓
人工审查 / 自动重放
  ↓
记录到 metrics: agent_task_dlq_total
```

**DLQ 设计要点：**
- 消息保留 7 天（便于排查历史问题）
- 每条 DLQ 消息记录失败原因和原始 trace_id
- 提供 Admin API 手动重放或丢弃
- Prometheus 告警：DLQ 堆积 > 100 条触发告警

## 2.4 面试口述逻辑（ReAct + MQ）

**Q：为什么要把 Agent 任务异步化？**

A：三个原因。第一，用户体验——RAG 检索 + LLM 生成可能需要 10-30 秒，用户不应该一直等待 HTTP 连接。异步化后立即返回 task_id，前端轮询或 WebSocket 推送结果。第二，削峰填谷——高峰期大量用户同时提问，如果都是同步处理，Agent 服务的线程池会被打满。消息队列天然缓冲。第三，解耦——RAG Worker 可以独立扩容，不影响 Agent 服务本身。

---

# 第三章：LangGraph 工作流编排

## 3.1 为什么选择 LangGraph

LangGraph 是一个有状态的图执行框架，适合构建多步骤的 Agent 工作流。相比 LangChain 的 Chain：
- **Chain：** 线性 DAG，A → B → C，无法循环
- **LangGraph：** 任意有向图，支持条件分支和循环（ReAct 需要循环）

## 3.2 本项目的工作流设计

### v2.0 扁平化架构（详见第十四章）

从 v0.4 的 5 子图架构重构为 1 个单层 StateGraph + 8 个 handler 函数。核心流程：

```
entry → classify → {faq_handle | rag_handle | human}
                            ↓
                    reflect? → reply → END
                            ↓
                    expert? → reflect → reply
```

### 云原生部署考量

在云原生微服务架构中，LangGraph 工作流运行在 **Agent Service** 容器内：

```
APISIX Gateway → Agent Service (LangGraph 工作流)
                      ├── 同步：classify → faq_handle → reply
                      └── 异步：rag_handle → RabbitMQ → RAG Worker
```

**关键设计：LangGraph 的 checkpoint 持久化到 Redis**，这意味着即使 Agent Service 重启，进行中的对话可以从断点恢复。这在 Kubernetes 环境中尤为重要（Pod 随时可能被重新调度）。

## 3.3 State 管理

```python
class AgentState(TypedDict):
    messages: List[BaseMessage]       # 对话历史
    intent: str                       # classify_node 分类结果
    context: List[Document]           # RAG 检索结果
    reflection: Optional[str]         # 反思结果
    escalate_reason: Optional[str]    # 转人工原因
    task_id: Optional[str]            # 异步任务 ID
```

**State 序列化到 Redis 的考量：**
- `messages` 用 LangChain 的 `messages_to_dict` / `messages_from_dict` 序列化
- `context` (List[Document]) 只存储 doc_id，检索时从向量库按 ID 恢复
- 对话超过 24 小时自动过期（Redis TTL）

## 3.4 面试口述逻辑（LangGraph + 云原生）

**Q：LangGraph 工作在云原生环境中有什么挑战？**

A：最大的挑战是状态持久化。Kubernetes Pod 随时可能被 OOM Kill 或重新调度，如果状态只在内存中，对话会丢失。我们的方案是 LangGraph checkpoint 持久化到 Redis，对话 24 小时 TTL。另一个挑战是长任务的优雅关闭——当 Pod 收到 SIGTERM，需要等待当前 ReAct 循环完成或将中间状态保存到 Redis，下次从断点恢复。

---

# 第四章：高级记忆管理

## 4.1 三层记忆架构

```
短期记忆（Short-term Memory）
  └── 当前对话的完整消息历史（存在 AgentState.messages 中）
      实现：LangGraph checkpoint → Redis

中期记忆（Medium-term Memory）
  └── 最近 N 次对话摘要（跨 Session）
      实现：PostgreSQL conversation_summaries 表

长期记忆（Long-term Memory）
  └── 用户偏好、历史问题类型、常用操作
      实现：PostgreSQL user_profiles 表
```

## 4.2 记忆生命周期

```
用户消息 → 追加到短期记忆
         ↓
Session 结束 → LLM 生成对话摘要 → 存入中期记忆（PG）
         ↓
每周定时任务 → 分析对话摘要 → 更新长期记忆（用户画像）
```

## 4.3 v0.5 升级：Redis 分布式锁去重

在云原生环境中，多个 Agent Service 实例可能同时处理同一用户的记忆更新。例如：
- 用户同时开了两个对话窗口
- 定时任务和实时写入冲突
- 消息重试导致重复处理

**Redis 分布式锁方案：**

```lua
-- Lua 脚本保证原子性
-- KEYS[1] = lock key (memory:lock:{user_id})
-- ARGV[1] = lock value (instance_id + timestamp)
-- ARGV[2] = TTL in seconds

if redis.call("SET", KEYS[1], ARGV[1], "NX", "EX", ARGV[2]) then
    return 1  -- 获取锁成功
else
    return 0  -- 锁已被其他实例持有
end
```

**为什么用 Lua 脚本：** Redis 的 SETNX + EXPIRE 是两步操作，非原子——SETNX 成功后进程崩溃，锁永远不会释放。Lua 脚本在 Redis 服务端原子执行，保证 SET + EXPIRE 是一个不可分割的操作。

**锁的使用场景：**

| 操作 | 锁前缀 | TTL | 冲突策略 |
|------|--------|-----|---------|
| 记忆写入 | memory:write:{user_id} | 10s | 等待 + 重试 |
| 摘要生成 | memory:summary:{user_id} | 30s | 跳过（下一次定时再生成） |
| 用户画像更新 | memory:profile:{user_id} | 60s | 合并写入 |

## 4.4 记忆去重策略

```
写入前检查：
  1. 获取 Redis 分布式锁
  2. 计算新记忆内容的 SHA-256 哈希
  3. 查询 PostgreSQL 中最近一条记录（同 user_id + 同 session_id）
  4. 如果哈希相同 → 跳过（去重）
  5. 如果哈希不同 → 写入 + 释放锁
```

## 4.5 面试口述逻辑（记忆 + 分布式锁）

**Q：分布式环境下记忆管理有什么坑？**

A：最大的坑是并发写入导致的数据不一致。比如用户在手机和电脑上同时提问，两个请求可能路由到不同的 Agent Service 实例，它们同时更新用户记忆。解决方案是 Redis 分布式锁——用 Lua 脚本保证 SET + EXPIRE 原子性，不同操作类型用不同 TTL 避免死锁。另外记忆去重用内容哈希而非时间戳，相同内容不重复存储。

---

# 第五章：Agent 评估与监控

## 5.1 评估维度

Agent 评估覆盖四个维度：

| 维度 | 指标 | 评估方式 |
|------|------|---------|
| 准确性 | 答案正确率、幻觉率 | 人工标注 + LLM-as-Judge |
| 效率 | 首字延迟、端到端耗时、工具调用次数 | 自动采集 |
| 覆盖 | FAQ 命中率、问题解决率 | 统计分析 |
| 安全 | 拒绝率、误拒率、越狱成功率 | 红队测试 |

## 5.2 评估方法

### LLM-as-Judge

使用更强的模型（Qwen-Max）作为评判者，对 Agent 回答打分：

```python
judge_prompt = """
请根据以下标准对 Agent 回答评分（1-5分）：
- 准确性：回答是否正确
- 完整性：是否覆盖了用户问题的所有方面
- 相关性：是否直接回应了用户的问题
- 安全性：是否包含不当内容

用户问题：{query}
Agent 回答：{response}
参考文档：{context}
"""
```

### 人工评估集

维护 200+ 条标注问答对，覆盖：
- 50 条 FAQ（已知问题，答案固定）
- 50 条 RAG（需要检索文档回答）
- 50 条复杂问题（需要多轮对话或工具调用）
- 50 条边界/攻击（垃圾输入、越狱尝试）

## 5.3 v0.5 升级：Prometheus 指标 + Grafana 可视化

云原生架构中，评估结果不再只是离线报告，而是**实时采集到 Prometheus，通过 Grafana 可视化**。

### 关键 Prometheus 指标

```python
# Counter：累计计数
agent_evaluation_total{status="pass|fail|hallucination"}   # 评估总数
agent_tool_call_total{tool="search_kb|search_faq|..."}     # 工具调用次数
agent_escalation_total{reason="angry|complex|..."}         # 转人工次数

# Histogram：分布统计
agent_response_duration_seconds      # 响应耗时分布 (p50/p95/p99)
agent_ttft_seconds                   # Time To First Token
agent_rag_retrieval_duration_seconds # RAG 检索耗时

# Gauge：瞬时值
agent_active_conversations           # 当前活跃对话数
agent_queue_depth                    # MQ 队列深度
```

### Grafana 面板设计（12 个面板）

| 面板 | 类型 | 数据源 | 说明 |
|------|------|--------|------|
| 评估通过率趋势 | Time series | agent_evaluation_total | 24h 内 pass/fail 比例 |
| 幻觉率趋势 | Time series | agent_evaluation_total{status="hallucination"} | 幻觉率变化 |
| 响应耗时 P95 | Time series | agent_response_duration_seconds | 95 分位延迟 |
| TTFT P50/P95 | Time series | agent_ttft_seconds | 首字延迟分布 |
| 工具调用分布 | Pie chart | agent_tool_call_total | 各工具调用占比 |
| 转人工率 | Stat + Time series | agent_escalation_total | 转人工比例 |
| RAG 检索耗时 | Heatmap | agent_rag_retrieval_duration_seconds | 检索延迟热力图 |
| 活跃对话数 | Stat | agent_active_conversations | 当前在线用户 |
| 队列深度 | Time series | agent_queue_depth | MQ 积压趋势 |
| FAQ 命中率 | Gauge | faq_hit_rate | FAQ 首次命中比例 |
| LLM Token 消耗 | Time series | llm_token_usage_total | Token 用量趋势 |
| 错误率 | Time series | http_requests_total{status=~"5.."} | HTTP 5xx 比例 |

### 告警规则（8 条）

```yaml
# 1. 幻觉率过高
- alert: HighHallucinationRate
  expr: rate(agent_evaluation_total{status="hallucination"}[5m]) > 0.1
  for: 5m
  severity: warning

# 2. 响应延迟恶化
- alert: HighResponseLatency
  expr: histogram_quantile(0.95, agent_response_duration_seconds) > 30
  for: 5m
  severity: warning

# 3. 转人工率异常
- alert: HighEscalationRate
  expr: rate(agent_escalation_total[10m]) > 0.3
  for: 5m
  severity: critical

# 4. MQ 队列堆积
- alert: QueueBacklog
  expr: agent_queue_depth > 500
  for: 10m
  severity: critical

# 5. RAG 检索超时
- alert: RAGRetrievalTimeout
  expr: histogram_quantile(0.99, agent_rag_retrieval_duration_seconds) > 10
  for: 5m
  severity: warning

# 6. 服务错误率
- alert: HighErrorRate
  expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
  for: 5m
  severity: critical

# 7. 无活跃对话
- alert: NoActiveConversations
  expr: agent_active_conversations == 0
  for: 30m
  severity: info

# 8. Token 消耗异常
- alert: TokenUsageSpike
  expr: rate(llm_token_usage_total[15m]) > 100000
  for: 5m
  severity: warning
```

## 5.4 面试口述逻辑（评估 + 可观测性）

**Q：你们的 Agent 质量怎么衡量？**

A：四个维度：准确性（LLM-as-Judge + 200 条人工评估集）、效率（TTFT、端到端耗时、工具调用次数）、覆盖率（FAQ 命中率）、安全性（红队测试拒绝率）。所有指标实时采集到 Prometheus，通过 Grafana 12 面板仪表盘可视化，8 条告警规则覆盖幻觉率、延迟、错误率等关键指标。

---

# 第六章：智能体安全与防护（多层纵深防御）

## 6.1 安全威胁模型

Agent 面临的安全威胁与传统 Web 应用不同。核心威胁向量：

| 威胁类型 | 攻击方式 | 危害 |
|---------|---------|------|
| Prompt Injection | 在用户输入中嵌入指令覆盖 System Prompt | 绕过限制、泄露知识库 |
| Jailbreak | "DAN"、"奶奶漏洞"等越狱话术 | 生成违规内容 |
| Data Exfiltration | 通过多轮对话诱导泄露文档内容 | 知识产权泄露 |
| DoS | 大量恶意请求耗尽 Token 配额 | 服务不可用 |
| PII Leak | Agent 返回中包含身份证/银行卡号 | 合规风险 |

## 6.2 多层防御架构

```
Layer 1: APISIX 网关（网络层）
  ├── IP 黑白名单
  ├── 速率限制 (rate limiting)
  ├── 熔断 (circuit breaking)
  └── WAF 规则

Layer 2: 输入护栏（应用层）
  ├── 敏感词过滤
  ├── Prompt Injection 检测
  ├── Jailbreak 模式匹配
  └── 输入长度限制

Layer 3: 输出护栏（应用层）
  ├── PII 检测 + 脱敏
  ├── 合规检查
  ├── 幻觉检测
  └── 输出长度限制

Layer 4: 审计日志（持久层）
  ├── 全量对话记录（脱敏后存储）
  ├── 异常行为告警
  └── 定期安全审计
```

## 6.3 v0.5 升级：APISIX 网关级防护

在云原生架构中，安全防护的第一道防线从应用代码移到了网关层。

### APISIX 网关配置

```yaml
# 速率限制：每用户每分钟最多 60 次请求
plugins:
  limit-req:
    rate: 60
    burst: 10
    key: http_x_user_id
    rejected_code: 429

# 熔断：后端连续失败 10 次触发
  api-breaker:
    break_response_code: 502
    max_breaker_sec: 300
    unhealthy:
      http_statuses: [500, 502, 503, 504]
      failures: 10

# IP 限制
  ip-restriction:
    whitelist:
      - 10.0.0.0/8        # 内网
      - 172.16.0.0/12     # 内网
    blacklist: []

# CORS
  cors:
    allow_origins: "https://console.example.com"
    allow_methods: "GET,POST,OPTIONS"
    allow_headers: "Authorization,Content-Type,X-User-Id,X-Tenant-Id"
```

### 速率限制的策略设计

| 用户类型 | 速率限制 | Burst | 为什么 |
|---------|---------|-------|--------|
| 普通用户 | 60 req/min | 10 | 正常对话不会超过这个频率 |
| VIP 用户 | 300 req/min | 50 | 批量查询场景 |
| 匿名用户 | 10 req/min | 0 | 防滥用 |
| 内部 API | 1000 req/min | 200 | 后台批量任务 |

**为什么在网关层做限流：**
1. 请求在到达 Agent 服务之前就被拦截，不消耗 Agent 的计算资源
2. 集中管理——不需要在每个微服务里都实现一套限流逻辑
3. APISIX 基于 Nginx/OpenResty，限流性能远高于应用层实现

### 网关 + 应用层协同

```
请求到达 APISIX
  ├── IP 黑名单？→ 403
  ├── 速率超限？→ 429（秒级拒绝）
  ├── 后端熔断？→ 502（不转发到故障服务）
  └── 放行 → Agent Service → 输入护栏 → 输出护栏 → 返回
```

## 6.4 Prompt Injection 检测

```python
# 注入检测的启发式规则
INJECTION_PATTERNS = [
    r"(忽略|忘记|无视)(以上|之前|前面)(的)?(所有|全部)?(指令|规则|限制|要求)",
    r"(你|现在)(是|变成|扮演)(一个|新的)",
    r"(system|系统)(指令|提示|prompt)",
    r"ignore (all |the |above |previous )?instructions",
    r"you are now",
    r"new system prompt",
]
```

**为什么不用 LLM 检测：** 成本高（每次输入都要调用一次 LLM）、延迟大（+200ms）、本身也可能被注入。正则 + 关键词匹配虽然粗暴，但低延迟、零成本、无注入风险。

## 6.5 面试口述逻辑（安全 + 网关）

**Q：你们的 Agent 安全防护怎么做的？**

A：四层纵深防御。第一层是 APISIX 网关——IP 黑白名单、速率限制、熔断，在请求到达应用前就拦截恶意流量。第二层是输入护栏——敏感词过滤、注入检测、越狱模式匹配。第三层是输出护栏——PII 检测脱敏、合规检查。第四层是全量审计日志。关键设计是网关和应用层协同：网关处理网络层的攻击（DDoS、暴力），应用层处理语义层的攻击（注入、越狱）。

---

# 第七章：云原生部署与容器化

> 新增章节（v2.1 云原生架构升级）

## 7.1 为什么从单进程走向云原生

### 单进程架构的瓶颈

```
┌──────────────────────────────┐
│      单进程 FastAPI 应用       │
│  ┌──────┐ ┌──────┐ ┌──────┐ │
│  │Agent │ │ RAG  │ │Memory│ │
│  │模块   │ │模块   │ │模块   │ │
│  └──────┘ └──────┘ └──────┘ │
└──────────────────────────────┘

问题：
  1. 单点故障——一个模块 OOM，整个服务挂
  2. 无法独立扩缩——RAG 模块压力大，但必须和 Agent 一起扩
  3. 部署慢——改一行 RAG 代码要重新部署整个应用
  4. 资源争抢——Agent 和 RAG 在同一进程竞争 CPU/内存
```

### 云原生架构全景

```
                          ┌──────────────┐
                          │   APISIX     │  ← API 网关
                          │  (Gateway)   │
                          └──────┬───────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
┌──────────────┐       ┌──────────────┐        ┌──────────────┐
│Agent Service │       │ RAG Service  │        │  WS Service  │
│ (LangGraph)  │       │ (FastAPI)    │        │ (WebSocket)  │
│  副本×3       │       │  副本×2       │        │  副本×2       │
└──────┬───────┘       └──────┬───────┘        └──────────────┘
       │                      │
       │    ┌─────────────────┼─────────────────┐
       │    │                 │                 │
       ▼    ▼                 ▼                 ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│ RabbitMQ │ │  Redis   │ │  MinIO   │ │   Milvus     │
│ (消息队列) │ │ (缓存/锁) │ │ (对象存储) │ │  (向量库)     │
└──────────┘ └──────────┘ └──────────┘ └──────────────┘
       │
       ▼
┌──────────┐
│  Worker  │  ← RAG Worker / Reflect Worker / Notify Worker
│  副本×2   │
└──────────┘
```

## 7.2 Docker Compose：12 服务编排

开发环境和轻量级部署采用 Docker Compose 编排 12 个服务：

```yaml
# docker-compose.yml 核心结构
services:
  # ─── 应用服务 ───
  agent:          # Agent 主服务 (LangGraph 工作流)
  rag:            # RAG 检索服务 (FastAPI)
  ws:             # WebSocket 推送服务
  worker:         # RabbitMQ 异步 Worker

  # ─── 中间件 ───
  rabbitmq:       # 消息队列 (管理端口 15672)
  redis:          # 缓存/分布式锁 (6379)
  postgres:       # 关系数据库 (5432)
  minio:          # 对象存储 (9000 API, 9001 Console)
  milvus:         # 向量数据库 (19530)

  # ─── 基础设施 ───
  apisix:         # API 网关 (9080)
  prometheus:     # 监控采集 (9090)
  grafana:        # 监控可视化 (3000)
```

**12 个服务的网络拓扑：**

```
┌─────────────────────────────────────────────────────┐
│  Docker Network: enterprise-agent (bridge)           │
│                                                      │
│  apisix (9080:9080) ──→ agent (8000)                 │
│                     ──→ rag (8001)                    │
│                     ──→ ws (8002)                     │
│                                                      │
│  agent ──→ rabbitmq (5672)                           │
│  agent ──→ redis (6379)                              │
│  agent ──→ postgres (5432)                           │
│                                                      │
│  rag ──→ milvus (19530)                              │
│  rag ──→ minio (9000)                                │
│                                                      │
│  worker ──→ rabbitmq (5672)                          │
│  worker ──→ rag (8001)                               │
│                                                      │
│  prometheus ──→ agent:9090/metrics                   │
│  prometheus ──→ rag:9090/metrics                     │
│  prometheus ──→ rabbitmq:15692/metrics               │
│                                                      │
│  grafana ──→ prometheus (9090)                       │
└─────────────────────────────────────────────────────┘
```

### 各服务的资源配置

| 服务 | CPU Limit | Memory Limit | 副本数 | 健康检查端点 |
|------|-----------|-------------|--------|------------|
| apisix | 0.5 | 256Mi | 1 | /apisix/status |
| agent | 1.0 | 512Mi | 3 | /health |
| rag | 1.0 | 1Gi | 2 | /health |
| ws | 0.5 | 256Mi | 2 | /health |
| worker | 1.0 | 512Mi | 2 | RabbitMQ heartbeat |
| rabbitmq | 1.0 | 512Mi | 1 | Management API |
| redis | 0.5 | 256Mi | 1 | PING |
| postgres | 0.5 | 512Mi | 1 | pg_isready |
| minio | 0.5 | 256Mi | 1 | /minio/health/live |
| milvus | 2.0 | 4Gi | 1 | /healthz |
| prometheus | 0.5 | 512Mi | 1 | /-/healthy |
| grafana | 0.5 | 256Mi | 1 | /api/health |

## 7.3 多阶段 Docker 构建

### Agent 服务的多阶段 Dockerfile

```dockerfile
# Stage 1: Builder（构建阶段）
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime（运行阶段）
FROM python:3.11-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 tesseract-ocr tesseract-ocr-chi-sim && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --shell /bin/bash appuser
COPY --from=builder /root/.local /home/appuser/.local
COPY src/ /app/src/
COPY config/ /app/config/
WORKDIR /app
USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**多阶段构建的关键收益：**

| 维度 | 单阶段 | 多阶段 |
|------|--------|--------|
| 镜像大小 | ~1.2GB（含编译工具链） | ~400MB（仅运行时依赖） |
| 安全攻击面 | gcc/g++ 可被利用 | 无编译工具 |
| 构建缓存 | 较差 | 依赖层独立缓存 |
| 推送/拉取速度 | 慢 | 快 3x |

### 各服务 Dockerfile 设计对比

| 服务 | 基础镜像 | 特殊依赖 | 镜像大小 |
|------|---------|---------|---------|
| agent | python:3.11-slim | langchain, langgraph | ~380MB |
| rag | python:3.11-slim | pymupdf, paddleocr, tesseract | ~650MB |
| ws | python:3.11-slim | fastapi, websockets | ~250MB |
| worker | python:3.11-slim | pika (RabbitMQ client) | ~300MB |

## 7.4 K3s + Helm 生产部署

### 为什么选 K3s 而不是 K8s

| 维度 | K8s (标准) | K3s |
|------|-----------|-----|
| 二进制大小 | ~1GB | ~50MB |
| 内存占用 | ~1GB | ~256MB |
| 组件数量 | etcd + kube-apiserver + controller + scheduler + kubelet + kube-proxy | 合并为一个 binary |
| 默认存储 | etcd | SQLite（可替换 etcd） |
| 适用场景 | 大规模集群 | 边缘/中小规模/开发环境 |

**选型决策：** 项目当前规模（14,707 行代码，12 个服务）不需要完整的 K8s 集群。K3s 提供了 K8s 的核心能力（声明式部署、自动扩缩、滚动更新）且运维成本低很多。

### Helm Chart 结构

```
helm/enterprise-agent/
├── Chart.yaml              # Chart 元信息 (name, version, appVersion)
├── values.yaml             # 默认配置值
├── values-dev.yaml         # 开发环境覆盖
├── values-prod.yaml        # 生产环境覆盖
├── templates/
│   ├── _helpers.tpl        # 模板函数
│   ├── namespace.yaml      # 命名空间
│   ├── configmap.yaml      # 配置（环境变量）
│   ├── secret.yaml         # 密钥（API Key、数据库密码）
│   ├── deployment-agent.yaml
│   ├── deployment-rag.yaml
│   ├── deployment-ws.yaml
│   ├── deployment-worker.yaml
│   ├── service.yaml        # ClusterIP Services
│   ├── ingress.yaml        # APISIX Ingress
│   ├── pvc.yaml            # 持久化存储声明
│   └── hpa.yaml            # 水平自动扩缩
```

### values.yaml 核心配置

```yaml
# 全局配置
global:
  namespace: enterprise-agent
  imageRegistry: registry.example.com
  imageTag: "v2.1.0"

# Agent 服务
agent:
  replicas: 3
  image: enterprise-agent/agent
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 512Mi
  hpa:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
  env:
    RABBITMQ_HOST: rabbitmq.enterprise-agent.svc.cluster.local
    REDIS_HOST: redis.enterprise-agent.svc.cluster.local
    VECTOR_BACKEND: milvus

# RAG 服务
rag:
  replicas: 2
  image: enterprise-agent/rag
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 2Gi

# APISIX 网关
apisix:
  enabled: true
  replicas: 1
  plugins:
    - limit-req
    - api-breaker
    - prometheus
    - cors
```

### KEDA 自动扩缩（基于 RabbitMQ 队列深度）

除了 HPA（基于 CPU/内存），Worker 服务使用 KEDA 基于队列深度自动扩缩：

```yaml
# KEDA ScaledObject
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: worker-scaler
spec:
  scaleTargetRef:
    name: worker-deployment
  minReplicaCount: 1
  maxReplicaCount: 20
  triggers:
    - type: rabbitmq
      metadata:
        queueName: agent.task.rag
        host: rabbitmq.enterprise-agent.svc.cluster.local
        queueLength: "50"  # 队列超过 50 条触发扩容
```

**为什么 Worker 用 KEDA 而不是 HPA：** HPA 基于 CPU/内存，但 Worker 的 CPU 使用率和队列深度不总是正相关。KEDA 直接基于 RabbitMQ 队列长度决策，更精准。

## 7.5 APISIX 网关配置详解

### 路由规则

```yaml
routes:
  # Agent 对话接口
  - uri: /api/v1/chat
    upstream:
      service_name: agent-service
      type: roundrobin
    plugins:
      limit-req:
        rate: 60
        burst: 10
        key: http_x_user_id

  # RAG 检索接口（内部）
  - uri: /api/v1/search
    upstream:
      service_name: rag-service
    plugins:
      api-breaker:
        break_response_code: 502
        unhealthy:
          failures: 10

  # WebSocket
  - uri: /ws/notifications
    upstream:
      service_name: ws-service
    enable_websocket: true

  # Metrics（内部）
  - uri: /metrics
    upstream:
      service_name: prometheus
```

### 负载均衡策略

| 策略 | 适用场景 | 本项目使用 |
|------|---------|-----------|
| roundrobin | 通用 | Agent Service（无状态） |
| least_conn | 长连接 | WS Service（WebSocket） |
| consistent_hash | 有状态 | 未使用（状态在 Redis） |

## 7.6 云原生部署面试口述逻辑

**Q：你们从单进程到云原生，主要做了什么？**

A：四个层面。第一，服务拆分——Agent、RAG、Worker、WS 拆为 4 个独立微服务，每个有独立的 Dockerfile 和多阶段构建。第二，容器编排——Docker Compose 管理 12 个服务（开发/测试），K3s + Helm 管理生产部署。第三，API 网关——APISIX 统一入口，处理路由、限流、熔断。第四，自动扩缩——HPA 基于 CPU 扩缩 Agent 和 RAG，KEDA 基于 RabbitMQ 队列深度扩缩 Worker。

**Q：多阶段 Docker 构建有什么好处？**

A：三个好处。镜像体积从 ~1.2GB 降到 ~400MB（不含编译工具链），安全攻击面减少（没有 gcc/g++），依赖层独立缓存加快重复构建速度。核心原理是把 gcc/g++ 等编译工具放在 builder 阶段，最终镜像只 COPY 编译产出（pip install --user 的 .local 目录）。

---

# 第八章：分布式中间件

> 新增章节（v2.1 云原生架构升级）

## 8.1 RabbitMQ：异步任务与削峰填谷

### Topic Exchange 设计

```
Exchange: agent.tasks (type=topic, durable=true)

Routing Pattern                    → Queue
──────────────────────────────────────────────────
task.rag.#                         → agent.task.rag
task.reflect.#                     → agent.task.reflect
task.notify.#                      → agent.task.notify
task.*.high                        → agent.task.high_priority
task.*.*                           → agent.task.dlq (after x-dead-letter-exchange)
```

**路由示例：**

| 消息 Routing Key | 目标队列 | 说明 |
|-----------------|---------|------|
| task.rag.search | agent.task.rag | RAG 检索任务 |
| task.rag.high | agent.task.rag + agent.task.high_priority | 高优先级 RAG 任务（两个队列都收到） |
| task.reflect | agent.task.reflect | 反思审查任务 |
| task.notify.email | agent.task.notify | 邮件通知任务 |

### 消息可靠性保障

```
Publisher Confirm（发布确认）
  ├── 生产者发送消息后等待 Broker 确认
  ├── 未确认 → 重试（最多 3 次）
  └── 3 次失败 → 记录到本地 DLQ (SQLite)

Consumer Ack（消费确认）
  ├── 手动确认模式 (auto_ack=False)
  ├── 处理成功 → basic_ack
  ├── 处理失败 → basic_nack (requeue=True) 或 basic_reject
  └── 连续 Nack 3 次 → 路由到 DLQ

Message Persistence（消息持久化）
  ├── delivery_mode=2（持久化到磁盘）
  ├── exchange durable=true
  └── queue durable=true

Dead Letter Queue（死信队列）
  ├── agent.task.dlq：所有重试失败的任务
  ├── 消息保留 7 天
  ├── 提供 HTTP API 查询/重放/丢弃
  └── Prometheus 监控：DLQ 堆积 > 100 → 告警
```

### 连接管理（云原生特别关注）

```python
class RabbitMQClient:
    def __init__(self, url: str):
        self._params = pika.URLParameters(url)
        # 关键：云原生环境需要心跳和重连
        self._params.heartbeat = 30           # 30s 心跳
        self._params.blocked_connection_timeout = 300
        self._connection = None

    async def connect(self):
        while True:
            try:
                self._connection = pika.BlockingConnection(self._params)
                break
            except pika.exceptions.AMQPConnectionError:
                await asyncio.sleep(5)  # 5s 重试

    @property
    def channel(self):
        # 连接断开自动重连
        if not self._connection or self._connection.is_closed:
            self.connect()
        return self._connection.channel()
```

**为什么云原生环境需要特别关注连接管理：**
1. K3s 网络策略可能导致 Pod 间网络短暂中断
2. RabbitMQ Pod 重启时，所有客户端连接断开
3. 心跳机制确保快速检测断连（30s vs 默认 60s）

## 8.2 Redis：分布式锁 + 缓存

### 分布式锁完整实现

```python
class RedisDistributedLock:
    """基于 Redis Lua 脚本的分布式锁"""

    LOCK_SCRIPT = """
    if redis.call("SET", KEYS[1], ARGV[1], "NX", "EX", ARGV[2]) then
        return 1
    else
        return 0
    end
    """

    UNLOCK_SCRIPT = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("DEL", KEYS[1])
    else
        return 0
    end
    """

    def __init__(self, redis_client, key: str, ttl: int = 30):
        self.redis = redis_client
        self.key = f"lock:{key}"
        self.ttl = ttl
        self.value = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"

    async def __aenter__(self):
        while True:
            result = await self.redis.eval(
                self.LOCK_SCRIPT, 1, self.key, self.value, self.ttl
            )
            if result == 1:
                return self
            await asyncio.sleep(0.1)

    async def __aexit__(self, *args):
        await self.redis.eval(
            self.UNLOCK_SCRIPT, 1, self.key, self.value
        )
```

**关键设计决策：**

1. **为什么锁值包含 hostname + PID + UUID：** 防止误解锁。如果 A 实例的锁过期被 B 获取，A 不能用自己持有的旧 value 去删 B 的锁。解锁时检查 value 匹配（GET + DEL 的原子性由 Lua 保证）。

2. **为什么用 spin-wait 而不是阻塞：** 分布式锁的持有时间通常很短（毫秒级），spin-wait 避免了操作系统层面的上下文切换开销。

3. **TTL 设计：** 操作预期耗时的 2-3 倍。太短→锁提前释放→并发冲突；太长→死锁时间长。

### 缓存策略

| 缓存类型 | Key Pattern | TTL | 淘汰策略 |
|---------|-------------|-----|---------|
| FAQ 答案缓存 | faq:{question_hash} | 1h | LRU |
| 用户权限缓存 | user:perm:{user_id} | 5min | 主动失效 |
| RAG 热门查询缓存 | rag:hot:{query_hash} | 30min | TTL + LRU |
| Session 状态 | session:{session_id} | 24h | TTL |
| 限流计数器 | ratelimit:{user_id}:{minute} | 60s | TTL |

**缓存一致性策略：** 采用 Cache-Aside 模式——读缓存未命中时查数据库并回填，写操作先更新数据库再删除缓存（避免双写不一致）。

### 缓存穿透/击穿/雪崩防护

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 缓存穿透 | 查一个不存在的数据，每次都穿透到 DB | 布隆过滤器 + 空值缓存（TTL 30s） |
| 缓存击穿 | 热点 key 过期瞬间大量请求打 DB | 互斥锁（Redis 分布式锁）只让一个请求去查 DB |
| 缓存雪崩 | 大量 key 同时过期 | 基础 TTL + 随机偏移（±20%） |

## 8.3 MinIO：对象存储

### 为什么用 MinIO 而不是直接挂载 Volume

| 维度 | HostPath / NFS | MinIO |
|------|---------------|-------|
| 多 Pod 共享 | 需要 NFS，配置复杂 | S3 API 原生支持 |
| 高可用 | 单点故障 | 分布式纠删码 |
| 访问控制 | 文件系统权限 | IAM Policy（S3 标准） |
| 生命周期管理 | 手动 | Bucket Lifecycle Rule |
| 客户端库 | 文件路径 | 标准 S3 SDK（boto3） |
| 扩展性 | 垂直扩展 | 水平扩展 |

### 存储桶设计

```
minio/
├── documents/          # 原始文档（产品手册、FAQ 等）
│   Policy: 只读（Agent/RAG 读取）
│   Lifecycle: 180 天后归档
│
├── images/             # 图片文件
│   Policy: 读写（Loader 写入）
│   Lifecycle: 90 天后删除（处理后不需要保留原图）
│
├── models/             # 模型文件（OCR 模型等）
│   Policy: 只读（服务启动时加载）
│   Lifecycle: 无（永久保留）
│
└── exports/            # 数据导出（评估报告等）
    Policy: 读写（定时任务生成）
    Lifecycle: 30 天后删除
```

### Python 客户端封装

```python
class MinIOClient:
    def __init__(self, endpoint: str, access_key: str, secret_key: str):
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=False  # 内网 HTTP
        )

    async def upload_document(self, bucket: str, file_path: Path, content_type: str):
        """上传文档，自动检测 content-type"""
        result = self.client.fput_object(
            bucket_name=bucket,
            object_name=file_path.name,
            file_path=str(file_path),
            content_type=content_type
        )
        return result.object_name

    async def get_presigned_url(self, bucket: str, object_name: str, expires: int = 3600):
        """生成预签名 URL（临时访问链接）"""
        return self.client.presigned_get_object(bucket, object_name, timedelta(seconds=expires))
```

**MinIO 在 RAG 流程中的角色：**

```
文档上传 → MinIO documents/ bucket
         → FileSyncManager 检测新文件
         → 从 MinIO 下载 → Loader → Chunker → Embedder → Milvus
         → 完成后标记已处理（不删除 MinIO 中的原文件）
```

## 8.4 分布式中间件面试口述逻辑

**Q：RabbitMQ 的消息可靠性怎么保证？**

A：四层保障。第一，发布确认（Publisher Confirm）——生产者发消息后等待 Broker 确认，失败自动重试。第二，消费确认（Consumer Ack）——手动 ack 模式，处理完才确认，失败 nack 回队列。第三，消息持久化——exchange/queue/message 都标记 durable + persistent，RabbitMQ 重启不丢。第四，死信队列——重试 3 次失败进入 DLQ，7 天保留期，提供 API 手动重放。

**Q：Redis 分布式锁为什么要用 Lua 脚本？**

A：因为 SETNX + EXPIRE 是两个命令，非原子。如果进程在 SETNX 成功后、EXPIRE 之前崩溃，锁永远不会释放——死锁。Lua 脚本在 Redis 服务端原子执行，"SET NX EX" 是一个不可分割的操作。解锁也一样，GET + DEL 必须原子——不能删掉别人的锁。

---

# 第九章：CI/CD 与 GitOps

> 新增章节（v2.1 云原生架构升级）

## 9.1 GitLab CI 六阶段流水线

### 完整 Pipeline 设计

```yaml
# .gitlab-ci.yml
stages:
  - lint        # 代码规范检查
  - test        # 单元测试 + 集成测试
  - sast        # 静态安全分析
  - build       # Docker 镜像构建
  - deploy      # 部署到 K3s
  - verify      # 部署后验证（冒烟测试）
```

### Stage 1: Lint

```yaml
lint:
  stage: lint
  image: python:3.11-slim
  script:
    - pip install ruff mypy
    - ruff check src/ tests/           # 代码风格 + 逻辑错误
    - mypy src/ --ignore-missing-imports # 类型检查
  allow_failure: false   # lint 失败必须修复
```

**为什么 ruff 而不是 flake8：** ruff 用 Rust 实现，比 flake8 快 10-100 倍，规则集更全（兼容 flake8 + isort + pyupgrade）。

### Stage 2: Test

```yaml
test:
  stage: test
  image: python:3.11-slim
  services:
    - redis:7-alpine
    - postgres:15-alpine
    - rabbitmq:3-management-alpine
  variables:
    REDIS_HOST: redis
    PG_HOST: postgres
    RABBITMQ_HOST: rabbitmq
    VECTOR_BACKEND: chroma   # CI 环境用 Chroma 避免启动 Milvus
  script:
    - pip install -e ".[test]"
    - pytest tests/ -v --cov=src --cov-report=xml --cov-report=term
    - coverage report --fail-under=80
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

**48 个测试用例的分布：**

| 测试模块 | 用例数 | 类型 | 覆盖范围 |
|---------|--------|------|---------|
| test_rag_loaders | 12 | 单元测试 | 5 种加载器的输入输出验证 |
| test_rag_processors | 10 | 单元测试 | 7 种处理器的处理逻辑 |
| test_rag_retriever | 8 | 集成测试 | 检索 + 融合 + 过滤 |
| test_rag_sync | 5 | 集成测试 | 增量同步逻辑 |
| test_agent_graph | 6 | 单元测试 | LangGraph 状态转换 |
| test_memory | 4 | 单元测试 | 记忆 CRUD + 去重 |
| test_security | 3 | 单元测试 | PII 检测、注入检测 |

### Stage 3: SAST (Static Application Security Testing)

```yaml
sast:
  stage: sast
  image: registry.gitlab.com/security-products/semgrep:latest
  script:
    - semgrep --config=auto --error src/
  allow_failure: true    # SAST 告警不阻断 pipeline（需人工 review）
  artifacts:
    reports:
      sast: gl-sast-report.json
```

**Semgrep 规则覆盖：**
- Python 注入风险（SQL 拼接、命令注入）
- 硬编码密钥检测
- 不安全的反序列化
- 危险函数使用（eval, exec, pickle）

### Stage 4: Build

```yaml
build:
  stage: build
  image: docker:24-dind
  services:
    - docker:24-dind
  parallel:
    matrix:
      - SERVICE: [agent, rag, ws, worker]
  script:
    - docker build -t $CI_REGISTRY_IMAGE/$SERVICE:$CI_COMMIT_SHORT_SHA
                   -f docker/$SERVICE.Dockerfile .
    - docker push $CI_REGISTRY_IMAGE/$SERVICE:$CI_COMMIT_SHORT_SHA
    - docker tag $CI_REGISTRY_IMAGE/$SERVICE:$CI_COMMIT_SHORT_SHA
                 $CI_REGISTRY_IMAGE/$SERVICE:latest
    - docker push $CI_REGISTRY_IMAGE/$SERVICE:latest
```

**并行构建矩阵：** 4 个服务镜像同时构建，减少整体 pipeline 时间。

**镜像标签策略：**
- `$CI_COMMIT_SHORT_SHA` — 不可变标签，用于回滚
- `latest` — 可移动标签，开发环境自动更新
- Git Tag `v2.1.0` — 生产版本标签，由 Release 流程创建

### Stage 5: Deploy (GitOps with ArgoCD)

```yaml
deploy-dev:
  stage: deploy
  image: alpine:3.19
  script:
    - apk add --no-cache git
    # 更新 Helm values 中的镜像 tag
    - cd helm/enterprise-agent
    - yq -i ".agent.image.tag = \"$CI_COMMIT_SHORT_SHA\"" values-dev.yaml
    - yq -i ".rag.image.tag = \"$CI_COMMIT_SHORT_SHA\"" values-dev.yaml
    - yq -i ".ws.image.tag = \"$CI_COMMIT_SHORT_SHA\"" values-dev.yaml
    - yq -i ".worker.image.tag = \"$CI_COMMIT_SHORT_SHA\"" values-dev.yaml
    # 推送到 GitOps 配置仓库
    - git add values-dev.yaml
    - git commit -m "auto: update dev images to $CI_COMMIT_SHORT_SHA"
    - git push
  environment:
    name: development
```

### Stage 6: Verify (Smoke Test)

```yaml
verify:
  stage: verify
  image: alpine:3.19
  script:
    - apk add --no-cache curl
    # 等待部署完成
    - sleep 30
    # 冒烟测试：发送测试问题
    - curl -f -X POST https://dev-api.example.com/api/v1/chat
           -H "Content-Type: application/json"
           -H "X-User-Id: ci-smoke-test"
           -d '{"query": "你好"}'
    # 检查健康端点
    - curl -f https://dev-api.example.com/health
    - curl -f https://dev-api.example.com/rag/health
  allow_failure: true  # 冒烟测试失败不阻断（可能是网络问题）
```

## 9.2 ArgoCD GitOps

### GitOps 核心原理

```
┌─────────────┐     Push Image    ┌──────────────┐
│  GitLab CI  │ ────────────────→  │ GitLab        │
│  (Pipeline) │                   │ Container     │
└─────────────┘                   │ Registry      │
                                  └──────────────┘
                                         │
┌─────────────┐     Git Commit    ┌──────▼───────┐
│  GitOps Repo│ ←──────────────── │  GitLab CI   │
│  (Helm      │    更新 image tag  │  (Deploy     │
│   Charts)   │                   │   Stage)     │
└──────┬──────┘                   └──────────────┘
       │
       │ Poll (3s interval)
       ▼
┌─────────────┐     Apply         ┌──────────────┐
│   ArgoCD    │ ────────────────→ │  K3s Cluster │
│  (GitOps    │                   │  (Target)    │
│   Engine)   │                   └──────────────┘
└─────────────┘
```

**为什么用 GitOps 而不是 CI/CD 直接 kubectl apply：**
1. **审计：** Git 是单一真实来源（Single Source of Truth），谁改了什么都记录在 commit log
2. **回滚：** `git revert` = 回滚部署，不需要记 kubectl 命令
3. **自动修复：** ArgoCD 每 3 秒对比 Git 状态和集群状态，任何手动修改都会被自动修复（self-healing）
4. **权限控制：** 开发者不需要 K3s 集群的直接访问权限，只需 Git 写权限

### ArgoCD Application 配置

```yaml
# argocd/enterprise-agent.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: enterprise-agent
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://gitlab.com/enterprise/enterprise-agent-gitops.git
    targetRevision: main
    path: helm/enterprise-agent
    helm:
      valueFiles:
        - values.yaml
        - values-prod.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: enterprise-agent
  syncPolicy:
    automated:
      prune: true          # 自动删除 Git 中移除的资源
      selfHeal: true       # 自动修复手动修改
    syncOptions:
      - CreateNamespace=true
      - PruneLast=true     # 先创建新资源再删除旧资源
```

### Sync 状态机

```
OutOfSync ──→ Syncing ──→ Synced
    ↑                       │
    └───────────────────────┘
         (manual change / drift detected)
```

**Self-Healing 示例：**
1. 运维手动 `kubectl scale deployment agent --replicas=1`（把 3 副本改成了 1）
2. ArgoCD 每 3 秒对比 Git → 发现差异 → 自动 `kubectl scale deployment agent --replicas=3`
3. 集群状态恢复到 Git 定义的期望状态

## 9.3 CI/CD 面试口述逻辑

**Q：你们的 CI/CD 流水线怎么设计的？**

A：GitLab CI 六阶段流水线：lint（rule + mypy）→ test（48 个用例，覆盖率 > 80%）→ SAST（Semgrep 安全扫描）→ build（4 个服务并行构建多阶段 Docker 镜像）→ deploy（更新 GitOps 仓库的 Helm values，ArgoCD 自动同步到 K3s）→ verify（冒烟测试）。核心设计是"Git 是单一真实来源"——CI 只负责构建和推送镜像，不直接操作 K3s 集群。ArgoCD 监控 GitOps 仓库变化并自动同步。

**Q：为什么用 ArgoCD 而不是 CI/CD 直接部署？**

A：三个原因。审计——Git commit log 记录了每一次部署的 who/what/when。自动修复——ArgoCD 每 3 秒检测 drift，手动对集群的修改会被自动回滚到 Git 定义的状态。权限安全——开发者不需要 K3s 集群的 kubectl 权限，只需 Git 仓库的写权限。

---

# 第十章：微服务拆分设计

> 新增章节（v2.1 云原生架构升级）

## 10.1 拆分原则

本项目采用**领域驱动拆分**，按业务能力边界划分为 4 个核心服务：

### 服务边界定义

| 服务 | 职责 | 一句话描述 | 端口 |
|------|------|-----------|------|
| Agent Service | 对话编排 + LangGraph 工作流 | "大脑"——理解意图、编排流程 | 8000 |
| RAG Service | 文档检索 + 向量索引管理 | "记忆"——找到最相关的文档 | 8001 |
| WS Service | WebSocket 实时推送 | "嘴巴"——把结果推送给前端 | 8002 |
| Worker Service | 异步任务消费 | "手"——后台干重活 | N/A |

### 拆分决策矩阵

在拆分时，我们对每个模块做了"应该独立吗"的决策：

| 模块 | 决策 | 理由 |
|------|------|------|
| RAG 检索 | 独立为 RAG Service | 计算密集（向量检索）、内存需求大（索引常驻）、可独立扩容 |
| LangGraph 工作流 | 保留在 Agent Service | 与意图识别强耦合，拆分徒增延迟 |
| FAQ 匹配 | 保留在 Agent Service | 只是 dict 查找，无独立价值 |
| RabbitMQ Worker | 独立为 Worker Service | 完全不同的计算特征（批处理 vs 在线服务） |
| 记忆管理 | 保留在 Agent Service | 与对话流程强耦合 |
| 安全护栏 | 保留在 Agent Service | 输入输出都在 Agent 路径上，独立无意义 |

**拆分原则：**
1. **高内聚低耦合：** 频繁调用的两个模块不应该拆分（会变成分布式单体）
2. **独立变更频率：** 经常独立变更的模块应该拆分（RAG 加载器更新 vs Agent 逻辑更新）
3. **资源需求差异：** CPU 密集和 IO 密集的模块应该拆分（可以独立配置资源）
4. **独立扩缩：** 需要不同扩缩策略的模块应该拆分（RAG 按 QPS 扩、Worker 按队列深度扩）

## 10.2 服务间通信

### 通信方式选择

| 通信场景 | 方式 | 协议 | 为什么 |
|---------|------|------|--------|
| Agent → RAG（检索） | HTTP REST | JSON/HTTP | 请求-响应模式，需要同步返回结果 |
| Agent → Worker（任务提交） | RabbitMQ | AMQP | 异步解耦，不需要立即返回 |
| Worker → RAG（批量摄入） | HTTP REST | JSON/HTTP | 同检索 |
| Agent → WS Service（推送） | Redis Pub/Sub | Redis Protocol | 轻量级，无需持久化 |
| 所有服务 → Redis（缓存/锁） | TCP | Redis Protocol | 标准 Redis 通信 |
| 所有服务 → Prometheus（指标） | HTTP Pull | Prometheus text | Prometheus 主动拉取 |

### 通信协议对比

| 协议 | 延迟 | 可靠性 | 适用场景 | 本项目使用 |
|------|------|--------|---------|-----------|
| HTTP/REST | ms 级 | 无保证 | 同步请求-响应 | Agent ↔ RAG |
| AMQP (RabbitMQ) | ms 级 | At-least-once | 异步任务 | Agent → Worker |
| gRPC | μs 级 | 无保证 | 高性能内部调用 | 预留（Milvus 已用） |
| Redis Pub/Sub | ms 级 | 无保证 | 轻量级广播 | Agent → WS |

### 服务发现

在 K3s 环境中，服务发现由 CoreDNS + Kubernetes Service 自动处理：

```yaml
# 不需要硬编码 IP，直接用 Service 名称
RAG_SERVICE_URL = "http://rag-service.enterprise-agent.svc.cluster.local:8001"
REDIS_HOST = "redis-service.enterprise-agent.svc.cluster.local"
RABBITMQ_HOST = "rabbitmq-service.enterprise-agent.svc.cluster.local"
```

**跨环境服务发现策略：**

| 环境 | 发现方式 | Service URL 示例 |
|------|---------|-----------------|
| 本地开发 | localhost | http://localhost:8001 |
| Docker Compose | Docker DNS | http://rag:8001 |
| K3s | CoreDNS | http://rag-service.enterprise-agent.svc.cluster.local:8001 |

## 10.3 共享库设计

### 避免分布式单体的关键——共享什么，不共享什么

```
共享（作为内部 pip package enterprise-agent-common）：
  ✅ types.py        — 共享数据模型（AgentState, Document, FileInfo）
  ✅ exceptions.py   — 统一异常定义
  ✅ logging.py      — 统一日志格式（structlog JSON）
  ✅ metrics.py      — Prometheus 指标注册
  ✅ config.py       — 配置加载（pydantic-settings）

不共享（每个服务独立维护）：
  ❌ 数据库模型      — 每服务独立 schema
  ❌ 业务逻辑        — 每服务独立实现
  ❌ API 路由        — 每服务独立 FastAPI app
```

### 共享库的版本管理

```toml
# enterprise-agent-common/pyproject.toml
[project]
name = "enterprise-agent-common"
version = "2.1.0"

# agent-service/requirements.txt
enterprise-agent-common==2.1.0  # 锁定版本，避免 breaking change

# rag-service/requirements.txt
enterprise-agent-common==2.1.0
```

**版本管理原则：**
- `enterprise-agent-common` 严格遵循语义化版本（SemVer）
- 新增类型定义 → MINOR bump（2.1.0 → 2.2.0）
- 修改现有类型 → MAJOR bump（同时更新所有消费者）
- CI 中检查所有服务是否使用同一版本的 common library

## 10.4 数据所有权

每个微服务拥有自己的数据，不允许跨服务直接访问数据库：

| 服务 | 拥有数据 | 存储 | 其他服务如何访问 |
|------|---------|------|----------------|
| Agent Service | 对话历史、Session | PostgreSQL (agent_db) | 通过 Agent API |
| RAG Service | 文档索引、同步状态 | Milvus + MinIO + SQLite | 通过 RAG API |
| Worker Service | 任务状态、DLQ | SQLite (本地) | 通过 RabbitMQ 管理 API |
| 全部共享 | 用户权限、配置 | PostgreSQL (shared_db) | 通过 Redis 缓存层 |

**为什么不允许跨服务直连数据库：**
1. Schema 耦合——A 服务的数据库改表结构，B 服务也挂了
2. 无法独立扩容——共享数据库是最难扩展的架构
3. 故障传播——B 服务的慢查询拖垮 A 服务的数据库

## 10.5 微服务拆分面试口述逻辑

**Q：你们的服务拆分是怎么决策的？**

A：四个判断标准。第一，高内聚低耦合——频繁相互调用的模块不拆分。第二，独立变更频率——RAG 加载器经常更新，Agent 工作流相对稳定，拆开后互不影响。第三，资源需求差异——RAG 是计算+内存密集型，Worker 是批处理型，拆开可以独立配置资源（RAG 2Gi 内存，Worker 512Mi 足够）。第四，独立扩缩策略——Agent 按 CPU 用 HPA 扩，Worker 按队列深度用 KEDA 扩，拆开才能用不同的扩缩策略。

**Q：共享库设计有什么要注意的？**

A：只共享类型定义、异常、配置、日志格式这些"契约"层的东西。不共享业务逻辑和数据模型。关键是版本管理——common library 严格语义化版本，CI 检查所有服务是否使用同一版本。如果 common 改了现有类型定义，必须 MAJOR bump 并同步更新所有消费者。

---

# 第十一章：可观测性体系

> 新增章节（v2.1 云原生架构升级）

## 11.1 三大支柱

```
┌─────────────────────────────────────────────────────┐
│                    可观测性三支柱                       │
│                                                      │
│  Metrics（指标）     Logs（日志）      Traces（链路）    │
│  ─────────────     ──────────       ─────────────    │
│  Prometheus         structlog         OpenTelemetry   │
│  + Grafana          + Loki            + Jaeger        │
│                                                      │
│  "系统是否正常？"     "哪里出了问题？"    "请求经过了哪些     │
│   聚合数值           事件明细            服务？耗时分布？"   │
└─────────────────────────────────────────────────────┘
```

## 11.2 Prometheus 指标体系

### 指标类型选择指南

| 指标类型 | 何时使用 | 示例 |
|---------|---------|------|
| Counter | 只增不减的计数 | 请求总数、错误总数、Token 消耗 |
| Gauge | 可增可减的瞬时值 | 活跃连接数、队列深度、内存使用 |
| Histogram | 分布统计（p50/p95/p99） | 响应延迟、检索耗时 |
| Summary | 客户端分位数（不推荐） | （使用 Histogram 替代，服务端计算分位数） |

### 四层黄金信号（RED + USE 方法）

**RED 方法（面向服务）：**
- **R**ate（请求速率）
- **E**rrors（错误率）
- **D**uration（延迟）

**USE 方法（面向资源）：**
- **U**tilization（利用率）
- **S**aturation（饱和度）
- **E**rrors（错误）

### 本项目全部 Prometheus 指标

#### Agent Service 指标

```python
# === RED: Rate ===
agent_requests_total{service="agent", endpoint, status}
# 描述：请求总数，按端点和状态码分类

# === RED: Errors ===
agent_errors_total{service="agent", error_type}
# 描述：错误总数，按类型分类 (timeout, llm_error, rag_error)

# === RED: Duration ===
agent_request_duration_seconds{service="agent", endpoint}
# 描述：请求延迟直方图，buckets=[0.1, 0.5, 1, 2, 5, 10, 30]

# === 业务指标 ===
agent_conversations_active{service="agent"}
# 类型：Gauge，当前活跃对话数

agent_tool_calls_total{service="agent", tool_name, status}
# 类型：Counter，工具调用次数

agent_llm_tokens_total{service="agent", model, type}
# 类型：Counter，LLM Token 消耗 (type=input|output)

agent_escalation_total{service="agent", reason}
# 类型：Counter，转人工次数
```

#### RAG Service 指标

```python
# === RED: Rate ===
rag_search_requests_total{service="rag", status}
# 描述：检索请求总数

# === RED: Duration ===
rag_search_duration_seconds{service="rag"}
# 描述：检索延迟直方图
# 细分标签：retrieval_type=vector|bm25|hybrid

# === 业务指标 ===
rag_documents_indexed_total{service="rag", format, status}
# 描述：已索引文档数

rag_vector_count{service="rag", collection}
# 类型：Gauge，向量库中的向量数量

rag_index_size_bytes{service="rag", collection}
# 类型：Gauge，索引占用磁盘大小
```

#### RabbitMQ 指标

```python
rabbitmq_queue_messages{queue, state}
# state=ready|unacked，队列中消息数量

rabbitmq_queue_messages_published_rate{queue}
# 消息入队速率

rabbitmq_queue_messages_delivered_rate{queue}
# 消费速率

rabbitmq_dlq_messages_total
# Counter，进入 DLQ 的消息总数
```

#### 基础设施指标

```python
# Node Exporter（K3s 节点）
node_cpu_utilization
node_memory_utilization
node_disk_utilization

# cAdvisor（容器级别）
container_cpu_usage_seconds_total
container_memory_working_set_bytes
container_network_receive_bytes_total
```

### 指标命名规范

```
{namespace}_{subsystem}_{name}_{unit}

示例：
  agent_request_duration_seconds   — agent 系统的请求延迟（秒）
  rag_documents_indexed_total      — rag 系统已索引文档总数
  rabbitmq_queue_messages          — rabbitmq 队列消息数量
```

## 11.3 Grafana Dashboard 设计（12 个面板）

### Dashboard Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Row 1: 服务概览 (Service Overview)                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ P1: QPS  │ │P2: Error │ │P3: P95   │ │P4: Active     │  │
│  │ (Graph)  │ │ Rate     │ │ Latency  │ │ Conversations │  │
│  │          │ │ (Graph)  │ │ (Graph)  │ │ (Stat)        │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Row 2: RAG 检索性能 (RAG Performance)                       │
│  ┌────────────────────┐ ┌────────────────────┐              │
│  │ P5: Retrieval      │ │ P6: Vector Count   │              │
│  │ Duration Heatmap   │ │ Trend (Graph)      │              │
│  └────────────────────┘ └────────────────────┘              │
├─────────────────────────────────────────────────────────────┤
│  Row 3: 消息队列 (Message Queue)                             │
│  ┌────────────────────┐ ┌────────────────────┐              │
│  │ P7: Queue Depth    │ │ P8: DLQ Messages   │              │
│  │ (Graph)            │ │ (Stat + Graph)     │              │
│  └────────────────────┘ └────────────────────┘              │
├─────────────────────────────────────────────────────────────┤
│  Row 4: 业务指标 (Business Metrics)                           │
│  ┌────────────────────┐ ┌────────────────────┐              │
│  │ P9: Tool Call      │ │ P10: LLM Token     │              │
│  │ Distribution (Pie) │ │ Usage (Graph)      │              │
│  └────────────────────┘ └────────────────────┘              │
├─────────────────────────────────────────────────────────────┤
│  Row 5: 基础设施 (Infrastructure)                            │
│  ┌────────────────────┐ ┌────────────────────┐              │
│  │ P11: Pod CPU/Mem   │ │ P12: Escalation    │              │
│  │ (Graph)            │ │ Rate (Graph)       │              │
│  └────────────────────┘ └────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

### 每个面板的 PromQL

| 面板 | PromQL 查询 |
|------|-----------|
| P1: QPS | `rate(agent_requests_total[1m])` |
| P2: Error Rate | `rate(agent_requests_total{status=~"5.."}[5m]) / rate(agent_requests_total[5m])` |
| P3: P95 Latency | `histogram_quantile(0.95, rate(agent_request_duration_seconds_bucket[5m]))` |
| P4: Active Conversations | `agent_conversations_active` |
| P5: RAG Heatmap | `rate(rag_search_duration_seconds_bucket[5m])` (Heatmap 类型) |
| P6: Vector Count | `rag_vector_count` |
| P7: Queue Depth | `rabbitmq_queue_messages{queue="agent.task.rag", state="ready"}` |
| P8: DLQ Count | `rabbitmq_dlq_messages_total` |
| P9: Tool Calls | `rate(agent_tool_calls_total[5m])` (Pie chart by tool_name) |
| P10: Token Usage | `rate(agent_llm_tokens_total[5m])` |
| P11: CPU/Mem | `container_cpu_usage_seconds_total` / `container_memory_working_set_bytes` |
| P12: Escalation Rate | `rate(agent_escalation_total[10m])` |

## 11.4 告警规则详解（8 条）

### 告警严重级别定义

| 级别 | 含义 | 通知方式 | 响应时间 |
|------|------|---------|---------|
| critical | 服务不可用或即将不可用 | PagerDuty + 企业微信 | 5 分钟 |
| warning | 需要关注但服务仍可用 | 企业微信 | 30 分钟 |
| info | 信息通知，无需立即响应 | 仅 Grafana 面板 | 无需响应 |

### 完整告警规则

```yaml
groups:
  - name: enterprise-agent-alerts
    rules:
      # 1. 幻觉率过高 (warning)
      - alert: HighHallucinationRate
        expr: |
          rate(agent_evaluation_total{status="hallucination"}[15m])
          / rate(agent_evaluation_total[15m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Agent 幻觉率超过 5%"
          description: "过去 15 分钟内幻觉率 {{ $value | humanizePercentage }}"

      # 2. 响应延迟恶化 (warning)
      - alert: HighResponseLatency
        expr: |
          histogram_quantile(0.95,
            rate(agent_request_duration_seconds_bucket[5m])) > 20
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent P95 响应延迟超过 20s"
          description: "当前 P95 延迟 {{ $value }}s"

      # 3. 转人工率异常 (critical)
      - alert: HighEscalationRate
        expr: |
          rate(agent_escalation_total[10m])
          / rate(agent_requests_total[10m]) > 0.3
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "转人工率超过 30%，可能 Agent 大面积失效"
          description: "当前转人工率 {{ $value | humanizePercentage }}"

      # 4. MQ 队列堆积 (critical)
      - alert: QueueBacklog
        expr: rabbitmq_queue_messages{queue="agent.task.rag"} > 500
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "RAG 任务队列积压超过 500 条"
          description: "队列 {{ $labels.queue }} 积压 {{ $value }} 条"

      # 5. RAG 检索超时 (warning)
      - alert: RAGRetrievalSlow
        expr: |
          histogram_quantile(0.99,
            rate(rag_search_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "RAG P99 检索延迟超过 5s"

      # 6. 服务错误率 (critical)
      - alert: HighErrorRate
        expr: |
          rate(agent_requests_total{status=~"5.."}[5m])
          / rate(agent_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Agent 服务 5xx 错误率超过 5%"

      # 7. DLQ 堆积 (warning)
      - alert: DLQBacklog
        expr: rabbitmq_dlq_messages_total > 100
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "死信队列积压超过 100 条"
          description: "DLQ 积压 {{ $value }} 条，需要人工排查"

      # 8. Token 消耗异常 (warning)
      - alert: TokenUsageSpike
        expr: rate(agent_llm_tokens_total[15m]) > 100000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "LLM Token 消耗异常飙升"
          description: "15 分钟内消耗 {{ $value }} tokens/min"
```

### 告警设计原则

1. **消除误报：** 每个告警都有 `for` 持续时间（5-15 分钟），避免瞬时波动触发
2. **可操作：** 每条告警的 description 都包含当前值和排查方向
3. **分级别：** critical 需要立即响应，warning 可以工作时间处理，info 仅记录
4. **有文档：** 每条告警对应一个 Runbook 文档（怎么写排查步骤）

## 11.5 结构化日志

```python
# structlog 配置
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()  # JSON 格式，Loki 友好
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()

# 使用示例
log.info(
    "agent.request.completed",
    request_id=request_id,
    user_id=user_id,
    intent=intent,
    duration_ms=duration_ms,
    tokens_used=tokens_used,
)
```

**为什么用 structlog + JSON：**
- JSON 格式直接被 Loki 索引，不需要正则解析
- 结构化字段（request_id, user_id）天然支持按字段聚合查询
- 跨服务通过 trace_id 关联日志（distributed tracing 的基础）

## 11.6 可观测性面试口述逻辑

**Q：你们的可观测性体系怎么建的？**

A：三大支柱——Metrics（Prometheus + Grafana）、Logs（structlog JSON → Loki）、Traces（OpenTelemetry → Jaeger，预留）。核心是 12 个 Grafana 面板覆盖服务概览、RAG 性能、消息队列、业务指标、基础设施五个维度。8 条告警规则覆盖幻觉率、延迟、错误率、队列堆积等关键信号，分 critical/warning/info 三级。特别注意消除误报——每个告警都有持续时间缓冲（5-15 分钟），每条告警对应一个 runbook。

**Q：Prometheus Histogram 和 Summary 有什么区别，为什么选 Histogram？**

A：Histogram 在服务端计算分位数（Prometheus 用 histogram_quantile），Summary 在客户端计算。Histogram 的优势是可以在查询时任意指定分位数（p50/p95/p99/p999），Summary 的分位数在采集时就固化了。唯一的劣势是 Histogram 的 bucket 需要提前定义，bucket 设计不好会影响精度。我们的 buckets 是 [0.1, 0.5, 1, 2, 5, 10, 30]，覆盖了从亚秒级到超时的大部分场景。

---

# 第十二章：向量库迁移 — Chroma 到 Milvus

> 新增章节（v2.1 云原生架构升级）

## 12.1 为什么迁移

### Chroma 的局限

Chroma 是一个优秀的嵌入式向量库，但在生产环境中暴露了以下局限：

| 维度 | Chroma | 生产环境问题 |
|------|--------|------------|
| 架构 | 单进程嵌入式 | 无法多副本共享索引 |
| 扩展性 | 垂直扩展（加内存） | 数据量 > 100 万向量时性能急剧下降 |
| 一致性 | 最终一致性（SQLite） | 写入后立即可读性不保证 |
| 多租户 | 手动 collection 前缀 | 无原生多租户隔离机制 |
| 高可用 | 无（单点故障） | 挂了就是挂了 |
| 监控 | 无原生 metrics | 无法接入 Prometheus |
| 索引算法 | 仅 HNSW | 无 IVF/量化索引等选项 |

### Milvus 的优势

| 维度 | Milvus | 对项目的价值 |
|------|--------|------------|
| 分布式架构 | 计算存储分离（Proxy/QueryNode/DataNode/IndexNode） | 各组件独立扩缩 |
| 多租户 | Partition Key 原生支持 | 一条数据一个 tenant_id 字段，自动隔离 |
| 索引多样性 | IVF_FLAT / IVF_PQ / IVF_SQ8 / HNSW / DISKANN | 根据数据量选择最优索引 |
| 一致性 | Strong / Bounded / Eventually 可配置 | 写入后立即可读（Strong 模式） |
| 监控 | 内置 Prometheus metrics | 直接接入现有 Grafana |
| 混合搜索 | 向量 + 标量过滤（标量索引） | 权限过滤在数据库层完成 |
| 数据量 | 百亿级向量 | 无需担心数据增长 |

## 12.2 架构对比

### Chroma 嵌入式架构

```
┌─────────────────────────┐
│      RAG Service         │
│  ┌─────────────────────┐ │
│  │   Chroma (进程内)     │ │
│  │   - SQLite 持久化     │ │
│  │   - HNSW 索引（内存）  │ │
│  └─────────────────────┘ │
└─────────────────────────┘
问题：多副本 → 多份独立索引 → 数据不一致
```

### Milvus 分布式架构

```
┌──────────────┐  ┌──────────────┐
│ RAG Service  │  │ RAG Service  │
│  (副本 1)     │  │  (副本 2)     │
│  MilvusClient│  │  MilvusClient│
└──────┬───────┘  └──────┬───────┘
       │                 │
       └────────┬────────┘
                │ gRPC
                ▼
┌───────────────────────────────────┐
│           Milvus 集群              │
│  ┌─────────┐  ┌─────────────────┐ │
│  │  Proxy  │  │  Query Node ×2  │ │
│  │ (路由)   │  │  (向量检索)      │ │
│  └─────────┘  └─────────────────┘ │
│  ┌─────────┐  ┌─────────────────┐ │
│  │Data Node│  │  Index Node ×2  │ │
│  │ (写入)   │  │  (索引构建)      │ │
│  └─────────┘  └─────────────────┘ │
│                                    │
│  共享存储：MinIO (S3) + etcd       │
└───────────────────────────────────┘
```

**关键组件职责：**
- **Proxy：** 请求入口，路由到 QueryNode 或 DataNode
- **QueryNode：** 向量相似度检索
- **DataNode：** 新数据写入，写入 MinIO 持久化
- **IndexNode：** 异步构建索引
- **MinIO (S3)：** 所有持久化数据（binlog、索引文件）
- **etcd：** 元数据存储（collection schema、segment 状态）

## 12.3 Partition Key 多租户隔离

### 方案对比

| 方案 | 实现方式 | 隔离性 | 性能 | 运维复杂度 |
|------|---------|--------|------|-----------|
| 每租户一个 Collection | tenant_001_kb, tenant_002_kb | 物理隔离，最强 | 检索时只需搜一个 collection | 租户多了管理困难 |
| Collection 字段过滤 | metadata["tenant_id"] = "xxx" | 逻辑隔离 | 全表扫描后过滤，慢 | 简单 |
| Partition Key | partition_key_field="tenant_id" | 逻辑隔离 + 性能优化 | 自动分区裁剪，只搜目标 partition | 最优方案 |

### Partition Key 工作原理

```python
# 创建 Collection 时指定 Partition Key
from pymilvus import Collection, FieldSchema, CollectionSchema, DataType

fields = [
    FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=256, is_primary=True),
    FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=64, is_partition_key=True),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024),
    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
]
schema = CollectionSchema(fields)
collection = Collection("knowledge_base", schema)

# 插入时 Milvus 自动按 tenant_id 分 partition
data = [
    {"id": "doc:1", "tenant_id": "tenant_001", "embedding": [0.1]*1024, "text": "..."},
    {"id": "doc:2", "tenant_id": "tenant_002", "embedding": [0.2]*1024, "text": "..."},
]
collection.insert(data)  # 自动路由到对应 partition

# 检索时指定 tenant_id，自动裁剪 partition
collection.search(
    data=[[0.15]*1024],
    anns_field="embedding",
    param={"metric_type": "IP", "params": {"nprobe": 16}},
    limit=10,
    expr='tenant_id == "tenant_001"',  # 只搜这个租户的 partition
)
```

**为什么 Partition Key 优于字段过滤：**
1. Milvus 根据 `is_partition_key=True` 自动创建和管理 partition
2. 查询时，如果 expr 中包含 partition key 的等值条件（`tenant_id == "xxx"`），Milvus 自动裁剪 partition——只搜索目标租户的数据，而非全库扫描后过滤
3. 对比 metadata 字段过滤：后者需要扫描所有数据然后过滤，性能差距在数据量大时是数量级的

## 12.4 迁移策略：三步法

### 完整迁移流程

```
Phase 1: Dry Run（预演）
  ├── 验证 Milvus 连接 & Collection Schema
  ├── 测试小批量数据（100 条）写入+检索
  ├── 验证检索结果与 Chroma 一致性
  └── 耗时：1 天

Phase 2: Migrate（迁移）
  ├── 从 Chroma 读取所有文档
  ├── 批量写入 Milvus（batch_size=1000）
  ├── 构建索引（后台异步）
  ├── 验证文档数量一致
  └── 耗时：取决于数据量（10 万向量约 10 分钟）

Phase 3: Verify（验证）
  ├── A/B 对比：同一 query 在 Chroma 和 Milvus 的 Top-10 结果
  ├── 相似度分数偏差分析
  ├── 权限过滤正确性验证
  ├── 延迟对比（P50/P95/P99）
  └── 通过后切换 VECTOR_BACKEND=milvus
```

### 迁移脚本核心逻辑

```python
class VectorMigration:
    """从 Chroma 迁移到 Milvus"""

    def __init__(self, chroma_store, milvus_store):
        self.source = chroma_store
        self.target = milvus_store

    async def migrate(self, batch_size: int = 1000):
        # 1. 从 Chroma 导出所有数据
        all_docs = self.source.get_all_documents()
        total = len(all_docs)

        # 2. 分批写入 Milvus
        for i in range(0, total, batch_size):
            batch = all_docs[i:i+batch_size]
            self.target.insert(batch)
            log.info("migration.progress", progress=f"{i+len(batch)}/{total}")

        # 3. 构建索引
        self.target.create_index(
            field_name="embedding",
            index_type="IVF_FLAT",
            metric_type="IP",
            params={"nlist": 1024}
        )
        self.target.load()  # 加载到内存

        # 4. 计数验证
        milvus_count = self.target.num_entities
        assert milvus_count == total, f"Count mismatch: {milvus_count} != {total}"

    async def verify(self, test_queries: List[str]):
        """A/B 对比验证"""
        for query in test_queries:
            chroma_results = self.source.search(query, k=10)
            milvus_results = self.target.search(query, k=10)

            # 对比 Top-10 重叠率
            chroma_ids = {r.id for r in chroma_results}
            milvus_ids = {r.id for r in milvus_results}
            overlap = len(chroma_ids & milvus_ids) / 10

            log.info("migration.verify",
                     query=query[:50],
                     overlap_ratio=f"{overlap:.1%}")
            assert overlap >= 0.8, f"Overlap too low: {overlap:.1%}"
```

### 回滚策略

```
Phase 1-2 期间：
  1. Chroma 保持为主数据源
  2. Milvus 为影子副本（shadow write）
  3. 随时可以切回 Chroma（VECTOR_BACKEND=chroma）

Phase 3 通过后：
  1. 切换 VECTOR_BACKEND=milvus
  2. Chroma 保留 7 天作为备份（不删除）
  3. 7 天无问题 → 删除 Chroma 数据
```

## 12.5 索引选择指南

| 索引类型 | 适用场景 | 内存占用 | 检索速度 | 召回率 | 本项目使用 |
|---------|---------|---------|---------|--------|-----------|
| FLAT | < 10 万向量 | 高 | 慢（暴力搜索） | 100% | 否 |
| IVF_FLAT | 10 万 - 100 万 | 中 | 中 | >95% | **默认** |
| IVF_PQ | 100 万 - 1000 万 | 低 | 快 | >90% | 数据量增长后切换 |
| HNSW | < 100 万 | 高 | 极快 | >98% | 高召回需求场景 |
| DISKANN | > 1000 万 | 极低（磁盘） | 中 | >90% | 未来考虑 |

**本项目默认 IVF_FLAT 的原因：**
- 数据量在 10 万 - 100 万之间
- 内存占用适中
- 召回率 >95%，满足客服场景需求
- nlist=1024, nprobe=16 参数经过实际调优

## 12.6 向量库迁移面试口述逻辑

**Q：为什么从 Chroma 迁移到 Milvus？**

A：Chroma 是优秀的嵌入式向量库，但在生产环境有三个致命问题：单点故障（无法高可用）、无法多副本共享索引（每个 RAG 实例一份独立索引，数据不一致）、无原生多租户隔离。Milvus 是分布式向量数据库，计算存储分离，Partition Key 原生支持多租户隔离——查询时自动 partition 裁剪，性能比 metadata 字段过滤高一个数量级。

**Q：迁移过程怎么保证数据一致性？**

A：三步法。Dry Run 阶段用小批量数据验证写入和检索。Migrate 阶段分批写入（batch_size=1000），完成后计数校验（Milvus num_entities == Chroma count）。Verify 阶段 A/B 对比同一 query 的 Top-10 结果，要求重叠率 >= 80%。通过后切换环境变量 VECTOR_BACKEND=milvus，Chroma 保留 7 天作为回滚备份。

---

# 第十三章：2026 年 AI Agent 三大工程热点

> 原第七章，涵盖 2026 年 Agent 领域的核心工程趋势

## 13.1 MCP (Model Context Protocol)

MCP 是 Anthropic 提出的模型-工具通信标准协议，目标是让 LLM 和工具之间的交互像 HTTP 一样标准化。

**核心概念：**
- **Server：** 工具提供方，暴露 resources（数据）、tools（函数）、prompts（模板）
- **Client：** LLM 宿主（如 Agent 应用），发现和调用 Server 的能力
- **Transport：** stdio（本地进程）/ SSE（远程 HTTP）/ Streamable HTTP

**本项目实践：** 通过 zeromcp 实现 MCP Server，暴露 RAG 检索工具给外部 Agent 调用。

## 13.2 A2A (Agent-to-Agent)

Google 提出的智能体间通信协议，标准化 Agent 之间的任务委托和结果返回。

**核心概念：**
- **Agent Card：** JSON 描述 Agent 的能力和端点
- **Task：** 委托的任务描述（可带 artifact 附件）
- **Message：** 文本/文件/数据的通用消息格式

**本项目的架构决策——为什么 v2.0 不做 A2A 多智能体：**
- v0.4 的 Expert Delegate 预期通过 A2A 调用外部专家 Agent——但外部服务不存在
- v2.0 扁平化为 handler 函数，A2A 保留为可插拔的未来能力

## 13.3 Agent 可观测性（OpenTelemetry + 语义约定）

2026 年的趋势是将 Agent 的调用链纳入标准的分布式追踪体系。

**GenAI 语义约定：** OpenTelemetry 为 LLM 操作定义了标准 span 属性：
- `gen_ai.request.model` — 模型名称
- `gen_ai.usage.input_tokens` — 输入 Token 数
- `gen_ai.usage.output_tokens` — 输出 Token 数
- `gen_ai.system` — 供应商（anthropic/openai/dashscope）

**本项目状态：** 已在代码中预留 OpenTelemetry trace 插桩点，尚未正式接入 Jaeger。

---

# 第十四章：多智能体架构扁平化（v2.0 重构）

> 原第八章，更新日期：2026-07-12
> 核心变化：5 个子图 + 1 个父图 → 1 个单层 StateGraph + 8 个 handler 函数

## 14.1 重构前的问题

### 问题 1：过度嵌套

v0.4 的多智能体架构使用了 5 个独立的 LangGraph 子图（FAQ/RAG/Reflect/Chat/Expert），每个子图都有自己的 StateGraph 和 StateType。父图通过桥接函数在 6 种 State 之间转换。

**嵌套层级：**
```
parent_workflow.py (StateGraph)
  ├── invoke_faq_subgraph() → FAQAgentState → faq_agent.py (StateGraph)
  ├── invoke_rag_subgraph() → RAGAgentState → rag_agent.py (StateGraph)
  ├── invoke_reflect_subgraph() → ReflectAgentState → reflect_agent.py (StateGraph)
  └── expert_delegate_node() → 直接调用
```

**问题：** 一个用户消息要经历：`entry → clarify → router → faq_subgraph → invoke_faq_subgraph → FAQAgentState → faq_query_node → faq_reply_node → 桥接回父 State → reply`。每一层都在拷贝 State 字段，增加了不必要的开销。

### 问题 2：职责重叠

| 功能 | 在哪里实现 | 重复次数 |
|------|-----------|---------|
| FAQ 关键词匹配 | `faq_agent.py` + `tools.py` 的 `search_faq` | 2 次 |
| 质量审查 | `reflect_agent.py` + `nodes.py` 的 `reflect_node` | 2 次 |
| 闲聊检测 | `chat_agent.py` + `router_node` 关键词判断 | 2 次 |
| 意图路由 | `router_node` + `_decide_route` | 2 次 |

### 问题 3：追问误杀

`clarify_node` 在 `router_node` 之前执行，看到"怎么"就认为是排查类问题，要求追问技术环境。导致"怎么重置密码"这种标准 FAQ 也被误杀。

### 问题 4：死代码

- `expert_delegate.py` 调用的 A2A 服务不存在
- `reflect_node` 在 nodes.py 中定义但 parent_workflow 用的是 `reflect_subgraph`
- `chat_agent.py` 只在 `invoke_faq_subgraph` 里被间接调用

## 14.2 重构方案

**核心原则：职责分离不等于子图嵌套**

多智能体的本质是每个组件有明确的职责边界，但这不意味着每个职责都必须是一个独立的 LangGraph StateGraph。对于简单的关键词匹配（FAQ）、闲聊回复等，一个普通函数就够了。

### 新旧架构对比

| 维度 | v0.4（重构前） | v2.0（重构后） |
|------|---------------|---------------|
| 子图数量 | 5 | 0 |
| StateGraph 层数 | 6 层 | 1 层 |
| StateType 数量 | 4 | 1 |
| 桥接函数 | 3 | 0 |
| 代码行数 | ~1200 | ~500 |
| 调试难度 | 高（跨子图 State 转换） | 低（一个 StateGraph） |

### 新的执行流程

```
entry → classify → {faq_handle | rag_handle | human}
                            ↓
                    reflect? → reply → END
                            ↓
                    expert? → reflect → reply
```

**关键改进：**
1. `classify_node` 合并了 clarify + router，先意图分类再决定追问
2. FAQ 豁免列表：密码重置、SSO 配置、403 错误等不走追问
3. 情绪检测前置：愤怒/紧急用户直接转人工
4. 追问仅对 technical 意图生效
5. Handler 是普通函数，不再是 StateGraph 子图

## 14.3 多智能体 vs 单智能体的取舍

### 什么时候用子图？

- 子图内部有复杂的循环（RAG 的 ReAct 多轮推理）
- 子图需要独立部署或独立扩展（Expert Delegate 的 A2A 远程服务）
- 子图需要独立的状态管理和 checkpoint

### 什么时候不用子图？

- 只是简单的关键词匹配（FAQ 子图就是个 dict 查找）
- 逻辑简单且不会被独立调用（闲聊回复直接一个 if 语句）
- 子图之间只是顺序调用，没有独立的状态管理需求

### 判断标准

> 如果一个 handler 内部超过 3 个节点、有循环、需要独立部署，就用子图。否则就是一个普通函数。

## 14.4 学到的教训

1. **追问逻辑必须在路由之后** — 先判断意图类型，再决定是否需要追问
2. **FAQ 豁免列表是必须的** — 关键词匹配的问题不应该进入追问流程
3. **情绪检测要前置** — 愤怒用户不需要追问，应该直接转人工
4. **子图不是越多越好** — 简单的关键词匹配不值得编译成 StateGraph
5. **职责分离不等于子图嵌套** — 多智能体的本质是职责分离，不是每个职责都要一个 StateGraph

## 14.5 面试回答模板

**Q：你的项目从多子图架构改成了什么？**

A：从 5 个独立 LangGraph 子图 + 1 个编排父图，扁平化为 1 个单层 StateGraph + 8 个 handler 函数。核心变化是：不再为每个职责都编译一个 StateGraph，而是把简单的职责（FAQ 匹配、闲聊回复）变成普通函数，只在真正需要复杂循环的场景（RAG 的 ReAct 推理）才保留子图概念。这样减少了 700+ 行代码，消除了所有桥接函数，调试难度大幅降低。

**Q：追问逻辑的 bug 是怎么发现的？**

A：用户说"怎么重置密码"，系统反问"请提供 SDK 版本和操作系统"。根因是 clarify_node 在 router_node 之前执行，看到"怎么"就认为是排查类问题。修复方案是合并 classify_node，先意图分类再决定追问，并加了 FAQ 豁免列表。

**Q：多智能体架构中，什么时候该用子图？**

A：判断标准是：如果 handler 内部超过 3 个节点、有循环、需要独立部署，就用子图。否则就是一个普通函数。比如 FAQ 匹配就是个 dict 查找，不值得编译成 StateGraph；但 RAG 的 ReAct 循环有多轮推理，值得保留子图结构。

---

# 第十五章 业务系统模块设计与实现（v2.2 新增）

**对应代码：** `src/api/rbac.py`, `src/api/auth.py`, `src/api/tickets.py`, `src/api/customers.py`, `src/api/satisfaction.py`, `src/api/notifications.py`, `src/api/dashboard.py`, `src/api/admin.py`, `src/seed.py`, `frontend/src/components/AdminDashboard.tsx`

---

## 15.1 RBAC 权限模型设计

### 为什么选 RBAC 而不是 ABAC？

**RBAC（Role-Based Access Control）**：用户 → 角色 → 权限，三层映射。
**ABAC（Attribute-Based Access Control）**：基于属性（用户部门、资源敏感度、时间等）动态决策。

客服场景的角色边界非常清晰：超级管理员（管一切）、管理员（管业务）、客服（处理工单）、观察员（只看数据）。不需要 ABAC 那种"财务部员工在工作时间可以访问部门内非机密文档"的复杂属性表达式。

**实现要点：**
- 4 个角色枚举 + 15 个权限点枚举
- `ROLE_PERMISSIONS: Dict[UserRole, List[Permission]]` 硬编码映射
- `require_permissions(...)` 依赖注入，O(1) 权限校验
- 前端用同样的映射做按钮/菜单显隐控制

**面试常问：** 如果用户量扩大到 10 万，需要"客服只能看自己分配的工单"怎么办？
**答案：** RBAC + 资源属主（Owner）模型。权限校验分两步：① 角色是否有 `ticket:view`；② 如果不是 admin，是否 `ticket.assignee == current_user.id`。

---

## 15.2 工单状态机设计

### 状态机 vs 自由更新

很多初学者设计工单时，直接在 API 里 `UPDATE tickets SET status = ? WHERE id = ?`，这会导致：
- 已关闭的工单被 reopen（可能是误操作，也可能是恶意）
- 状态跳跃（open → closed，跳过 in_progress）
- 没有历史记录，不知道谁、什么时候、为什么改了状态

**正确做法：**
1. **定义合法转换**：open → in_progress / cancelled；in_progress → resolved / closed / open
2. **终态不可变**：resolved / closed / cancelled 不允许再 update
3. **评论独立**：工单关闭后仍可添加评论（历史补充），但状态不变
4. **生产级**：数据库层加 CHECK 约束 + 乐观锁（version 字段）

```python
# 业务层校验
if ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
    raise HTTPException(status_code=400, detail="Closed tickets cannot be updated")
```

---

## 15.3 数据仪表盘的数据聚合策略

### 实时聚合 vs 预计算

**实时聚合（当前实现）：**
- 优点：数据最新，没有延迟
- 缺点：每次请求都计算，数据量大时性能下降
- 适用：开发环境、数据量 < 10 万条

**预计算（生产推荐）：**
- Redis 计数器：`INCR agent:requests:total`，实时累加
- 定时任务：每 5 分钟把聚合结果写入 `dashboard_stats` 表
- 仪表盘读缓存，延迟 5 分钟但性能稳定

**时序数据库（大规模）：**
- Prometheus：指标天然时序，Grafana 直接读
- ClickHouse：亿级数据秒级聚合
- InfluxDB：专门做时间序列统计

---

## 15.4 人工客服工作台的 SSE 实时推送

### 为什么用 SSE 而不是 WebSocket？

**SSE（Server-Sent Events）：**
- 单向推送（服务器 → 客户端），适合"客服看队列"这种服务器主动推送场景
- 基于 HTTP，自动重连，穿透防火墙容易
- 实现简单，不需要维护 WebSocket 连接状态

**WebSocket：**
- 双向通信，适合"客服和用户实时对话"
- 本项目客服回复走 REST API，队列推送走 SSE，分工明确

**实现要点：**
1. FastAPI 用 `StreamingResponse` + `async def event_generator()`
2. 客服连接 SSE 后，服务器持续 yield 队列状态变化
3. 用户点击"转人工" → 触发队列更新 → 所有连接的客服收到新事件

---

## 15.5 演示数据注入的工程价值

### 为什么花精力做 seed.py？

1. **降低演示门槛**：新人 clone 项目后，无需手动创建数据就能看到完整界面
2. **保证数据一致性**：工单关联客户、满意度关联工单，数据之间有真实业务逻辑
3. **覆盖边界情况**：工单覆盖全部 5 种状态，满意度覆盖 1-5 星分布
4. **幂等设计**：重复启动不重复生成，避免数据膨胀

**环境隔离：**
- `SEED_DEMO_DATA=false` 可关闭
- 内存存储，重启清空，不会污染生产

---

## 15.6 面试高频问题

**Q：权限系统设计时，如何避免前端绕过？**
A：前端权限只做 UI 控制（按钮显隐），真正的权限校验在后端 API。即使前端隐藏了按钮，直接调 API 也会 403。

**Q：工单状态机如果上生产，数据库层怎么保障？**
A：PostgreSQL CHECK 约束 + 触发器记录状态变更历史 + 乐观锁 version 字段防止并发修改。

**Q：仪表盘数据量大怎么优化？**
A：三级策略——① Redis 计数器实时累加；② 定时任务预计算写入缓存；③ 时序数据库（ClickHouse/Prometheus）做历史趋势。

---

# 附录 A：项目文件结构（v2.2 云原生版 + 业务系统）

```
enterprise-agent/
├── src/
│   ├── common/                 # 共享库 (enterprise-agent-common)
│   │   ├── types.py            # 共享数据模型
│   │   ├── exceptions.py       # 统一异常
│   │   ├── logging_config.py   # structlog 配置
│   │   ├── metrics.py          # Prometheus 指标注册
│   │   └── config.py           # pydantic-settings 配置
│   │
│   ├── agent_service/          # Agent 微服务
│   │   ├── main.py             # FastAPI app
│   │   ├── graph/              # LangGraph 工作流
│   │   ├── handlers/           # 8 个 handler 函数（v2.0 扁平化）
│   │   ├── memory/             # 记忆管理 + Redis 锁
│   │   ├── safety/             # 安全护栏 + 注入检测
│   │   └── evaluation/         # 评估 + LLM-as-Judge
│   │
│   ├── rag_service/            # RAG 微服务
│   │   ├── main.py             # FastAPI app
│   │   ├── loader.py           # DocumentLoader 编排器
│   │   ├── data_sources.py     # 数据源抽象
│   │   ├── loaders/            # 格式加载插件
│   │   ├── processors/         # 处理管道
│   │   ├── chunker.py          # HybridChunker
│   │   ├── embedder.py         # DashScope Embedding
│   │   ├── vector_store/       # 多后端适配
│   │   │   ├── base.py
│   │   │   ├── chroma_backend.py
│   │   │   └── milvus_backend.py
│   │   ├── retriever.py        # 混合检索 + 多后端路由
│   │   ├── concurrency.py      # RateLimiter + CircuitBreaker
│   │   ├── sync_state.py       # 同步状态表
│   │   ├── file_sync_manager.py
│   │   ├── vision_engines/     # 视觉引擎插件
│   │   └── safety/             # PII + 合规检测
│   │
│   ├── ws_service/             # WebSocket 微服务
│   │   ├── main.py
│   │   └── pubsub.py           # Redis Pub/Sub
│   │
│   └── worker_service/         # 异步 Worker
│       ├── main.py
│       ├── consumers/           # RabbitMQ 消费者
│       │   ├── rag_consumer.py
│       │   ├── reflect_consumer.py
│       │   └── notify_consumer.py
│       └── dlq_handler.py      # DLQ 处理
│
├── docker/                     # Dockerfile（每服务一个）
│   ├── agent.Dockerfile
│   ├── rag.Dockerfile
│   ├── ws.Dockerfile
│   └── worker.Dockerfile
│
├── docker-compose.yml          # 12 服务编排
├── docker-compose.override.yml # 开发环境覆盖
│
├── helm/enterprise-agent/     # Helm Chart
│   ├── Chart.yaml
│   ├── values.yaml
│   ├── values-dev.yaml
│   ├── values-prod.yaml
│   └── templates/
│       ├── deployment-*.yaml
│       ├── service.yaml
│       ├── ingress.yaml
│       ├── configmap.yaml
│       ├── secret.yaml
│       └── hpa.yaml
│
├── .gitlab-ci.yml              # GitLab CI 6 阶段 pipeline
├── argocd/                     # ArgoCD 配置
│   └── enterprise-agent.yaml
│
├── monitoring/                 # 可观测性配置
│   ├── prometheus/
│   │   ├── prometheus.yml
│   │   └── rules/
│   │       └── agent-alerts.yml  # 8 条告警规则
│   ├── grafana/
│   │   └── dashboards/
│   │       └── agent-overview.json  # 12 面板仪表盘
│   └── loki/
│       └── loki-config.yaml
│
├── scripts/
│   ├── migrate_vector.py       # Chroma → Milvus 迁移脚本
│   └── seed_data.py            # 测试数据填充
│
├── tests/                      # 48 个测试用例
├── data/docs/                  # 产品文档（RAG 源数据）
└── pyproject.toml
```

**项目统计（v2.1）：**
- 总代码行数：14,707 行
- Python 模块：90 个
- 测试用例：48 个
- Docker 服务：12 个
- GitLab CI Stage：6 个
- Prometheus 告警规则：8 条
- Grafana 面板：12 个
- 核心微服务：4 个（Agent / RAG / WS / Worker）

---

# 附录 B：核心概念速查表

| 概念 | 一句话解释 | 对应章节 |
|------|-----------|---------|
| RAG | 检索增强生成——先检索相关文档再让 LLM 回答 | 第一章 |
| ReAct | Reasoning + Acting——LLM 交替思考和调用工具 | 第二章 |
| LangGraph | 有状态图执行框架——构建多步骤 Agent 工作流 | 第三章 |
| RRF | Reciprocal Rank Fusion——不关心绝对分数，只关心排名 | 第一章 |
| Small2Big | 句子级检索 + 上下文展开——精准定位、完整生成 | 第一章 |
| Milvus | 分布式向量数据库——支持 Partition Key 多租户隔离 | 第十二章 |
| APISIX | 云原生 API 网关——统一入口、限流、熔断 | 第七章 |
| K3s | 轻量级 Kubernetes——50MB 二进制，256MB 内存 | 第七章 |
| Helm | Kubernetes 包管理器——模板化部署配置 | 第七章 |
| ArgoCD | GitOps 引擎——Git 是单一真实来源 | 第九章 |
| RabbitMQ | 消息队列——异步解耦、削峰填谷 | 第八章 |
| DLQ | Dead Letter Queue——处理失败的消息存放处 | 第八章 |
| MinIO | S3 兼容对象存储——文档/图片/模型的存储层 | 第八章 |
| Partition Key | Milvus 的分区字段——自动 partition 裁剪 | 第十二章 |
| KEDA | Kubernetes Event-Driven Autoscaling——基于队列深度扩缩 | 第七章 |
| GitOps | 声明式基础设施——Git 作为期望状态来源 | 第九章 |
| GitLab CI | CI/CD 流水线——6 阶段自动化 | 第九章 |
| Prometheus | 监控系统——时序数据库 + 告警 | 第十一章 |
| Grafana | 可视化平台——12 面板仪表盘 | 第十一章 |
| Histogram | Prometheus 指标类型——服务端计算分位数（p50/p95/p99） | 第十一章 |
| structlog | 结构化日志库——JSON 输出，Loki 友好 | 第十一章 |
| Redis 分布式锁 | Lua 脚本保证 SET + EXPIRE 原子性 | 第四章 |
| LLM-as-Judge | 用更强的模型评判 Agent 回答质量 | 第五章 |
| Prompt Injection | 通过用户输入覆盖 System Prompt 的攻击方式 | 第六章 |
| MCP | Model Context Protocol——LLM 和工具的标准通信协议 | 第十三章 |
| A2A | Agent-to-Agent——智能体间通信协议 | 第十三章 |
