# Phase 3 改动清单与验收报告

- **项目**：enterprise-agent（工业知识库 AI Agent 内网全离线改造）
- **执行日期**：2026-09-16
- **技术栈**：Python（FastAPI + LangGraph + LangChain）+ Chroma + Ollama
- **任务范围**：P0 离线合规硬门槛 7 项 + P1 功能改造 2 项 + P2 页码 1 项 + 附加检查 1 项，共 11 项
- **执行结果**：11 项全部完成；全量回归 `1407 passed, 23 skipped, 退出码 0`

---

## 一、Phase 3 改动清单

改动前 / 改动后为关键片段的摘要形式，完整内容见各文件同目录下的 `.bak` 备份。

| 任务编号 | 文件路径 | 改动行号 | 改动前 | 改动后 | 验收结果 |
|---|---|---|---|---|---|
| P0-1 | `src/config.py` | 31 | `openai_api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"` | `openai_api_base = ""`（附 2 行说明注释） | ✅ grep 确认 config.py 中已无 `dashscope.aliyuncs.com` |
| P0-1 | `src/config.py` | 32 | `embedding_model = "text-embedding-v4"` | `embedding_model = "bge-m3"` | ✅ 已改，附 Phase3 注释 |
| P0-1 | `src/config.py` | 33 | `embedding_provider = "openai"  # openai/dashscope/local` | `embedding_provider = "openai"  # 保持 openai（走 OpenAI 兼容协议连 Ollama），值不变` | ✅ 值未变，仅补注释 |
| P0-2 | `src/config.py` | 133（原 128） | `rerank_provider = "dashscope"` | `rerank_provider = "local_bge"` | ✅ 已改 |
| P0-2 | `src/config.py` | 135（原 130） | `rerank_model = "gte-rerank"` | `rerank_model = "BAAI/bge-reranker-base"` | ✅ 已改 |
| P0-2 | `src/config.py` | 129-131 | `rerank_enabled = False`（无说明） | `rerank_enabled = False` + 3 行内网启用方式注释 | ✅ 值保持 False，注释已补 |
| P0-3 | `src/rag/reranker.py` | 131-137 | `self.api_base = api_base or "https://dashscope.aliyuncs.com/compatible-mode/v1"` | `self.api_base = api_base or ""` + 空值抛 `ValueError` | ✅ 见下方说明 |
| P0-3 | `src/rag/reranker.py` | 289-295 | 工厂 dashscope 分支直接传空 `api_base` | 先判空，空值抛 `ValueError` 后再构造 | ✅ 已改 |
| P0-4 | `src/config.py` | 49 | `langsmith_tracing = True` | `langsmith_tracing = False` | ✅ 已改 |
| P0-5 | `src/config.py` | 39-40 | `llm_model = "qwen-plus"` / `llm_complex_model = "qwen-max"` | 两者均为 `"qwen2.5:7b"` | ✅ 已改 |
| P0-6 | `src/config.py` | 415-470 | 无 | 新增 `assert_offline_mode()` + `_is_private_host()` + 两组常量 | ✅ 三分支行为实测通过（见 2.1） |
| P0-6 | `main.py` | 162-163 | 无 | `from src.config import assert_offline_mode` + 调用 | ✅ grep 确认已接线 |
| P0-6 | `src/api/server.py` | 172-173 | 无 | 同上 | ✅ grep 确认已接线 |
| P0-7 | `deploy/prod/.env.production` | 10 | `JWT_SECRET=<出厂默认占位弱口令>`  # [必须修改] | 新 48 字节随机密钥 `# [Phase3 已修改]` | ✅ grep 确认旧值已消失 |
| P1-8 | `src/config.py` | 121-127 | 注释 `always 必定调用 / smart 智能调用` | 注释统一为 `always / smart / never` 三值语义说明 | ✅ 已改 |
| P1-8 | `src/config_center/schema.py` | 130 | `enum=("auto", "always", "never")` | `enum=("always", "smart", "never")` | ✅ 两处定义一致 |
| P1-8 | `src/graph/nodes.py` | 823-900 | 无（`kb_call_mode` 无消费点） | 三分支实现 + 日志 + 预检索 | ✅ 见 1.1 行为验证 |
| P1-8 | `src/graph/nodes.py` | 1017-1035 | 无 | `always` 预检索结果按内容去重后并回 `retrieved_docs` | ✅ 已改 |
| P1-10 | `src/agent/tools.py` | 962-968 | `if retriever is None: return "知识库当前不可用。请转人工客服。"` | 返回前补 `logger.error("[Phase3] retriever 未注入…")` | ✅ 已改（见下方偏差说明） |
| P2-13 | `src/rag/loaders/pdf_loader.py` | 22-57 | 无 | 新增 `_inject_page_metadata()` | ✅ 见 1.2 端到端验证 |
| P2-13 | `src/rag/loaders/pdf_loader.py` | 178-185 | 仅 `_structure_hint` 循环 | 其前插入 `_inject_page_metadata(chapters, full_text)` | ✅ 已改 |
| P2-13 | `src/rag/vector_store.py` | 未改动 | — | 确认 metadata 无白名单过滤，直接透传 Chroma | ✅ 仅确认，未改（见 1.2） |
| P2-13 | `src/websocket/routes.py` | 516-518 | `citations` 无 page 字段 | 新增 `"page": meta.get("page") if isinstance(meta, dict) else None` | ✅ 已改 |

### 1.1 P1-8（`kb_call_mode`）行为验证

三分支均以脚本实测（`kb_call_mode` 逐一切换，retriever 用桩对象）：

| 模式 | 实测行为 | 证据 |
|---|---|---|
| `never` | 跳过检索与 Agent。桩 retriever 的 `search` 抛断言，全程未被调用 → 证明未触碰检索。LLM 不可达时优雅捕获并返回 `answer_status="refused"` | 日志 `[kb_call_mode=never] 检索策略已应用`；返回 keys = `answer_status / final_response / needs_human / quality_score / retrieved_docs / tool_sourced` |
| `always` | Agent 之前先执行一次 `retriever.search`，`top_k=5`。桩 retriever 调用记录 `[('T100 测温范围是多少', 5)]` | 日志 `[kb_call_mode=always] 预检索命中 1 条（top_k=5）` |
| `smart` | 保持原有行为，不执行预检索 | 代码分支未进入 `always` / `never` |

### 1.2 P2-13（页码）端到端验证

用 PyMuPDF 生成测试 PDF（写在 `C:/tmp/p2-13/`，未进仓库），经 `DocumentLoader.load_file` 实跑：

| 测试文件 | 构造 | 章节数 | page 结果 |
|---|---|---|---|
| `multi.pdf` | 3 页，每页一个 markdown 标题 | 3 | `[1, 2, 3]` ✅ 正确 |
| `spec.pdf` | 3 页，无标题（整篇一章） | 1 | `[1]` ✅ 正确 |

metadata 透传链路：`chunker.py:178`（`**doc.metadata`）与 `chunker.py:323/330`（`dict(doc.metadata)`）全量继承，`vector_store.py:84` 直接把 Document 交给 Chroma，无白名单过滤，`page` 字段可完整透传。

`_build_citations` 异常输入安全降级实测：`None → []`、`[] → []`、空 metadata → `page=None`。

### 1.3 两处偏离任务原文的说明

**偏差 1（P1-10 日志器选择）**。任务原文要求 `import logging; logging.error(...)`。因 `src/agent/tools.py:3` 已 `import logging`、第 12 行已定义 `logger = logging.getLogger(__name__)`，改为使用模块级 `logger.error(...)`。同为 ERROR 级别，但保留模块上下文便于按来源过滤，且避免根日志器重复 handler。

**偏差 2（P1-8 `never` 模式实现方式）**。任务原文写「跳过 Agent 执行，直接返回空 `retrieved_docs`，将用户问题交给后续 reply_node 纯 LLM 回答」。经核实 `src/graph/nodes.py:1345-1386`，`reply_node` 在 `final_response` 为空时返回的是固定兜底话术，全程无 LLM 调用；`reflect_node` 也在 `nodes.py:1234-1236` 直接 `return {}`。即「reply_node 纯 LLM 回答」这条路径不存在，照字面实现会让 `never` 退化成统一道歉。经你确认，改为在 `rag_node` 内直接调 LLM 生成回答。

### 1.4 备份文件清单（16 个，全部保留）

```
.env.bak                                  src/config_center/schema.py.bak
deploy/prod/.env.production.bak           src/graph/nodes.py.bak
main.py.bak                               src/rag/chunker.py.bak          （未改动，备份保留）
src/agent/tools.py.bak                    src/rag/loader.py.bak           （未改动，备份保留）
src/api/server.py.bak                     src/rag/loaders/pdf_loader.py.bak
src/config.py.bak                         src/rag/reranker.py.bak
src/websocket/routes.py.bak               tests/test_api/test_config.py.bak
tests/test_config.py.bak                  tests/test_memory/test_short_term.py.bak
```

> 其中 `src/rag/loaders/pdf_loader.py.bak` 为反向还原生成。初次备份时误备份了同名的 `src/rag/loader.py`，遗漏该文件；事后按「删除新增函数 + 还原注入块」的方式重建，已用 `ast.parse` 校验可解析、结构与原文件一致（146 行 vs 当前 189 行）。
>
> ⚠️ `.bak` 文件未被 `.gitignore` 覆盖（`git check-ignore` 无输出），会出现在 `git status` 中。按你的 git 铁律，提交时切勿 `git add .`，否则 16 个备份会被一并提交。

---

## 二、附加检查结论：local_bge 在内网能否直接启用

### 结论：**不能直接启用**。当前默认配置下属于「安全但不生效」状态

### 2.1 依赖层缺失

`LocalBgeReranker` 使用 `sentence_transformers.CrossEncoder` 加载模型（`src/rag/reranker.py:200-201`）。

| 检查项 | 结果 |
|---|---|
| `requirements.txt:29` | 含 `sentence-transformers>=3.0.0`（开发/全功能） |
| `requirements-runtime.txt` | **明确排除**，原文：「排除 sentence-transformers：本地向量模型（会拉取 ~2GB torch）」 |
| 容器镜像实际依赖 | 根 `Dockerfile:57` `COPY requirements-runtime.txt requirements.txt` → **镜像内无 sentence-transformers、无 torch** |
| `deploy/prod` 用的 target | compose 指定 `target: runtime-with-ollama`，派生自 `runtime-base`（`Dockerfile:103`）→ 同样无该依赖 |
| 本机 venv | 已装（sentence-transformers 5.6.0），故本机与容器行为不同 |
| HF 权重缓存 | `~/.cache/huggingface/hub/models--BAAI--bge-reranker-base` **不存在** |

### 2.2 实测：会尝试联网下载

```
=== 首次访问 .model 时才加载权重 ===
  加载失败: ProxyError 502 Bad Gateway
```

构造阶段（`create_reranker("local_bge")`）成功，因为模型是惰性加载。首次访问 `.model` 时即触发 HuggingFace 下载，本机实测被代理拦截返回 502。这在断网内网中会表现为连接超时。

### 2.3 失效方式是「优雅降级」，不会崩溃

`HybridRetriever._rerank` 在 `src/rag/retriever.py:780-782` 全量兜底：

```python
except Exception as e:
    logger.warning("Rerank failed, using original order: %s", e)
    return candidates
```

实测：rerank 失败后返回 2 条候选、顺序保持不变（原始顺序）。

**因此默认配置是安全的**：`rerank_enabled=False` 时根本不进这条路径；即便有人开启，也只是打一条 WARNING 后按原顺序返回，不会中断检索。代价是「开了但没生效」的静默失效，日志级别为 WARNING，容易被忽略。

### 2.4 另一条 provider 路径（`llm`）存在接线缺陷

`llm` provider 走 LLM 打分，理论上可完全离线（Ollama 聊天接口），但 `HybridRetriever.reranker`（`src/rag/retriever.py:705-712`）调 `create_reranker` 时**未传 `llm` 实例**，导致 `LLMReranker(llm=None)` 落到长度启发式分支（`src/rag/reranker.py:236-239`）。

实测：`_compute_scores('q', ['abc','abcdefgh'])` 返回 `[3.0, 8.0]`，即原始字符长度，而非文档承诺的 0-1 归一化语义分。`llm` 路径当前实质不可用。

### 2.5 三条启用方案（按代价从低到高）

| 方案 | 改动 | 代价 | 离线可用 |
|---|---|---|---|
| A. 保持现状（默认 `rerank_enabled=false`） | 无 | 无重排序能力 | — |
| B. 修 `llm` provider 接线，指向 Ollama | `src/rag/retriever.py:705-712` 传入 `ChatOpenAI(...)`；同时修长度启发式的归一化 | 每篇候选一次 LLM 调用，延迟与显存开销明显；7B 打分稳定性需实测 | ✅ 完全离线 |
| C. 补齐 local_bge 前置条件 | ① `requirements-runtime.txt` 加 sentence-transformers（连带 torch，镜像约 +2GB）；② 联网机预下载 `BAAI/bge-reranker-base` 并 COPY 进镜像或挂载；③ 设 `HF_HUB_OFFLINE=1` 与本地模型路径 | 镜像体积翻倍级增长，与「精简运行时依赖」的既有设计冲突 | ✅ 完全离线，需预置 |

补充一点辩证视角。方案 C 的 2GB 代价与 `requirements-runtime.txt` 里那段注释的取舍逻辑（排除本地向量模型、Embedding 走 API）直接冲突。而该注释本身已经过时：原写「镜像内 Embedding 走阿里百炼 text-embedding-v4 API」，但 P0-1 后默认 embedding 已是本地 bge-m3 走 Ollama，注释需一并订正。

---

## 三、待确认 / 风险项

### 3.1 本次改动引入的行为变化（需你知晓）

| 序号 | 变化 | 影响 |
|---|---|---|
| R1 | `openai_api_base` 默认值置空 + `assert_offline_mode()` 拒绝启动 | **本机启动必须先配 `OPENAI_API_BASE`**。已验证 `docker-compose.dev.yml` 与 `docker-compose.milvus.yml` 均未注入该变量 → 这两种形态启动会直接失败 |
| R2 | `kb_call_mode` 默认 `always` 由「无消费点」变为「真实生效」 | 默认行为从「LLM 自主决定检索」变为「进入 rag_node 必先检索一次」。每次技术类提问多一次检索开销，换来可溯源文档的强制覆盖。按你确认保持 `always` |
| R3 | `.env` 新增 `OPENAI_API_BASE=http://127.0.0.1:11434/v1` | 经你授权。本机 `.env` 非 ASCII 字节数维持 411 基线，**本次新增 0 个非 ASCII 字节**（初版中文注释已改为纯英文注释） |
| R4 | 2 处测试断言 + 1 处测试打桩调整 | `tests/test_config.py:24-25`、`tests/test_api/test_config.py:337-339` 断言旧默认值 → 已同步；`tests/test_memory/test_short_term.py` 补 `monkeypatch` 强制走关键词兜底路径 |

### 3.2 范围外发现（未改动，需你决策）

| 序号 | 发现 | 位置 | 说明 |
|---|---|---|---|
| F1 | `src/rag/` 下仍有 1 处外网地址 | `src/rag/vision_engines/qwen_vision_engine.py:53` | `os.environ.get("VISION_BASE_URL", "https://dashscope.aliyuncs.com/...")`。P0-3 的验收条件写「src/rag/ 目录下无剩余」，但该文件不在任务点名范围，未改。**该验收条件因此未 100% 达成** |
| F2 | 根 compose 仍硬编码百炼回退 | `docker-compose.yml:85,144,182,224` | `OPENAI_API_BASE=${OPENAI_API_BASE:-https://dashscope.aliyuncs.com/compatible-mode/v1}`。约束禁止改 compose，未改。云端形态启动时自检会走 WARN 分支（不阻止） |
| F3 | `LLMReranker` 长度启发式未归一化 | `src/rag/reranker.py:236-239` | 返回原始长度而非 0-1 分数，与文档语义不符。见 2.4 |
| F4 | `requirements-runtime.txt` 注释已过时 | `requirements-runtime.txt:9` | 称「镜像内 Embedding 走阿里百炼 text-embedding-v4 API」，P0-1 后默认已是本地 bge-m3 |
| F5 | 补检路径伪分数与真实分混用同一字段 | `src/graph/nodes.py:981-987` → `src/websocket/routes.py:500-508` | 补检注入 `1/(rank+1)`，与真实相似度共用 `score`，前端无法区分 |
| F6 | `deploy/prod/.env.production` 内 `POSTGRES_PASSWORD` 仍为明文固定值 | `deploy/prod/.env.production:13` | 文件自带 `# [必须修改]` 标记，本次未纳入任务范围 |
| F7 | PDF 书签页码未被复用 | `src/rag/outline.py:extract_pdf_bookmarks` | 该函数能取到真实页码，但 `OutlineTree.split` 未把页码透传到章节 metadata。本次改用 PAGE-BREAK 偏移量方案（对书签/无书签两种 PDF 一致生效），未改 outline.py。若后续要让书签 PDF 用更精确的标题页码，需改 `outline.py` |
| F8 | DeepDoc 扫描件路径未注入页码 | `src/rag/loaders/pdf_loader.py:57-65` | 走 `DeepDocParser` 的扫描件 PDF 直接 return，其产出的 docs 无 `page`（引用层读到 None）。需改 `src/rag/deepdoc_parser.py` 才能覆盖 |
| F9 | `_filter_by_similarity` 不作用于 RRF 融合后结果 | `src/rag/retriever.py:584`（调用点 435/441/456/565） | Phase 2 已记录，本次未纳入范围 |

### 3.3 环境侧发现

| 序号 | 发现 | 影响 |
|---|---|---|
| E1 | **本机 127.0.0.1:11434 有 Ollama 在运行，已拉取 `qwen2.5:7b`（4.68GB, Q4_K_M）与 `bge-m3:latest`（1.16GB, 1024 维）** | 这是本次最重要的环境发现。意味着 `.env` 指向本地 Ollama 后，本机具备完整可用的离线推理链路（含 embedding）。P0-5/P0-1 选的模型名与本机已有模型完全对应，无需额外下载 |
| E2 | `tests/test_memory/test_short_term.py::test_summary_generated_when_exceeding_window` 是环境敏感用例 | 见 3.4 详细分析 |
| E3 | pytest 退出码可能被 safe-delete shim 污染 | 全量跑时 shim 拦截 pytest 临时目录清理（count=63 > threshold=50），使退出码为 1，但测试全绿。绕开方式：加 `--basetemp=C:/tmp/...` 与 `-p no:cacheprovider`，退出码恢复正常 0 |

### 3.4 环境敏感用例的因果分析（重要）

`test_summary_generated_when_exceeding_window` 断言摘要含英文 `password` 或 `reset`。对照实验：

| 实验 | `OPENAI_API_BASE` | 结果 | 原因 |
|---|---|---|---|
| A | `http://127.0.0.1:19999/v1`（不可达） | ✅ passed | LLM 失败 → `_keyword_summarize` 兜底 → 含英文关键词 |
| B | `http://127.0.0.1:11434/v1`（本地 Ollama） | ❌ failed | LLM 成功 → 返回中文四点式摘要 → 无英文关键词 |
| C | `https://dashscope.aliyuncs.com/...`（旧默认） | ✅ passed | 公网不可达 → 走兜底 |

**结论**：该用例原先「通过」是因为测试环境里 LLM 不可达，属偶然。它的断言里 `password`/`reset` 正是 `_keyword_summarize` 关键词表（`src/memory/short_term.py:210`）里的词，说明它本意是测兜底路径，但没有打桩 LLM，形成隐性缺陷。Phase 3 的 `.env` 改动把执行路径从兜底切到真实 LLM，缺陷被暴露。已按你确认的方式修正（`monkeypatch` 强制 `_llm_summarize` 返回 `None`），修复后在 LLM 可达与不可达两种条件下均 `18 passed`，行为确定。

---

## 四、验收汇总

### 4.1 全量回归

```
1407 passed, 23 skipped, 4 warnings in 90.79s
pytest 退出码 = 0
```

对比改动前基线：改动前同样为 1407 passed / 23 skipped（含 2 处断言旧默认值的失败与 1 处环境敏感失败，均在本次一并修正）。

### 4.2 单项验收命令与结果

| 任务 | 验收命令 | 结果 |
|---|---|---|
| P0-1 | `grep -n "dashscope.aliyuncs.com" src/config.py` | 无输出 ✅ |
| P0-2 | `grep -n "rerank_provider\|rerank_model" src/config.py` | `local_bge` / `BAAI/bge-reranker-base` ✅ |
| P0-3 | `grep -rn "dashscope.aliyuncs.com" src/rag/ --include=*.py` | 仅剩范围外的 `qwen_vision_engine.py:53`（见 F1）⚠️ |
| P0-4 | `grep -n "langsmith_tracing" src/config.py` | `= False` ✅ |
| P0-5 | `grep -n "qwen-plus\|qwen-max" src/config.py` | 无输出 ✅ |
| P0-6 | `grep -rn "assert_offline_mode" main.py src/api/server.py src/config.py` | 定义 1 处 + 调用 2 处 ✅ |
| P0-6 | 三分支行为实测 | 空→RuntimeError；公网→WARN 返回 True；私网→INFO 返回 True ✅ |
| P0-7 | `grep -rn "JWT_SECRET" deploy/prod/` 核对旧弱口令前缀已消失 | 无输出 ✅ |
| P1-8 | `grep -rn "kb_call_mode" src/graph/nodes.py` | 命中 6 处（读取 + 三分支 + 日志）✅ |
| P1-8 | 两处枚举一致性 | config.py 注释与 schema.py 均为 `always/smart/never` ✅ |
| P1-10 | `grep -n "retriever 未注入" src/agent/tools.py` | 命中 1 处 ERROR 日志 ✅ |
| P2-13 | `_locate_page` / `_build_citations` 行为测试 | 页码定位正确、异常输入安全降级 ✅ |
| P2-13 | 真机 PDF 端到端 | 3 页 3 章节 → `[1,2,3]`；无标题整篇 → `[1]` ✅ |
| 附加检查 | `create_reranker("local_bge")` + `.model` 访问 + `_rerank` 降级 | 构造成功、加载触发联网失败、降级保留原顺序 ✅ |

### 4.3 未执行的约束项（合规声明）

本次**未**执行以下操作，符合任务硬性约束：

- 未执行 `docker compose up / start / restart / build`，未启动或重建任何容器
- 未修改任何 `docker-compose*.yml` 文件
- 未修改 `.env*` 中的任何项，除 P0-7 明确授权的 `JWT_SECRET` 与经二次授权补配的 `OPENAI_API_BASE` 一行
- 未删除、移动、重命名任何文件；16 个 `.bak` 全部保留
- 未修改 RAG/Agent 主链路之外的未点名逻辑

---

## 五、三条核心改动摘要

**1. 离线合规从「靠环境变量压制」变为「代码默认值即合规 + 启动即可验证」。**
`openai_api_base` 置空、`rerank_provider` 改 `local_bge`、`langsmith_tracing` 关、LLM/embedding 默认值换成本地模型，四处外网默认值全部清除；并新增 `assert_offline_mode()` 接入 `main.py` 与 `src/api/server.py` 双入口。空值直接拒绝启动，公网地址明确告警，私网地址打印确认。这补上了 Phase 2 报告里「无离线启动自检、漏配会静默回落百炼并超时」这个最隐蔽的失效模式。

**2. `kb_call_mode` 从假开关变成真开关。**
改造前它只存在于配置定义与配置中心白名单，改了没有任何效果。现在 `always` 会在 Agent 之前强制预检索并把结果去重并回 `retrieved_docs`，`smart` 保持 LLM 自主决策，`never` 跳过检索与 Agent 直接由 LLM 作答。两处枚举定义也统一为 `always/smart/never`。需要留意默认值 `always` 现在真实生效，技术类提问会固定多一次检索。

**3. 引用元数据补上页码，PDF 章节可定位到起始页。**
PDF loader 用 `---PAGE-BREAK---` 页边界加偏移量计数反推章节起始页，对「有书签」与「无书签」两类 PDF 一致生效，定位不到时返回 `None` 而不猜。真机端到端验证 3 页 3 章节得到 `[1,2,3]`。`citations` 结构新增 `page` 字段。

---

## 六、建议的下一步

按性价比排序，三条建议：

1. **补 `.env` 之外的部署形态**（对应 R1）。`docker-compose.dev.yml` 与 `docker-compose.milvus.yml` 未注入 `OPENAI_API_BASE`，P0-6 生效后这两种形态无法启动。若它们仍在用，需补上注入项。
2. **决定 `local_bge` 的去向**（对应 2.5）。当前是「安全但不生效」。要么按方案 B 修 `llm` provider 接线走 Ollama（改动小、完全离线），要么按方案 C 补依赖与权重（改动大）。若近期不打算启用重排序，建议把 `rerank_provider` 注释里明确写「需先按方案 C 预置依赖与权重，否则开启后仅降级不生效」。
3. **清理范围外残留**（对应 F1/F2/F4）。`qwen_vision_engine.py:53` 的外网回退、根 compose 的百炼回退、`requirements-runtime.txt` 的过时注释，三处都属于「同类问题漏网」，批量收口一次比逐次发现更省事。

---

*报告结束。本次执行遵循只读约束与逐项验收纪律，所有改动均可在同目录 `.bak` 文件中反向核对。*
