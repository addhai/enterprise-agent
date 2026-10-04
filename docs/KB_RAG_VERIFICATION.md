# 知识库 RAG 文档导入链路 — 验证与补全报告

- 验证日期：2026-09-14
- 验证对象：`deploy/prod` 内网单容器形态（应用 + 内置 Ollama，`qwen2.5:7b` + `bge-m3`）
- 容器：`prod-app-1`（镜像 `enterprise-agent-app-ollama:latest`，由根 `Dockerfile` 的 `runtime-with-ollama` 目标构建）
- 验证脚本：`scripts/verify_knowledge_rag.py`、`scripts/verify_chat_rag_citation.py`、`scripts/kb_test_fixtures.py`
- 原始证据：`docs/KB_RAG_VERIFICATION_evidence.json`（一次完整验证运行的原始请求/响应与断言明细）

---

## 一、结论摘要

| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| `src/rag/` 下模块无语法错误、可正常 import | 通过 | 容器内 `IMPORT_OK`，加载器注册表含 12 种扩展名 |
| knowledge 接口在 `/docs` 可见 | 通过 | OpenAPI 中列出 14 条 `/api/v1/admin/knowledge*` 路由 |
| 文档上传（PDF/DOCX/TXT/MD） | 通过 | 4/4 上传成功，切片数 9 / 1 / 3 / 1 |
| 解析 → 分块 → embedding → 存入 Chroma 链路完整 | 通过 | Chroma 内 14 条向量 = 9+1+3+1，与切片数逐一对齐 |
| 知识库列表 / 删除 / 查询接口可用 | 通过 | 列表、详情、删除、批量删除、刷新、重建索引均实测 200 |
| 检索能找到已上传文档 | 通过 | hit_test 4/4 命中各素材的独有事实，每条 3 个命中 |
| 聊天回复包含知识库引用（source/citation 字段） | 契约通过（见 §6） | 图节点命中 3 条 + `_build_citations` 产出含 `source`/`doc_id`/`kb_id` 的引用 |
| 端到端 WebSocket 聊天抓取引用 | 受限，未稳定复现 | 见 §6.3，受 7B 模型单轮 4~5 分钟与传输层限制 |

自动化断言结果：**18 项检查通过 17 项**（唯一失败项为端到端 WS 抓取，原因见 §6.3）。
相关既有测试：`62 passed`（知识库/会话/WS 逻辑）、`172 passed / 7 skipped`（RAG/安全/切分）。

---

## 二、接口清单（14 个，全部已注册且 `/docs` 可见）

所有路由前缀 `/api/v1`，要求 admin / agent 角色（写操作要求 admin）。

### 知识库集合

| 方法 | 路径 | 功能 | 权限 |
| --- | --- | --- | --- |
| POST | `/admin/knowledge` | 创建知识库 | admin / agent |
| GET | `/admin/knowledge` | 列出知识库（支持 kb_type / kb_version 过滤，返回前动态刷新文档数） | admin / agent |
| GET | `/admin/knowledge/{kb_id}` | 知识库详情（顺带重算统计） | admin / agent |
| PUT | `/admin/knowledge/{kb_id}` | 更新名称/描述/相似度阈值/权重 | admin |
| DELETE | `/admin/knowledge/{kb_id}` | 删除知识库及其全部文档 **并清理向量索引** | admin |
| POST | `/admin/knowledge/{kb_id}/reindex` | 全库重建索引（真实重算，非仅改状态） | admin |

### 文档

| 方法 | 路径 | 功能 | 权限 |
| --- | --- | --- | --- |
| POST | `/admin/knowledge/{kb_id}/documents` | 添加文档（来源：document 路径 / url / text） | admin / agent |
| POST | `/admin/knowledge/{kb_id}/documents/upload` | multipart 上传文件（白名单 `.md .txt .pdf .docx .html`，上限 10MB） | admin / agent |
| GET | `/admin/knowledge/{kb_id}/documents` | 列出文档（可按 status / doc_format 过滤） | admin / agent |
| GET | `/admin/knowledge/{kb_id}/documents/{doc_id}` | 文档详情 | admin / agent |
| DELETE | `/admin/knowledge/{kb_id}/documents/{doc_id}` | 删除文档 **并清理其向量切片** | admin |
| POST | `/admin/knowledge/{kb_id}/documents/batch_delete` | 批量删除 **并逐条清理向量** | admin |
| POST | `/admin/knowledge/{kb_id}/documents/{doc_id}/refresh` | 刷新文档：清旧索引 → 重新解析切块向量化 | admin |
| POST | `/admin/knowledge/{kb_id}/hit_test` | 命中测试（在指定知识库范围内检索） | admin / agent |

---

## 三、链路现状

### 3.1 文档格式支持

加载器注册表（容器内实测输出）：

```
['.bmp', '.docx', '.gif', '.htm', '.html', '.jpeg', '.jpg', '.md', '.pdf', '.png', '.txt', '.webp']
```

上传白名单与加载器的交集为 `.md .txt .pdf .docx .html`，四种主流文档格式均可用。
图片类加载器存在（走视觉/OCR 管线，依赖 `deepdoc_enabled` 等开关），不在本次验证范围。
`.doc` / `.xlsx` / `.csv` 在类别映射表里有分类，但没有注册加载器，上传会被白名单拒绝。

### 3.2 分块策略

`src/rag/chunker.py` 的 `HybridChunker`，参数 `chunk_size=512`、`chunk_overlap=64`（`src/config.py:88-89`）。

- 主策略是**章节感知**切块：先按 Markdown 标题切节，一节一块；只有单节超过 `chunk_size` 时才对节内按段落继续切（保留 overlap）。
- 设计取舍有明确注释：对「一问一节」的技术手册，块内语义纯度比块大小更重要。
- 空标题（只有标题无正文）会被丢弃，过短小节会并入上一节。
- 切块分隔符写成正则，同时兼容 loader 转义后的 `\###` 与未转义的 `###`。

**本次修复的关键点**：知识库上传接口原先完全没有调用切块器，直接把加载器的章节文档入库。
现在统一走 `_chunk_for_retrieval()` → `HybridChunker.split_standard`，与离线批量导入脚本 `scripts/ingest_docs.py` 完全一致。

### 3.3 Embedding 模型

- Provider：OpenAI 兼容接口，指向容器内 Ollama（`OPENAI_API_BASE=http://127.0.0.1:11434/v1`）。
- 模型：`bge-m3`（`EMBEDDING_MODEL=bge-m3`），维度 1024。
- 实测：容器内直接调用 `/api/embed`，返回 `dim=1024`，耗时 2.5 秒（模型已加载后）。
- `Embedder` 对不支持 `dimensions` 参数的端点会自动降级重试，适配内网 vLLM/Ollama 场景。

### 3.4 向量存储

- 后端：Chroma（`VECTOR_STORE_BACKEND=chroma`），可选 Milvus 作为实验路径。
- 路径：`CHROMA_PERSIST_DIR=/app/chroma_data`，对应卷 `prod-agent-chroma`。
- Collection：`knowledge_base`。
- 每个切片注入 `kb_id` / `doc_id` / `tenant_id` / `source_type` 元数据，用于知识库级隔离与来源溯源。

### 3.5 检索方式

混合检索，`HybridRetriever.search_with_scores` 的处理顺序：

1. 查询改写（`REWRITE_ENABLED=true`，失败自动回退原查询）
2. 向量检索（Chroma `similarity_search_with_relevance_scores`）+ 相似度阈值过滤（`kb_similarity_threshold=0.2`）
3. BM25 关键词检索（`retrieval_vector_only=false` 时启用）
4. RRF 融合（k=60），并按知识库权重与文档权重加权
5. 句子粒度合并（**当前未启用**，见 §7）
6. 重排序（`rerank_enabled=false`，默认关闭）
7. 权限过滤（租户 + access_level）
8. 版本冲突消解 + 来源配额（`retrieval_source_cap=2`）

### 3.6 聊天是否接入 RAG

已接入，链路为：

```
WS /ws/chat → LangGraph 工作流
  ├─ agent 节点：可用工具 search_knowledge_base 主动检索
  └─ rag_node：当 retrieved_docs 为空时按原始查询补检回填
→ state["retrieved_docs"]
→ _build_citations()  → {title, content, score, source, doc_id, kb_id}
→ done 帧携带 citations 推给前端（「引用知识片段」气泡）
```

对应代码：`src/websocket/routes.py:449`（`_build_citations`）、`:699`（构建 citations）、`:768`（done 帧推送）。

---

## 四、修复清单

### 4.1 代码缺陷（11 项）

| # | 位置 | 症状 | 修法 |
| --- | --- | --- | --- |
| 1 | `src/rag/loaders/docx_loader.py:132` | 导入不存在的 `src.rag.config` → `ModuleNotFoundError`，DOCX 永远解析失败 | 改为 `from src.config import settings` |
| 2 | `src/rag/loaders/docx_loader.py` | 使用 `json.dumps` 但从未 `import json` | 补 `import json` |
| 3 | `src/rag/loaders/pdf_loader.py:98/112` | 先 `doc_handle.close()` 再 `extract_pdf_bookmarks(doc_handle)` → `get_toc()` 抛 "document closed" | 关闭动作挪进 `finally` |
| 4 | 缺 `src/rag/loaders/text_loader.py` | 上传白名单允许 `.txt`，注册表无对应加载器 → 静默产出 0 切片 | 新增 TXT 加载器并注册 |
| 5 | `src/api/knowledge.py` `_ingest_document_internal` | 上传链路不分块，整章作为一个向量 | 新增 `_chunk_for_retrieval()` 复用 `HybridChunker` |
| 6 | 同上 | 失败时伪造 `chunk_count = 42` 占位，掩盖故障 | 状态置 `failed` 并记录真实原因，切片数如实为 0 |
| 7 | `src/api/knowledge.py` 删除类接口 | 只删元数据，Chroma 向量残留 → 已删文档仍被检索（幽灵引用） | 新增 `VectorStoreManager.delete_by_where()` + `HybridRetriever.purge_index()`，删除/批量删除/删库三处接入 |
| 8 | `refresh_document` | 只重新计数，不重建向量，刷新是空操作 | 改为 清旧索引 → 重新解析切块向量化 |
| 9 | `reindex_knowledge_base` | 只把状态改成 `indexed`，不做真实重算 | 改为真实重建，单文档失败不中断并汇总返回 |
| 10 | `src/api/knowledge.py` 状态写入 | `parse_status` 列宽 `String(32)`，写入长失败原因触发 `psycopg2 StringDataRightTruncation` → 上传接口 500 | 新增 `_status_text()` 截断到 32 字符，完整原因走日志 |
| 11 | `src/websocket/session_manager.py` / `routes.py` | 会话过期清理按 `last_active` 判定，长推理期间不刷新 → 请求处理中会话被清掉，历史丢失 | 新增 `in_flight` 计数，清理跳过处理中的会话 |
| 12 | `src/websocket/routes.py` `_handle_ai_chat` | 图执行期间不推任何帧，长推理时客户端连接被判定空闲而断开（`ClientDisconnected`，回复与引用全部丢失） | 改为后台跑图 + 每 20 秒推送一次「思考中」心跳 |

### 4.2 部署缺陷（8 项）

| # | 位置 | 症状 | 修法 |
| --- | --- | --- | --- |
| A | `deploy/prod/docker-compose.prod.yml` | app 服务只有 `image:` 没有 `build:`，`up -d --build` 的 `--build` 静默失效 | 补 `build:` 段并指定 `target` |
| B | 同上 | 宿主机代理被注入构建容器，pip 连不上 → `No matching distribution found` | build.args 中把四个 proxy 变量默认置空，可用 `BUILD_HTTP_PROXY` 覆盖 |
| C | 根 `Dockerfile` | **仓库里没有任何 Dockerfile 会安装 ollama**，而 compose 直接执行 `ollama serve`；照文档重建会得到没有 ollama 的镜像 | 拆成 `runtime-base` + `runtime-with-ollama`（从 `ollama/ollama:latest` 取） + `runtime`（默认） |
| D | 同上 | 只拷 `*.so*` 时缺 `llama-server`：ollama 能启动能列模型，一推理就报 `llama-server binary not found` | 一并拷 `llama-server` / `llama-quantize` |
| E | compose 卷挂载 | 模型卷挂在 `/root/.ollama`，容器以 uid 10001 运行读不到 | 改挂 `/home/appuser/.ollama`，沿用 `$HOME/.ollama/models` 默认约定 |
| F | 数据卷属主 | 历史卷内文件是 root 所有（旧镜像以 root 运行写入），非 root 容器报 `attempt to write a readonly database` | `chown -R 10001:10001`（全新部署不会遇到） |
| G | `requirements-runtime.txt` | 刻意排除 `pymupdf / python-docx / beautifulsoup4`，理由是「入库在构建前离线完成」——与「上传接口运行时接受 PDF/DOCX」矛盾 | 纳入三个解析器并如实改写注释 |
| H | compose 启动命令 | 只 `sleep 5` 就起 uvicorn，ollama 冷启动未就绪时上传请求因 embedding Connection refused 直接失败 | 增加 ollama 就绪探测（`timeout 180` 兜底） |

---

## 五、实测记录

### 5.1 构建与启动

```bash
docker compose -f deploy/prod/docker-compose.prod.yml \
  --env-file deploy/prod/.env.production up -d --build
```

修复前的关键输出（`--build` 空转，没有重建任何镜像）：

```
 Container prod-app-1 Running    ← 注意不是 Recreated
```

修复后的关键输出：

```
 Image enterprise-agent-app-ollama:latest Built
 Container prod-app-1 Recreated
 Container prod-app-1 Started
```

### 5.2 Ollama 与解析器就绪

```bash
docker exec prod-app-1 /usr/bin/ollama list
```

```
NAME             ID              SIZE      MODIFIED
qwen2.5:7b       845dbda0ea48    4.7 GB    3 days ago
bge-m3:latest    790764642607    1.2 GB    3 days ago
```

```bash
docker exec prod-app-1 python -c "import fitz, docx, bs4; print('parsers OK')"
```

```
parsers OK
```

### 5.3 上传与入库（关键片段）

请求：

```bash
curl -X POST "http://localhost:8000/api/v1/admin/knowledge/{kb_id}/documents/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@fixtures/kb_test/kb_docx_upgrade.docx"
```

响应（修复后）：

```json
{
  "success": true,
  "document": {
    "id": "KB-D40013",
    "title": "kb_docx_upgrade.docx",
    "doc_format": "docx",
    "status": "indexed",
    "parse_status": "completed",
    "chunk_count": 3,
    "file_size": 37081
  },
  "warning": null
}
```

四种格式的入库结果：

| 素材 | 格式 | 状态 | 切片数 | 文件大小 |
| --- | --- | --- | --- | --- |
| `kb_md_manual.md` | md | indexed | 9 | 917 B |
| `kb_txt_note.txt` | txt | indexed | 1 | 757 B |
| `kb_docx_upgrade.docx` | docx | indexed | 3 | 37081 B |
| `kb_pdf_safety.pdf` | pdf | indexed | 1 | 3684 B |

修复前对照（同一套素材、旧镜像）：TXT **0 切片**（无加载器），DOCX / PDF 均报 **42 切片**（异常被吞后的伪造占位值），Chroma 内实际只有 MD 的 5 条向量。

### 5.4 容器内 Chroma 向量核对

```bash
docker exec prod-app-1 python -c "
import sqlite3
c = sqlite3.connect('/app/chroma_data/chroma.sqlite3')
print('embeddings =', c.execute('select count(*) from embeddings').fetchone()[0])
print('collections =', c.execute('select name from collections').fetchall())
"
```

```
embeddings = 14
collections = [('3a4680af-...', 'knowledge_base')]
```

14 = 9(md) + 1(txt) + 3(docx) + 1(pdf)，与上传响应的切片数逐一对应。
每个切片的元数据键包含 `kb_id` / `doc_id` / `tenant_id` / `source_type` / `source` / `chapter_path` 等 20 个字段。

### 5.5 命中测试

请求：

```bash
curl -X POST "http://localhost:8000/api/v1/admin/knowledge/{kb_id}/hit_test" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"query": "XG-9000 的腔体预热温度是多少摄氏度，需要预热多久？", "top_k": 5}'
```

响应（节选）：

```json
{
  "kb_id": "KBS-058984",
  "total_hits": 3,
  "hits": [
    {
      "content": "## 1. 腔体预热规程\nXG-9000 型真空镀膜机的腔体预热温度为 187 摄氏度，预热时长为 43 分钟。...",
      "score": 1.0,
      "source": "kb_md_manual.md",
      "metadata": {
        "kb_id": "KBS-058984",
        "doc_id": "KB-...",
        "chapter_path": "XG-9000 真空镀膜机 运维手册(测试用) / 1. 腔体预热规程"
      }
    }
  ]
}
```

四种格式的命中判定（每份素材埋一个**只在该素材中出现的独有事实**，模型不可能凭空知道）：

| 素材 | 判定关键词 | 命中 | 返回条数 |
| --- | --- | --- | --- |
| `kb_md_manual.md` | 187（腔体预热温度） | 是 | 3 |
| `kb_txt_note.txt` | XO-2026-0912（交接编号） | 是 | 3 |
| `kb_docx_upgrade.docx` | 192（V3 固件预热温度） | 是 | 3 |
| `kb_pdf_safety.pdf` | 74（外壁最高温度） | 是 | 3 |

### 5.6 删除时的向量清理

```bash
DELETE /api/v1/admin/knowledge/KBS-058984
```

```json
{
  "success": true,
  "message": "知识库 KBS-058984 已删除，共删除 4 个文档",
  "vectors_removed": 14
}
```

删除后容器内 `embeddings` 归 0，确认幽灵引用已消除。

---

## 六、聊天引用验证

### 6.1 图节点确实检索了知识库

服务端日志（实测）：

```
2026-09-14 13:13:54 [INFO] src.graph.nodes: rag_node 引用补检：tenant=default 命中 3 条
```

即：聊天工作流在 `rag_node` 里按原始查询对已上传的知识库做了检索，拿到 3 条切片并回填到 `state["retrieved_docs"]`。
这条日志本身就是「聊天接口在回复时检索知识库」的直接证据。

### 6.2 引用对象的字段契约

容器内以同一问题直接调用检索并走引用构建函数：

```bash
docker exec prod-app-1 python -c "
from src.api.dependencies import get_retriever
from src.websocket.routes import _build_citations
docs = get_retriever().search('XG-9000 的腔体预热温度是多少摄氏度，需要预热多久？',
                              top_k=3, tenant_id='default',
                              user_access_levels=['public','internal','confidential','restricted'])
print(_build_citations(docs))
"
```

输出（节选）：

```json
[
  {
    "title": "kb_md_manual.md",
    "content": "## 1. 腔体预热规程\nXG-9000 型真空镀膜机的腔体预热温度为 187 摄氏度，预热时长为 43 分钟。...",
    "score": 0.0,
    "source": "kb_md_manual.md",
    "doc_id": "KB-BA7102",
    "kb_id": "KBS-3BF371"
  },
  {
    "title": "kb_docx_upgrade.docx",
    "content": "XG-9000 型真空镀膜机在 V3 固件后的腔体预热温度调整为 192 摄氏度，预热时长为 47 分钟。...",
    "source": "kb_docx_upgrade.docx",
    "doc_id": "KB-1E9024",
    "kb_id": "KBS-3BF371"
  }
]
```

即验收要求的 `source` / `citation` 字段齐备：`title`、`content`、`score`、`source`、`doc_id`、`kb_id`。
这批对象就是 WS `done` 帧里 `citations` 字段的原样内容。

### 6.3 端到端 WebSocket 抓取：受限原因

`scripts/verify_knowledge_rag.py --ws-limit 1 --ws-timeout 600` 在本环境下**未稳定抓到 done 帧**，原因经排查有三层，且都不是 RAG 链路本身的问题：

1. **7B 模型在 CPU 上太慢**。单次 LLM 调用的 prompt 约 2050 token，ollama 实测 `15.46 tokens per second`，prompt 处理阶段就要 130 秒以上；整张图含多轮 ReAct，单轮问答耗时 **4~5 分钟**。
2. **客户端必须在整个推理期间保持连接**。脚本化客户端在等待期间收不到任何业务帧，容易被中间层或客户端自身判定为空闲而断开。服务端日志可见 `uvicorn.protocols.utils.ClientDisconnected`，发生在图刚跑完、正要推送回复的时刻。
3. **模型经常先调无关工具**。该问题（「腔体预热温度是多少」）属于纯手册查询，但 7B 模型多次调用了 `ticket_create`（日志可见 `MCP ticket_create: id=TKT-...`）以及云资源查询工具，进一步拉长总耗时。这也是 `rag_node 引用补检` 存在的意义：即使 agent 没走知识库工具，引用也由代码层补上。

已针对第 2 点做了修复（每 20 秒推一次心跳帧），修复后服务端不再在图执行期间静默，但「客户端全程挂住 5 分钟」在这套 CPU 部署上仍难以在脚本里稳定复现，故本报告以 §6.1 + §6.2 的证据链替代端到端抓帧，并把这一限制如实标注。

**未完成项**：`scripts/verify_chat_rag_citation.py`（服务端直接跑图、打印 done 帧将携带的 citations）
已写好并按正确初始状态调用工作流，但在本机 CPU 环境下运行 **24 分钟仍未跑完**（单次 LLM 调用
prompt 2050 token、15 tok/s，整图多轮 ReAct），已中止，未取得该脚本的完成态输出。
因此 §6.1 + §6.2 的证据链是本项验收的依据。

### 6.4 验证后的留存状态

容器 `prod-app-1` 健康；知识库 `KBS-FA45FD`（RAG验证库-0914-212302）保留 4 个文档 / 14 个切片，
可直接用 `hit_test` 复现检索结果。不需要时按 §二 的删除接口清掉即可（会一并清理向量）。

> 各次运行的 KB ID 不同，本报告正文中出现的 `KBS-058984` / `KBS-B82D28` 等均为当次运行的记录值。

---

## 七、已知限制与未完成项

1. **句子级索引未接入在线检索**。`HybridRetriever.__init__` 只在显式传入 `collection_name` 时才创建 `sentence_store`，而 API 侧 `get_retriever()` 未传该参数，因此句子粒度检索恒为空；而 `scripts/ingest_docs.py` 会写一个 `${collection}_sentences` 集合，两边不一致。属既有设计遗留，改动会影响检索行为，未在本次范围内变更。
2. **重排序默认关闭**（`rerank_enabled=false`）。内网无 `gte-rerank` 服务，启用需 `rerank_provider=local_bge` 并准备本地模型。
3. **`.doc` / `.xlsx` / `.csv` 无加载器**，上传会被白名单拒绝（行为正确，不属缺陷，但文档里若宣称支持需修正）。
4. **WS 客户端断开后，服务端图调用不会被取消**。实测：多次中断的测试残留了后台图调用，导致无用户时仍持续调用 LLM（重启后归零）。内网 CPU 机器上这是真实的资源占用，建议后续在断开时取消任务或给图加总时长上限。
5. **`parse_status` 列宽仅 32 字符**，失败原因只能存摘要，完整原因需看日志。若要完整留存，需扩列。

---

## 八、复现步骤

```bash
# 0. 拉取依赖（宿主侧脚本需要 requests / websocket-client）
#    沙箱 Bash 的 PATH 可能缺 coreutils，先补：
export PATH="/usr/bin:/bin:$PATH"

# 1. 生成测试素材（DOCX 在宿主生成）
python scripts/kb_test_fixtures.py docx

# 2. 生成含中文的 PDF（容器内有 PyMuPDF 与内置 CJK 字体）
docker cp scripts/kb_test_fixtures.py prod-app-1:/tmp/kb_test_fixtures.py
docker exec -e KB_FIXTURE_DIR=/tmp/kbfix prod-app-1 python /tmp/kb_test_fixtures.py pdf
docker cp prod-app-1:/tmp/kbfix/kb_pdf_safety.pdf fixtures/kb_test/kb_pdf_safety.pdf

# 3. 构建并启动（即任务单里的命令，修复后 --build 才真正生效）
docker compose -f deploy/prod/docker-compose.prod.yml \
  --env-file deploy/prod/.env.production up -d --build

# 4. 等待健康检查通过
curl -s http://localhost:8000/api/v1/health

# 5. 全链路验证（API + 向量库 + 聊天）
python scripts/verify_knowledge_rag.py \
  --container prod-app-1 --ws-limit 1 --ws-timeout 600 \
  --report C:/tmp/kb_final.json

# 6. （可选）服务端直接跑图，验证 done 帧将携带的 citations
docker cp scripts/verify_chat_rag_citation.py prod-app-1:/tmp/
docker exec -e PYTHONPATH=/app prod-app-1 \
  python /tmp/verify_chat_rag_citation.py --expect 187
```

> 注意：Windows 上 Git Bash 的 `/tmp` 与 Windows 路径不一致。脚本里的 `--report /tmp/xxx.json`
> 实际写到 `C:\tmp\xxx.json`，用 `ls /tmp` 找不到，需用 `C:/tmp/...` 访问。

---

## 九、本次改动文件清单

**代码**

- `src/rag/loaders/docx_loader.py`（导入修正 + `json` 导入）
- `src/rag/loaders/pdf_loader.py`（句柄生命周期）
- `src/rag/loaders/text_loader.py`（**新增** TXT 加载器）
- `src/rag/loader.py`（注册 TXT 加载器）
- `src/rag/vector_store.py`（新增 `delete_by_where`）
- `src/rag/retriever.py`（新增 `purge_index`）
- `src/api/knowledge.py`（切块入库、真实状态、向量清理、状态截断、重建索引）
- `src/websocket/session_manager.py`（`in_flight` 计数）
- `src/websocket/routes.py`（处理中计数、推理期间心跳）

**部署**

- `Dockerfile`（拆 stage，新增 `runtime-with-ollama`）
- `deploy/prod/docker-compose.prod.yml`（build 段与 target、代理参数、模型卷路径、就绪门禁）
- `requirements-runtime.txt`（纳入 PDF/DOCX/HTML 解析器）

**脚本与素材**

- `scripts/verify_knowledge_rag.py`（**新增**端到端验证）
- `scripts/verify_chat_rag_citation.py`（**新增**引用契约验证）
- `scripts/kb_test_fixtures.py`（**新增**素材生成）
- `fixtures/kb_test/`（4 份测试素材）
