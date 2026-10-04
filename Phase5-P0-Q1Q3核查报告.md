# Phase5 P0：Q1+Q3 功能实现状态核查报告

核查时间：2026-09-17
核查方式：纯只读（源码阅读 + 容器内 Chroma 只读采样），未修改任何代码、配置、容器与数据卷。
容器环境：`prod-app-1`（镜像 `enterprise-agent-app-ollama:latest`），Chroma 真实路径 `/app/chroma_data`（由 `CHROMA_PERSIST_DIR` 环境变量指定，注意它并非 `/app/data/chroma`）。

---

## 一、Q1 kb_call_mode 核查

### 1.1 配置定义

**定义处 1** `src/config.py:121-127`

```python
kb_call_mode: str = (
    # Phase3 离线改造: 枚举统一为 always / smart / never（与 config_center/schema.py 对齐）
    # always: 进入 rag_node 后强制先执行一次检索，不依赖 LLM 自主决策
    # smart : LLM 在 ReAct 中自主决定是否检索（原有行为）
    # never : 进入 rag_node 后跳过检索，直接由 LLM 基于对话历史回答
    "always"
)
```

**定义处 2** `src/config_center/schema.py:128-130`

```python
# Phase3 离线改造: 枚举与 src/config.py 的 kb_call_mode 注释统一为 always/smart/never
# （原为 auto/always/never，auto 无实现且与 smart 语义重叠）
"kb_call_mode": FieldSpec(enum=("always", "smart", "never")),
```

**定义处 3** `src/config_center/categories.py:25-31`：归入 `retrieval`（检索配置）分类，管理员可通过配置中心 API 运行时修改，无需重启。消费点每次请求用 `getattr(settings, "kb_call_mode", ...)` 现读（见 1.2），所以改配置即时生效，属于真热更新。

小结：类型 `str`，默认值 `"always"`，枚举三值与注释三方对齐（config.py / schema.py / categories.py）。历史上曾是 `auto/always/never`，`auto` 已在 Phase3 清除。

### 1.2 三种模式实现分析

唯一消费点在 `src/graph/nodes.py` 的 `rag_node`（全仓库 `kb_call_mode` 命中共 3 个文件，业务消费仅此一处）。

**模式归一化** `src/graph/nodes.py:1052-1056`

```python
_kb_mode = (getattr(settings, "kb_call_mode", "always") or "always").strip().lower()
if _kb_mode not in ("always", "smart", "never"):
    logger.warning("未知 kb_call_mode=%s，回落 smart", _kb_mode)
    _kb_mode = "smart"
logger.info("[kb_call_mode=%s] 检索策略已应用", _kb_mode)
```

空串、未知值、大小写混杂都会被归一到合法三值，兜底方向是 `smart`。

**never 分支** `src/graph/nodes.py:1060-1089`

```python
if _kb_mode == "never":
    # 跳过检索：直接由 LLM 基于对话历史作答。
    # 关键约束：reply_node 在 final_response 为空时只会返回固定兜底话术
    # （见 reply_node 的 `elif not final_response` 分支），并不会补一次
    # LLM 调用，因此这里必须自己产出回答，否则该模式会退化成「统一道歉」。
    try:
        _plain_prompt = (
            "你是工业设备客服助手。请仅依据对话历史回答问题，"
            "不要声称查阅了知识库或文档。用简体中文作答，第一句直接给结论。\n\n"
            f"用户问题：{content}"
        )
        _plain_llm = ChatOpenAI(...)
        _plain_resp = _plain_llm.invoke(_plain_prompt)
        ...
    except Exception as exc:
        logger.warning("[kb_call_mode=never] 纯 LLM 作答失败：%s", exc)
        _plain_text = ""
    return {"final_response": _plain_text, ..., "retrieved_docs": [], ...}
```

完整实现。跳过检索与 Agent，直接一次 LLM 调用；失败时返回空串且 `answer_status="refused"`。注释明确记录了与 `reply_node` 兜底行为的约束关系。

**always 分支** `src/graph/nodes.py:1091-1117`

```python
if _kb_mode == "always" and retriever is not None:
    # 强制预检索：先把结果预置，保证即使 LLM 不调工具也有可溯源文档。
    # 这是「叠加」而非「替换」——下面的 Agent 流程照常执行，可再检索一次。
    try:
        _pre_top_k = int(getattr(settings, "retrieval_top_k", 5))
    ...
    pre_retrieved_docs = retriever.search(content, top_k=_pre_top_k, ..., tenant_id=_read_tenant(state), ...)
```

完整实现。top_k 有 `[1, 50]` 钳制；预检索异常时降级为空列表继续走 Agent（等于临时退回 smart 行为）；预检索是叠加式，Agent 仍可二次检索。

预检索结果的并回在 `src/graph/nodes.py:1239-1256`，按 `page_content` 前 100 字符去重后追加进 `retrieved_docs`，避免引用气泡重复。

**smart 分支**：无显式 `if _kb_mode == "smart"` 代码块。never 和 always 的两个 if 都不命中时，控制流直落到 `src/graph/nodes.py:1119` 起的 Agent 构建与执行，即保持原有行为。`pre_retrieved_docs` 保持空列表，是否检索由 LLM 在 ReAct 中决定（调 `search_knowledge_base` 工具或直接作答）。

另有一个兜底细节值得记录（`src/graph/nodes.py:1270` 起）：Agent 全程没触发检索工具导致 `retrieved_docs` 为空时，rag_node 会用原始查询主动补一次结构化检索回填，所以 smart 模式下引用气泡不会必然为空。

### 1.3 smart 模式判据

smart 模式没有独立判据函数。决策者就是 ReAct 循环里的 7B LLM 本身，它看着工具清单里的 `search_knowledge_base` 自主决定调或跳过。意图分类器不参与（意图分类产出 `faq` / `technical` / `human` 三值，与 kb_call_mode 正交）。唯一相关的"判据"是 1.2 的未知值回落规则（`nodes.py:1053-1055`）。

辩证看这一点：smart 把决策权交给模型，语义上最"智能"，但在 CPU 上跑 7B 时模型不调工具的概率不可控，这正是 Phase3 把默认值设为 always 的现实理由。三种模式的取舍是可用性与自主性的权衡，代码注释对此是坦诚的。

### 1.4 测试覆盖

全仓库测试中 `kb_call_mode` 仅 1 处命中。

**`tests/test_api/test_config_center.py:252-259`**

```python
def test_enum_violation_rejected(self, client, admin_headers):
    resp = client.put(
        "/api/v1/config/kb_call_mode",
        json={"value": "sometimes"},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "只接受" in resp.json()["detail"]
```

只覆盖了配置中心 API 的枚举校验，没碰 rag_node 的分支行为。

**`tests/test_graph/test_nodes_llm.py:247-319`** 有 4 个 rag_node 测试（basic / tool_docs_priority / escalate / retriever_fallback），全部在默认配置（即 `kb_call_mode="always"`）下运行，没有 monkeypatch 该配置。其中 `test_rag_node_basic` 未传 retriever，always 分支因 `retriever is None` 短路；`test_rag_node_retriever_fallback` 传入了 FakeRetriever，实际上让预检索与补检代码得到了执行，但测试断言只到 `res["retrieved_docs"]` 非空，没有区分"命中了哪种模式"。

覆盖缺口：never 分支零测试；smart 分支零测试；unknown 值回落 smart 的分支零测试；always 预检索失败降级路径零测试。

### 1.5 结论表

| 模式 | 实现状态 | 代码位置 | 测试覆盖 | 缺陷/缺失 |
|---|---|---|---|---|
| always | 已实现（默认值） | `nodes.py:1091-1117`（预检索）+ `nodes.py:1239-1256`（去重并回） | 间接覆盖（rag_node 测试在默认 always 下执行，但无模式级断言） | 预检索失败降级路径无测试 |
| never | 已实现 | `nodes.py:1060-1089` | 无 | 零测试；失败路径返回空串依赖 reply_node 话术，行为未被任何用例锁定 |
| smart | 已实现（直落分支） | `nodes.py:1052-1055`（未知值回落）+ `nodes.py:1119` 起（Agent 构建） | 无 | 零测试；无显式分支代码，回归时容易在无感知下被改坏 |

**Q1 总判定：三模式均已真实实现，配置真热更新，非占位开关。短板全在测试侧（仅枚举校验 1 条用例），建议补 3 个分支级测试。**

---

## 二、Q3 引用页码核查

### 2.1 文档切分层

**基础 metadata 无页码字段** `src/rag/loader.py:100-115`

```python
def _build_base_meta(info: FileInfo, encoding: str, default_tenant_id: str) -> dict:
    return {
        "source": info.name,
        "category": _get_category(info.ext),
        "kb_type": _get_kb_type(info.ext),
        "doc_format": ...,
        "created_time": ..., "modified_time": ..., "encoding": encoding,
        "tenant_id": default_tenant_id,
    }
```

**PDF 路径注入页码** `src/rag/loaders/pdf_loader.py:22-56`（`_inject_page_metadata`）

```python
doc.metadata["page"] = full_text.count("---PAGE-BREAK---", 0, pos) + 1   # 1-based
# 定位失败时：
doc.metadata["page"] = None    # "宁可 None，也不要给出错误页码"
```

调用点 `pdf_loader.py:183`（在结构提示注入前执行）。页码挂在章节级，粒度是"该章节起始页"。

**切块器保留页码**：标准路径 `src/rag/chunker.py:322-332` 用 `metadata=dict(doc.metadata)` 复制；句子路径 `src/rag/chunker.py:177-180` 用 `{**doc.metadata, ...}` 展开。两者都透传 page。

**其他格式的页码来源**：
1. `src/rag/processors/noise_filter.py:63-72` 能从 "第 N 页 / Page N" 文本行提取 `metadata["page"]`（挂在处理器管线，`loader.py:350-356` / `processors/base.py:130`）。对带页脚的 MD/TXT 是潜在补充来源。
2. **DeepDoc 扫描件路径写的是 `page_number`** `src/rag/deepdoc_parser.py:217-224`，字段名与 citations 读取的 `page` 不一致，属于链路内的命名分歧。

**DOCX / TXT / MD 的 loader 均无原生页码注入**（`pdf_loader.py:180-182` 注释明说：引用层读不到即为 None）。

### 2.2 Chroma 存储层

入库链路 `src/api/knowledge.py:495-527`：`HybridChunker.split_standard` 切块后注入 `kb_id` / `doc_id` / `source_type` / `tenant_id`，page 键原样保留，未做剥离。

写入 `src/rag/vector_store.py:75-84` → langchain Chroma `add_documents`，metadata 整体透传（容器内 `langchain_chroma/vectorstores.py` 的 `add_texts` 不做键清洗，遇到非法类型只会抛 ValueError 并提示用 `filter_complex_metadata`）。

关键事实：**Chroma 无法持久化 None 值的 metadata 键**。代码里 `page=None` 的章节，入库后该键会消失。生产数据可以实证这一点（见 2.6）。写入层本身没有丢弃 page，丢键发生在 Chroma 对 None 的处理上。

### 2.3 检索返回层

`src/rag/vector_store.py:123-127` Chroma 分支用 `similarity_search_with_relevance_scores` 返回完整 metadata 的 Document。后续四个环节逐一核对：

1. `_chroma_vector_search`（`retriever.py:495-502`）：相似度过滤只按分数筛，不动 metadata。
2. `_rrf_fusion`（`retriever.py:660-696`）：`doc_map[doc_id] = doc` 直接持有原对象，返回的也是同一批对象。
3. `_merge_standard_and_sentence`（`retriever.py:864-880`）：`merged.append((doc, score))`，原对象透传。
4. `_resolve_version_conflicts`（`retriever.py:999-1049`）：分组按 `doc.metadata.get("source")`，键 `position = {id(doc): idx}` 证明它刻意保持 Document 对象同一性。

结论：检索返回层不丢 page。Milvus / Remote 分支（`retriever.py:522-534` / `566-576`）重建 Document 时用 `**h["metadata"]` 展开，同样保留。当前生产 backend 是 chroma（`VECTOR_STORE_BACKEND=chroma`），Milvus 路径仅为架构就绪状态。

### 2.4 citations 构建层

`src/websocket/routes.py:479-521`（`_build_citations`）

```python
citations.append({
    "title": title, "content": content, "score": round(score, 4),
    "source": source, "doc_id": doc_id, "kb_id": kb_id,
    # Phase3 离线改造: 补页码字段。仅 PDF 来源的切片有值（由
    # src/rag/loaders/pdf_loader.py 注入），DOCX/TXT/MD 及缺失时统一为 None。
    "page": meta.get("page") if isinstance(meta, dict) else None,
})
```

第 519 行已提取 page。构建层完整。

### 2.5 API 返回层与前端

**WS 返回** `src/websocket/routes.py:766` 构建后于 `:855` 随 `agent_send_reply` 的 `metadata.citations` 下发，page 字段在内。

**前端类型定义** `frontend/src/App.tsx:752-759`

```ts
interface ChatCitation {
  title: string
  content: string
  score: number
  source: string
  doc_id?: string
  kb_id?: string
}
```

**前端渲染** `frontend/src/App.tsx:1188-1193`：引用卡片只渲染 `c.title`、`c.score`（匹配度）、`c.content` 三项。

**page 字段在后端响应里存在，前端类型没有声明它，渲染也没有用它。这一层就是断点。**

### 2.6 生产数据验证（只读采样）

容器内查询 `/app/chroma_data` 的 `knowledge_base` 集合，全量 315 块（未截断采样，`limit=400` 大于总量）：

```
=== metadata 键组合分布 ===
302 块: category, created_time, doc_format, doc_id, encoding, kb_id, kb_type,
        modified_time, source, source_file, source_type, tenant_id
  9 块: 上述 + chapter_path, heading_level, heading_text      （kb_md_manual.md）
  3 块: 上述 + author（kb_docx_upgrade.docx）
  1 块: 上述 + author, producer, title, total_pages           （kb_pdf_safety.pdf）

=== page 相关字段 ===
page         存在于 0 块，非 None 值 0 块
page_number  存在于 0 块，非 None 值 0 块
page_idx     存在于 0 块，非 None 值 0 块

=== source 分布（前几名）===
after_sales_policy.md 62 / maintenance_guide.md 48 / product_spec_manual.md 44 /
calibration_guide.md 43 / application_guide.md 40 / faq_full.md 37 /
fault_troubleshooting_manual.md 27 / kb_md_manual.md 9 / kb_docx_upgrade.docx 3 /
kb_txt_note.txt 1 / kb_pdf_safety.pdf 1
```

三个事实值得并列陈述：

1. **生产库 315 块中 0 块带页码**。全部素材是 MD/TXT/DOCX，仅 1 块 PDF。
2. **唯一的 PDF 块（kb_pdf_safety.pdf）也没有 page 键**。它带 `total_pages` / `title` / `author` / `producer`（`pdf_loader.py:144` 写入的 PyMuPDF 信息），证明走了 PdfLoader。而 `_inject_page_metadata` 对每个章节必然写 `page`（int 或 None）。键整体缺失与 2.2 的结论自洽：指纹定位失败写入 None，Chroma 持久化时丢弃了 None 键。只读条件下无法区分"指纹失败"与"其他绕行路径"，但无论哪种，落库结果就是没有页码。
3. DeepDoc 的 `page_number` 字段在生产数据中同样为 0 块（deepdoc_enabled 未开启或未走扫描路径），所以字段名分歧目前未造成实际脏数据，只是潜在风险。

### 2.7 结论表与修复建议

| 环节 | 页码状态 | 代码位置 | 缺失说明 |
|---|---|---|---|
| 文档切分层 | PDF 有（章节起始页，1-based），MD/DOCX/TXT 无 | `pdf_loader.py:22-56, 183`；`chunker.py:177-180, 322-332` | DeepDoc 扫描路径写 `page_number`，与读取方字段名不一致 |
| Chroma 存储层 | 透传，但 None 键被 Chroma 丢弃 | `vector_store.py:75-84`；langchain-chroma `add_texts` | 生产 PDF 块实测无 page 键 |
| 检索返回层 | 保留（四个后处理环节均原对象透传） | `retriever.py:495-502, 660-696, 864-880, 999-1049` | 无 |
| citations 构建层 | 已提取 page | `routes.py:519` | 无 |
| API 返回层 | 返回 JSON 含 page | `routes.py:766, 855` | 无 |
| 前端展示 | **无页码展示** | `App.tsx:752-759`（类型无字段）、`App.tsx:1188-1193`（渲染未用） | **断点在此** |

**Q3 总判定：页码链路后端全通（切分、存储、检索、构建、下发五层都实现了），前端是唯一断点。但生产数据里 0 块带页码，意味着即使补上前端，现有素材也展示不出任何页码。功能"代码已就绪"，效果"数据上空转"。**

修复建议（仅建议，不实施）：

1. **前端补 page 字段与渲染**（改动最小收益最直接）：`ChatCitation` 加 `page?: number | null`，引用卡片 head 处加 `c.page ? \`第 ${c.page} 页\` : null` 徽标。
2. **pdf_loader 写键策略收紧**：定位成功才写 `metadata["page"]`，失败时干脆不写键。现在的 None 写法落库即被 Chroma 静默丢弃，排查时会产生"代码写了但库里没有"的困惑（本次核查就花了一轮定位）。
3. **统一 DeepDoc 字段名**：`deepdoc_parser.py:221` 的 `page_number` 改为 `page`，或在 `_build_citations` 加兼容读取 `meta.get("page") or meta.get("page_number")`。
4. **演示素材**：现有 `kb_pdf_safety.pdf` 只切出 1 块且无页码。若要在 demo 里真实展示页码气泡，需要导入一份带书签的多页 PDF 手册并重跑入库。

---

## 三、总体结论与下一步建议

**Q1（kb_call_mode）：真实三模式实现，配置真热更新，无假开关。** always 有预检索与去重并回，never 有独立 LLM 直答路径（还处理了与 reply_node 兜底的约束），smart 直落 Agent 自主决策。短板集中在测试：三种模式加未知值回落，目前只有 1 条 API 枚举校验用例。

**Q3（引用页码）：后端五层贯通，断点在前端，且生产数据无页码素材。** 这是个典型的"半成品纵向切片"：Phase3 把数据链路修到了最后一公里，前端消费端没跟上，同时演示语料里没有能体现它的 PDF。

优先级建议（按投入产出比排序）：

| 优先级 | 事项 | 理由 |
|---|---|---|
| P0 | 前端 ChatCitation 加 page 字段并渲染 | 后端已就绪，改动一处即可闭环 |
| P0 | 导入一份多页 PDF 手册入库 | 没有素材，页码功能展示不出来 |
| P1 | kb_call_mode 三个分支级单测 | 锁住 never / smart / 回落行为，防无感知回归 |
| P1 | pdf_loader 失败不写 page 键 | 消除"代码写了库里没有"的静默落差 |
| P2 | DeepDoc page_number 字段统一 | 当前未产生脏数据，属预防性修复 |

一个值得留意的辩证关系：Q1 的 smart 模式与 Q3 的页码功能处于同一个成熟度带，即"后端逻辑完备但缺少面向用户的闭环验证"。这两个点的下一步都不是继续写后端，而是把消费端（测试 / 前端 / 演示素材）补齐。这也符合本项目一贯的验证纪律：功能是否完成，以端到端可见为准。
