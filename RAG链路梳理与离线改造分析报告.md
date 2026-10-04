# RAG 链路梳理与离线改造分析报告

- **项目**：enterprise-agent
- **报告日期**：2026-09-16
- **任务阶段**：Phase 2（纯代码阅读与链路梳理）
- **作业约束**：只读。未修改任何业务代码，未启动/重启/重建任何容器，未改动任何 yaml / env / properties 配置，未删除/移动/重命名任何文件。
- **证据基准**：所有结论均标注「文件绝对路径 + 行号 + 代码片段摘要」。无代码支撑的推断一律进入「待确认问题清单」，不写入结论。

---

## 0. 摘要（先看这三条）

| 序号 | 结论 | 证据位置 | 状态 |
|---|---|---|---|
| 1 | `/ws/chat` **已接入** RAG 检索，且调用链完整贯通到 Chroma 与引用回传 | `src/websocket/routes.py:101` → `src/graph/nodes.py:777` → `src/agent/tools.py:946` → `src/rag/retriever.py:314` | ✅ 已实现 |
| 2 | 检索是**条件触发**，不存在「RAG 功能总开关」。是否检索交由 ReAct Agent 自主决定调用工具，`kb_call_mode` 配置项**定义后无任何消费点** | `src/graph/workflow.py:38`、`src/config.py:119` | ⚠️ 架构就绪但未接线 |
| 3 | 默认配置层存在**四处外网残留**（百炼 base URL、rerank provider、LangSmith、视觉引擎），内网 `.env.intranet` 与 `deploy/prod/.env.production` 已将其覆盖为本地 Ollama，但代码默认值未改造 | `src/config.py:29`、`src/config.py:128`、`src/config.py:47`、`src/websocket/multimodal.py:159` | ⚠️ 靠环境变量压制，属潜在雷 |

---

## 1. 环境基线确认

### 1.1 技术栈澄清（事实修正）

任务背景描述「技术栈为 Java/Spring Boot」，与仓库实际不符。核实结果如下。

| 检查项 | 命令/方法 | 结果 |
|---|---|---|
| `pom.xml` | `ls pom.xml` | No such file or directory |
| `build.gradle` / `build.gradle.kts` | `ls` | No such file or directory |
| `*.java` 源码（排除 frontend） | `find . -name "*.java"` | 无输出 |

**实际技术栈**（依据 `src/` 目录结构与依赖导入）

- 后端语言：Python
- Web 框架：FastAPI + Starlette WebSocket（`src/websocket/routes.py:101` 使用 `@router.websocket`）
- 编排框架：LangGraph（`src/graph/workflow.py:16` `from langgraph.graph import StateGraph, END`）
- 检索框架：LangChain（`src/rag/vector_store.py:51` `from langchain_chroma import Chroma`）
- 向量库：Chroma（默认）/ Milvus（可选）
- 模型服务：Ollama（内网形态）
- 前端：`frontend/` 为 Node 工程（vite）

**这条修正很重要**。若按 Java/Spring Boot 去找 `@Configuration`、`@Bean`、`application.yml`，会全程找不到目标。本报告中「依赖注入」一节按 Python 实际形态（工厂函数 + 模块级 settings 单例 + `partial` 绑定）梳理，见第 3.5 节。

### 1.2 容器状态（与任务描述不符）

命令 `docker ps -a` 实际输出（节选 4 个运行中实例）

```
0b8644930635   grafana/grafana:11.6.0        "Up 8 minutes (healthy)"   0.0.0.0:3000->3000/tcp   agent-grafana
5e2db930276c   prom/prometheus:v3.3.0        "Up 8 minutes (healthy)"   0.0.0.0:9090->9090/tcp   agent-prometheus
5680c03b067e   oliver006/redis_exporter      "Up 8 minutes"             9121/tcp                 agent-redis-exporter
47b793819f17   postgrescommunity/postgres-exporter "Up 8 minutes"        9187/tcp                 agent-pg-exporter
```

**结论**：任务描述「enterprise-agent 项目所有容器当前处于停止状态」「确认无容器正在运行」**不成立**。监控栈 4 个容器处于 `Up (healthy)` 状态。

辩证看这一点。这 4 个容器属于 `docker-compose.monitoring.yml` 定义的监控栈，与业务栈（`deploy/prod/docker-compose.prod.yml` 的 app / postgres / redis）是两套编排。业务容器确实全部停止，任务的核心前提（业务已停机、数据卷完整）成立。监控栈在跑，恰好意味着本次梳理未触碰的监控链路是活的，但它不承载 RAG 数据面，不影响本次只读分析。

**业务栈容器状态**

| 容器名 | 镜像 | 状态 |
|---|---|---|
| `thermo-intranet` | `thermo-chatbot:1.0.0` | Exited (0) 4 days ago |
| `enterprise-agent-api-service-1/2/3` | `enterprise-agent-api-service` | Exited |
| `enterprise-agent-ws-service-1/2/3` | `enterprise-agent-ws-service` | Exited (137) |
| `enterprise-agent-rag-service-1` | `enterprise-agent-rag-service` | Created |
| `enterprise-agent-agent-worker-1` | `enterprise-agent-agent-worker` | Created |
| `agent-milvus` / `agent-rabbitmq` / `agent-postgres` / `agent-redis` / `agent-minio` / `agent-apisix` | 各自镜像 | Exited |
| `enterprise-agent-frontend-1` | `nginx:1.27-alpine` | Exited |

### 1.3 Docker 数据卷

命令 `docker volume ls` 输出的相关卷

| 卷名 | 用途 | 判定 |
|---|---|---|
| `prod-agent-chroma` | **Chroma 向量库（内网形态）** | ✅ 存在 |
| `prod-ollama-models` | Ollama 模型权重 | ✅ 存在 |
| `prod-pg-data` | PostgreSQL 数据 | ✅ 存在 |
| `prod-redis-data` | Redis 数据 | ✅ 存在 |
| `prod-agent-logs` | 应用日志 | ✅ 存在 |
| `enterprise-agent_chatwoot_data` | Chatwoot 集成 | 存在 |
| `enterprise-agent_pg_data` | 云端形态 PG | 存在 |
| `agent-milvus-data` / `agent-minio-data` / `agent-pg-data` / `agent-redis-data` / `agent-rabbitmq-data` / `agent-prometheus-data` / `agent-grafana-data` | 云端形态各组件 | 存在 |
| `ollama-models` | 独立 Ollama 模型卷 | 存在 |

Chroma 数据卷 `prod-agent-chroma` 确认存在，由 `deploy/prod/docker-compose.prod.yml:165-166` 声明

```yaml
volumes:
  agent_chroma:
    name: prod-agent-chroma
```

对应挂载点 `deploy/prod/docker-compose.prod.yml:70` `- agent_chroma:/app/chroma_data`。

### 1.4 向量库数据基线（重要修正）

任务描述「知识库文档切片 14 条 + 长期记忆 2 条，共 16 条记录」。本项**无法在只读约束下验证**，原因见下。同时，对仓库本地 `chroma_data/` 做了只读校验，结果与描述不一致。

**本地 `chroma_data/chroma.sqlite3` 只读查询结果**（使用 stdlib sqlite3 以 `mode=ro` 打开，未写入）

```
collections:
  ('243a26cb-4838-471c-b93b-512177830810', 'knowledge_base_sentences')
  ('372dd0c4-bda6-4ba7-94e7-31d97be0372e', 'long_term_memory')

各 collection 向量块数:
  knowledge_base_sentences    块数=956
  long_term_memory            块数=0
```

**三点观察**

1. 本地库的向量块数是 **956**，与「16 条」量级差距很大。这个数字对应的是「句子粒度」集合，与 `retrieval_source_cap` 注释里提到的「7 篇手册 301 块」（`src/config.py:93-95`）也不是同一层（301 是标准粒度，956 是句子粒度）。
2. 本地库**只有** `knowledge_base_sentences` 集合，**没有** `knowledge_base` 集合。这个缺失值得留意，见第 6 节风险点。
3. `long_term_memory` 集合存在但内容为空（0 块），与描述的「长期记忆 2 条」不符。

**为什么无法验证 `prod-agent-chroma` 的真实基线**：该卷位于 Docker Desktop 的 WSL2 虚拟机内部，在 Windows 宿主文件系统上无直接可读路径。读取其内容必须启动一个容器挂载该卷（`docker run --rm -v prod-agent-chroma:/data ...`）。任务硬性约束第 1 条明确禁止启动/重建容器，故本次**不执行**，将其列入「待确认问题清单」第 1 项。

> 顺带提示一个方法论要点。任务描述把「14 + 2 = 16」写成了既成事实，但本地库的数据与之矛盾。在处理这类现场交接文档时，数字类前提要先验后信。记忆里已有同类教训（`改动方案.md` 曾严重漂移），此处再次印证。

### 1.5 项目顶层目录结构

```
C:\Users\hai\enterprise-agent\
├── src/                    # 后端源码（Python）
│   ├── api/                # REST 接口层（含 knowledge.py / monitoring.py / metrics.py）
│   ├── websocket/          # WebSocket 层（routes.py 为主链路）
│   ├── graph/              # LangGraph 编排（nodes.py / workflow.py / workflow_dag.py）
│   ├── rag/                # RAG 核心（retriever / vector_store / embedder / reranker / chunker / loader）
│   ├── agent/              # Agent 与工具（agent.py / tools.py / prompt.py）
│   ├── memory/             # 长期记忆
│   ├── mcp_tools/          # MCP 工具（含资源查询、IM 集成）
│   ├── protocols/          # A2A / MCP 协议实现
│   ├── evaluation/         # 评测
│   ├── config.py           # 全局配置（pydantic-settings 单例）
│   └── config_center/      # 配置中心（热更新）
├── frontend/               # 前端工程（Node）
├── deploy/prod/            # 内网单容器形态编排（docker-compose.prod.yml 在此，非项目根）
├── deploy/monitoring/      # 监控栈
├── chroma_data/            # 本地 Chroma 持久化目录
├── data/docs/              # 知识库源文档
├── docker-compose.yml              # 云端多服务形态
├── docker-compose.monitoring.yml   # 监控栈
├── Dockerfile                      # 多阶段构建（runtime-base / runtime-with-ollama / runtime）
├── .env / .env.intranet            # 环境配置
└── tests/                          # 测试
```

**文件位置修正**：任务要求在「项目根目录 `docker-compose.prod.yml`」读取配置。该文件实际位于 `deploy/prod/docker-compose.prod.yml`，项目根仅有 `docker-compose.yml`、`docker-compose.dev.yml`、`docker-compose.milvus.yml`、`docker-compose.monitoring.yml`。

---

## 2. `/ws/chat` 聊天链路 RAG 接入结论

### 结论：✅ 已接入 RAG 检索

链路完整贯通，从 WebSocket 收帧一路走到 Chroma 向量检索，并把检索结果作为引用回传给前端。

### 2.1 完整调用链路

```
客户端
  │ WebSocket 连接
  ▼
[1] @router.websocket("/ws/chat")
    src/websocket/routes.py:101
    │
    ├─ 身份解析 _resolve_ws_identity()          routes.py:114
    ├─ 建立会话 session_mgr.create_session()    routes.py:140
    └─ while True: receive_text()               routes.py:158-159
         │
         │ msg_type == TYPE_CLIENT_CHAT
         ▼
[2] _handle_ai_chat()
    src/websocket/routes.py:520
    │
    ├─ 用户消息落库 message_save()              routes.py:542-545
    ├─ 多模态预处理 process_multimodal_message() routes.py:557
    ├─ app = get_workflow()                     routes.py:573
    ├─ 构建 AgentState                          routes.py:624-654
    │    （retrieved_docs 初始化为空 []，routes.py:627）
    └─ app.invoke(state, thread_config)         routes.py:669
         │
         ▼
[3] LangGraph DAG
    src/graph/workflow.py:87-148
    │
    entry ──► clarify ──┬─(needs_clarification)─► reply
                        │
                        └─(clear)─► router ──┬─(faq)────► faq ──┬─(命中)─► reply
                                             │                    └─(未命中)─► rag
                                             ├─(human)──► human ──► reply
                                             └─(其它)──► rag ──► reflect ──► reply ──► END
    │
    ▼
[4] rag_node()
    src/graph/nodes.py:777
    │
    ├─ 提取对话历史 _extract_history_manual()    nodes.py:803
    ├─ MemoryManager 长期记忆注入 on_rag_start() nodes.py:807-823
    └─ 构造 CustomerServiceAgent                 nodes.py:826-839
         │   参数含 retriever / tenant_id / user_access_levels / user_roles
         ▼
[5] agent.run_with_trace(content, chat_history=history)   nodes.py:841
    │
    │ ReAct 循环，由 LLM 决定是否调用工具
    ▼
[6] @tool search_knowledge_base(query)
    src/agent/tools.py:946
    │
    ├─ 权限检查 checker.check()                  tools.py:957
    ├─ 读 top_k 配置 settings.retrieval_top_k    tools.py:970-974
    ├─ retriever.search(...)                     tools.py:976-982
    └─ 结果格式化为 [Doc i - source] 文本         tools.py:1005-1014
         │
         ▼
[7] HybridRetriever.search_with_scores()
    src/rag/retriever.py:314
    │
    ├─ 查询改写 QueryRewriter().rewrite()        retriever.py:342-345
    ├─ 向量检索 top_k*2                          retriever.py:350
    ├─ BM25 检索 top_k*2（vector_only 可关）      retriever.py:353-356
    ├─ 句子粒度检索                              retriever.py:359-363
    ├─ RRF 融合（k=60）                          retriever.py:366 / 614
    ├─ 合并标准 + 句子结果                        retriever.py:377-379
    ├─ 重排序（rerank_enabled 控制，默认关）       retriever.py:384-385
    ├─ 权限过滤 _filter_by_permission()          retriever.py:389-391
    └─ 版本冲突处理 _resolve_version_conflicts()  retriever.py:400
         │
         ▼
[8] VectorStoreManager.search_with_scores()
    src/rag/vector_store.py:101
    │
    └─ Chroma.similarity_search_with_relevance_scores()   vector_store.py:124-127
        （embedding 由 Embedder 提供，vector_store.py:20）
    │
    ▼ 检索结果逐层回溯
    retriever → tool（格式化为文本喂给 LLM） → rag_node
    │
    ▼
[9] rag_node 汇总返回                          nodes.py:1092-1099
    return { final_response, needs_human, quality_score,
             retrieved_docs, tool_sourced, answer_status }
    │
    ▼
[10] 回到 _handle_ai_chat 组装引用并回推
    src/websocket/routes.py:750  citations = _build_citations(result.get("retrieved_docs"))
    src/websocket/routes.py:478  _build_citations() 定义
    src/websocket/routes.py:819-822  done 帧携带 citations
    │
    ▼
客户端收到 {type: streaming_chunk, done: true, citations: [...]}
```

### 2.2 检索函数定位（回答「检索函数名、所在文件、行号」）

| 层 | 函数名 | 文件绝对路径 | 行号 |
|---|---|---|---|
| 工具层（LLM 可见入口） | `search_knowledge_base` | `C:\Users\hai\enterprise-agent\src\agent\tools.py` | 946 |
| 工具注册 | `tools = [search_knowledge_base, search_faq, escalate_to_human]` | `C:\Users\hai\enterprise-agent\src\agent\tools.py` | 1112 |
| 检索器对外接口 | `HybridRetriever.search` | `C:\Users\hai\enterprise-agent\src\rag\retriever.py` | 275 |
| 检索器主流程 | `HybridRetriever.search_with_scores` | `C:\Users\hai\enterprise-agent\src\rag\retriever.py` | 314 |
| 向量检索 | `HybridRetriever._vector_search` | `C:\Users\hai\enterprise-agent\src\rag\retriever.py` | 421 |
| BM25 检索 | `HybridRetriever._bm25_search` | `C:\Users\hai\enterprise-agent\src\rag\retriever.py` | 548 |
| RRF 融合 | `HybridRetriever._rrf_fusion` | `C:\Users\hai\enterprise-agent\src\rag\retriever.py` | 614 |
| 重排序 | `HybridRetriever._rerank` | `C:\Users\hai\enterprise-agent\src\rag\retriever.py` | 748 |
| 相似度阈值过滤 | `HybridRetriever._filter_by_similarity` | `C:\Users\hai\enterprise-agent\src\rag\retriever.py` | 584 |
| 权限过滤 | `HybridRetriever._filter_by_permission` | `C:\Users\hai\enterprise-agent\src\rag\retriever.py` | 806 |
| 向量库封装 | `VectorStoreManager.search_with_scores` | `C:\Users\hai\enterprise-agent\src\rag\vector_store.py` | 101 |
| 编排节点 | `rag_node` | `C:\Users\hai\enterprise-agent\src\graph\nodes.py` | 777 |

### 2.3 检索触发条件（回答「全量触发 or 条件触发」）

**结论：条件触发，且不含「RAG 总开关」。是否真正检索由 LLM 在 ReAct 循环中自主决定。**

触发决策分两级。

**第一级：图路由（决定是否进入 rag 节点）**

路由函数 `src/graph/workflow.py:38-47`

```python
def _decide_route(state: AgentState) -> str:
    intent = state.get("intent", "faq")
    if intent == "human":
        return "human"
    elif intent == "faq":
        return "faq"
    else:
        return "rag"          # 除 faq / human 外，全部走 rag
```

FAQ 分支的二次决策 `src/graph/workflow.py:50-55`

```python
def _decide_after_faq(state: AgentState) -> str:
    if state.get("faq_match"):
        return "reply"        # FAQ 命中，不检索
    else:
        return "rag"          # FAQ 未命中，升级到 RAG
```

`intent` 由 `router_node` 判定，`src/graph/nodes.py:537-670`，判定顺序为

| 顺序 | 条件 | 结果 intent | 行号 |
|---|---|---|---|
| 1 | 问候语关键词（你好 / hello / 谢谢 等） | `faq` | nodes.py:567-568 |
| 2 | 强制转人工关键词（转人工 / 投诉 / 退款 / 摔坏 / 进水 等） | `human` | nodes.py:612-613 |
| 3 | 英文转人工正则 `_ENGLISH_HANDOFF_RE` | `human` | nodes.py:618-619 |
| 4 | 负面情绪检测 `_detect_negative_emotion` | `human` | nodes.py:623-629 |
| 5 | FAQ 关键词（reset password / pricing 等） | `faq` | nodes.py:644-645 |
| 6 | LLM 分类 | `faq` / `technical` | nodes.py:648-666 |
| 7 | 分类失败兜底 | `technical` | nodes.py:670 |

其中第 6 步有一处刻意的改写，`src/graph/nodes.py:660-661`

```python
if intent == "human":
    intent = "technical"
```

注释解释（nodes.py:657-659）：LLM 判为 human 时不强制转人工，改走 technical 路径，靠 RAG 失败机制触发 `suggest_human`，把是否转人工的决定权交回用户。所以 **LLM 分类永远不会产出 human**，`human` 只来自关键词与情绪规则。

**第二级：工具调用（决定是否真正执行检索）**

进入 `rag_node` 后，`src/graph/nodes.py:826-841` 构造 `CustomerServiceAgent` 并调用 `run_with_trace`。检索动作发生在 ReAct 循环内部，由 LLM 决定是否发起 `search_knowledge_base` 调用。

这意味着即使路由判定为 `technical` 并进入 `rag_node`，若 LLM 未选择调用该工具，本次对话也**不会**产生真实检索。系统 prompt 中对此有引导，`src/agent/prompt.py:30`

```
技术问题优先用 search_knowledge_base / search_faq 检索知识库与 FAQ
```

但这是 prompt 层软约束。记忆中的既有教训正对应这一点：7B 模型的 prompt 约束不可完全信任，代码层兜底才是硬边界。

**关于「RAG 功能总开关」的核查结论**

配置项 `kb_call_mode` 存在，`src/config.py:119-121`

```python
kb_call_mode: str = (
    "always"  # 调用模式：always 必定调用 / smart 智能调用（AI 自主判断）
)
```

全仓库检索其消费点，结果如下

```
src/config.py:119                      ← 定义
src/config_center/categories.py:30     ← 列入配置中心白名单
src/config_center/schema.py:128        ← 定义枚举 ("auto","always","never")
tests/test_api/test_config_center.py:254  ← 测试用例
```

**除配置定义与配置中心白名单外，无任何业务代码读取 `kb_call_mode`。** 也就是说，即便在配置中心把它改成 `never`，检索行为也不会变化。这是一个「配置项存在但无人消费」的假开关，属于典型的假热更新陷阱（同类问题在 `retrieval_rerank_top_n` 上已被修过，见 `src/graph/nodes.py:958-965` 的注释）。

此外枚举值存在不一致，`src/config.py:120` 的文档说明是 `always` / `smart`，而 `src/config_center/schema.py:128` 定义的是 `("auto", "always", "never")`。两处对同一字段的可选值定义不同，需人工确认哪一份是准的。

**补充的一条兜底检索路径**

`rag_node` 内有一段「引用补检」，`src/graph/nodes.py:952-997`。当 Agent 路径没拿到结构化文档时，节点会绕过工具格式化，直接调 `retriever.search(content, ...)` 补一次检索。这段代码的作用是修复「工具把 docs 格式化成字符串导致引用气泡恒空」的问题，注释见 nodes.py:946-951。

这条路径的意义在于，**即使 LLM 没调工具，系统仍可能通过补检拿到检索结果**，条件是该分支被触发（`retrieved_docs` 为空且 `retriever` 非 None）。从可观测角度看，这让「检索是否发生」的判定变复杂，无法仅凭 LLM 输出推断。

### 2.4 检索结果是否拼入 LLM prompt

**结论：是，以工具返回文本的形式拼入。**

拼接发生在 `search_knowledge_base` 工具内部，`src/agent/tools.py:1005-1014`

```python
parts = []
for i, doc in enumerate(results, 1):
    source = doc.metadata.get("source", "unknown")
    content = trim_chunk_for_llm(doc.page_content, 1200)
    parts.append(f"[Doc {i} - {source}]\n{content}")
result_text = "\n\n---\n\n".join(parts)
```

每条切片上限 1200 字符，用 `[Doc i - source]` 标注来源，片段间以 `---` 分隔。

**拼接位置的性质**：这不是「把检索结果塞进 system prompt」，而是标准的 ReAct 工具返回模式。检索文本以 `Observation` 的身份进入对话消息序列，再由 LLM 在其上生成最终回答。这一点在离线改造时很关键，因为 prompt 模板本身不需要改，改动点在工具返回值。

**prompt 模板结构**（三层约束）

| 层 | 位置 | 内容 |
|---|---|---|
| 1. 系统 prompt 引导 | `src/agent/prompt.py:30` | 技术问题优先用 `search_knowledge_base` 检索 |
| 2. 未收录硬提示 | `src/agent/tools.py:1026-1036` | 检索词中的错误码/型号若未出现在命中文档中，明确标记「未收录判定」并要求不得推测 |
| 3. 回答格式硬指令 | `src/agent/tools.py:1041-1052` | 追加于工具结果末尾（近因效应最强位）；要求首句给结论、禁止弱化措辞、禁止反问、禁止英文、禁止编造 |

第 3 层贴在工具返回末尾，`src/agent/tools.py:1041` 注释说明了原因：「小模型（qwen2.5:7b 级别）工具调用后语言容易漂移到英文、反问用户，或在文档已有答案时仍声称未找到」。

---

## 3. knowledge 模块与 RAG 核心实现

### 3.1 模块文件清单

**`src/rag/`（RAG 核心，24 个文件）**

| 文件 | 大小 | 职责 |
|---|---|---|
| `retriever.py` | 44.9 KB | 混合检索主流程（向量 + BM25 + RRF + rerank + 权限 + 版本冲突） |
| `chunker.py` | 15.4 KB | 文本切片 |
| `loader.py` | 15.0 KB | 文档载入 |
| `milvus_store.py` | 13.4 KB | Milvus 后端封装 |
| `outline.py` | 13.3 KB | 大纲/结构提取 |
| `deepdoc_parser.py` | 11.5 KB | 深度文档解析（含 OCR 路径） |
| `reranker.py` | 10.1 KB | 重排序（dashscope / local_bge / llm 三 provider） |
| `remote_client.py` | 7.8 KB | 远程 rag-service HTTP 客户端 |
| `vector_store.py` | 7.5 KB | 向量库封装（Chroma / Milvus / auto / remote） |
| `server.py` | 6.7 KB | 独立 RAG 服务 |
| `embedder.py` | 4.9 KB | 向量化（openai / dashscope / local） |
| `query_rewriter.py` | 4.0 KB | 查询改写 |
| `source_ingest.py` | 3.7 KB | 网页抓取入库（httpx + BeautifulSoup） |
| `sync_models.py` | 3.6 KB | 模型同步 |
| `sync_state.py` | 5.5 KB | 同步状态 |
| `data_sources.py` | 4.0 KB | 数据源抽象 |
| `types.py` | 1.8 KB | 类型定义 |
| `file_sync_manager.py` | 17.7 KB | 文件同步管理 |
| `image_context.py` | 3.2 KB | 图片上下文 |
| `loader_utils.py` | 1.5 KB | 载入工具 |
| `loaders/`、`processors/`、`vision_engines/` | 目录 | 各类载入器与处理器 |

**`src/agent/`（Agent 与工具）**

| 文件 | 大小 | 职责 |
|---|---|---|
| `tools.py` | 51.8 KB | 全部工具定义，含 `search_knowledge_base` |
| `agent.py` | 12.9 KB | `CustomerServiceAgent` |
| `prompt.py` | 9.5 KB | prompt 模板 |
| `fake_llm.py` | 3.7 KB | 测试用假 LLM |

**`src/api/`（知识库 REST 接口）**

| 文件 | 大小 | 职责 |
|---|---|---|
| `knowledge.py` | 40.7 KB | 知识库管理接口（上传/删除/检索/重建） |

### 3.2 能力边界清单

| 能力 | 状态 | 证据 |
|---|---|---|
| 文档上传解析 | ✅ 已实现 | `src/rag/loader.py`、`src/rag/deepdoc_parser.py`、`src/api/knowledge.py`；支持 PDF/DOCX/TXT/MD（`fixtures/` 下四种格式齐全） |
| 网页抓取入库 | ⚠️ 架构就绪，离线不可用 | `src/rag/source_ingest.py:11` 流程为 `URL → httpx 抓取 → BeautifulSoup 提取正文 → 临时 .txt → DocumentLoader.load_file` |
| 文本切片策略 | ✅ 已实现 | `src/rag/chunker.py`；配置 `chunk_size=512` / `chunk_overlap=64`（`src/config.py:88-89`） |
| 句子粒度切分 | ✅ 已实现 | `knowledge_base_sentences` 集合实际存在（本地库 956 块） |
| 向量化 embedding | ✅ 已实现，三 provider | `src/rag/embedder.py:29-66`，支持 `openai` / `dashscope` / `local` |
| 写入 Chroma | ✅ 已实现 | `src/rag/vector_store.py:75-84` `add_documents` |
| 相似度检索 | ✅ 已实现 | `src/rag/vector_store.py:101-127` `similarity_search_with_relevance_scores` |
| 混合检索 BM25 + 向量 | ✅ 已实现，默认开启 | `src/rag/retriever.py:350-356`；`retrieval_vector_only=False` 时启用 BM25 |
| RRF 融合 | ✅ 已实现 | `src/rag/retriever.py:614-650`，k=60，支持知识库权重与文档权重 |
| 重排序 rerank | ⚠️ 已实现但默认关闭 | `src/rag/retriever.py:384-385`；`rerank_enabled` 默认 `False`（`src/config.py:124-126`），三条 provider 路径齐备 |
| 相似度阈值过滤 | ✅ 已实现 | `src/rag/retriever.py:584-608`，阈值 `kb_similarity_threshold` 默认 0.2 |
| 多租户隔离 | ✅ 已实现 | DB 级 `where` 过滤（`src/rag/retriever.py:452-455`）+ 应用层后过滤（`_filter_by_permission`，retriever.py:806）双层 |
| 权限等级过滤 | ✅ 已实现 | `src/rag/retriever.py:806`；4 级 public/internal/confidential/restricted |
| 版本冲突处理 | ✅ 已实现 | `src/rag/retriever.py:919` `_resolve_version_conflicts` |
| 查询改写 | ✅ 已实现 | `src/rag/query_rewriter.py`；`rewrite_enabled` 默认 True |
| 来源配额 | ✅ 已实现 | `retrieval_source_cap=2`（`src/config.py:102`） |
| 文档删除（含向量清理） | ✅ 已实现 | `src/rag/vector_store.py:158-192` `delete_by_where`，注释说明用于避免「幽灵引用」 |
| 文档更新 | ✅ 已实现 | 通过 `delete_by_where` + 重新 `add_documents` 组合；`src/rag/file_sync_manager.py` 负责同步 |
| 引用组装与回传 | ✅ 已实现 | `src/websocket/routes.py:478-517` |
| 命中埋点与耗时 | ✅ 已实现 | `src/rag/retriever.py:404-413` `record_rag_search` |
| RAG 功能总开关 | ❌ **未实现** | `kb_call_mode` 定义后无消费点（见 2.3 节） |
| 独立 RAG 服务（多形态） | ⚠️ 架构就绪 | `src/rag/server.py` + `rag_service_url`（`src/config.py:84`）指向 `http://localhost:8001`，内网单容器形态未启用 |

### 3.3 Chroma 封装细节

**collection 命名规则**

`src/rag/vector_store.py:17-19`

```python
def __init__(self, persist_directory: str = None, collection_name: str = None):
    self.persist_directory = persist_directory or settings.chroma_persist_dir
    self.collection_name = collection_name or settings.chroma_collection_name
    self._embedding_function = Embedder()
```

默认集合名 `knowledge_base`（`src/config.py:58`），句子粒度集合为 `knowledge_base_sentences`，长期记忆集合为 `long_term_memory`。后两者由本地库实测确认。

**持久化目录**

- 代码默认：`./chroma_data`（`src/config.py:57`）
- 内网容器内：`/app/chroma_data`（`deploy/prod/docker-compose.prod.yml:37`）
- 卷映射：`prod-agent-chroma:/app/chroma_data`（`deploy/prod/docker-compose.prod.yml:70`）

**元数据字段定义**

从 `_build_citations` 的读取逻辑反推（`src/websocket/routes.py:491-494`）

| 字段 | 用途 | 读取位置 |
|---|---|---|
| `source` | 源文件名 | routes.py:491 |
| `doc_id` | 文档 ID | routes.py:492 |
| `title` | 展示标题 | routes.py:493 |
| `kb_id` | 知识库 ID | routes.py:494 |
| `score` / `rrf_score` | 相似度分 | routes.py:502-506 |
| `tenant_id` | 租户隔离 | retriever.py:452 |
| `access_filtered` | 权限过滤计数 | routes.py 由 rag_node 注入，tools.py:1001-1003 |
| `version_conflicts` / `has_conflicts` | 版本冲突提示 | retriever.py:298-301 文档说明 |

**embedding 调用方式（是否本地 Ollama）**

`src/rag/embedder.py:54-66`，默认 `provider == "openai"` 分支走 OpenAI 兼容接口

```python
base_url = settings.embedding_api_base or settings.openai_api_base
api_key = settings.embedding_api_key or settings.openai_api_key or "ollama"
self._client = OpenAI(api_key=api_key, base_url=base_url)
```

内网 `.env.intranet:15` 将 `OPENAI_API_BASE` 设为 `http://ollama:11434/v1`，`EMBEDDING_MODEL=bge-m3`（`.env.intranet:21`），`EMBEDDING_DIMENSIONS=1024`（`.env.intranet:22`）。

**结论：内网形态下 embedding 走本地 Ollama 的 bge-m3，是本地调用。** 但代码层默认值是百炼地址（`src/config.py:29`），本地化完全依赖环境变量覆盖。

还有一处工程细节值得记录。`src/rag/embedder.py:82-101` 处理了维度参数兼容问题

```python
try:
    resp = self._client.embeddings.create(model=..., input=text, dimensions=self.dimensions)
except Exception as e:
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status == 400 or "dimensions" in msg or "unexpected" in msg:
        resp = self._client.embeddings.create(model=..., input=text)
```

原因注释（embedder.py:82-83）：百炼支持 `dimensions` 参数，Ollama 与多数 vLLM 部署不支持，传了会返回 400。首次带参尝试失败后自动去掉重试。这是内网适配已做过处理的证据。

### 3.4 检索参数

| 参数 | 默认值 | 定义位置 | 说明 |
|---|---|---|---|
| `retrieval_top_k` | 5 | `src/config.py:90` | 工具层读取（`src/agent/tools.py:970-974`），实际召回 `top_k*2` 后融合截断 |
| `retrieval_rerank_top_n` | 3 | `src/config.py:91` | 补检路径条数（`src/graph/nodes.py:962`） |
| `retrieval_min_tokens` | 200 | `src/config.py:92` | 低于此值标记低置信度 `quality_score=0.2`（nodes.py:1050-1057） |
| `retrieval_vector_only` | `False` | `src/config.py:96` | 置 `True` 关闭 BM25 路。内网 `.env.intranet:38` 置为 true |
| `retrieval_source_cap` | 2 | `src/config.py:102` | 单源文档最多贡献片段数，防单篇吃光名额 |
| `rewrite_enabled` | `True` | `src/config.py:105` | 查询改写开关 |
| `kb_similarity_threshold` | 0.2 | `src/config.py:116-118` | 相似度阈值，仅作用于向量检索结果 |
| `rerank_enabled` | **`False`** | `src/config.py:124-126` | 重排序总开关，默认关 |
| `rerank_provider` | `"dashscope"` | `src/config.py:128` | 重排序 provider |
| `rerank_model` | `"gte-rerank"` | `src/config.py:130` | 重排序模型名 |
| `rerank_top_n` | 5 | `src/config.py:131` | 重排后保留条数 |
| `chunk_size` / `chunk_overlap` | 512 / 64 | `src/config.py:88-89` | 切片参数 |
| `doc_weights` | 5 个文件名权重 | `src/config.py:108-114` | 影响 RRF 排序 |

**top_k 的实际使用路径**（`src/agent/tools.py:970-982`）

```python
_top_k = int(getattr(_settings, "retrieval_top_k", 5))
_top_k = max(1, min(_top_k, 50))          # 夹取 1..50
results = retriever.search(query, top_k=_top_k, ...)
```

工具层对 top_k 做了范围夹取，防止配置被改成 0 或过大值。

**重排序的实际生效条件**

默认 `rerank_enabled=False`，`_rerank` 不会被调用。`src/rag/retriever.py:734-741`

```python
@property
def _rerank_enabled(self) -> bool:
    if self._rerank_init_failed:
        return False
    return bool(getattr(settings, "rerank_enabled", False))
```

这是实时读配置的 property，设计意图是支持热更新。同时注意 `_rerank_init_failed` 一旦置位，重排序在本进程内永久关闭。

**相似度阈值的实际作用范围（一处需要留意的细节）**

`_filter_by_similarity` 的调用点仅在向量检索内部

```
src/rag/retriever.py:435   → Remote 模式
src/rag/retriever.py:441   → Milvus 模式
src/rag/retriever.py:456   → Chroma 模式
src/rag/retriever.py:565   → _sentence_vector_search
```

`search_with_scores` 主流程（retriever.py:314-415）在 RRF 融合后**未再调用** `_filter_by_similarity`。这意味着阈值只作用于向量召回的输入侧，BM25 召回的文档不受阈值约束，RRF 融合后的最终结果也不会被阈值二次筛掉。这是设计选择还是疏漏，需要人工确认，列入待确认清单第 4 项。

### 3.5 依赖注入方式（Python 实际形态）

任务要求读取「Spring 的 Configuration/Bean 类」。因项目为 Python，此处按实际机制梳理，共三层。

**第一层：全局配置单例**

`src/config.py:20-25`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
```

基于 `pydantic-settings`，从 `.env` 与环境变量读取。模块级实例被 `src/rag/retriever.py:5`、`src/rag/vector_store.py:5`、`src/rag/embedder.py:21` 等广泛直接导入使用（`from src.config import settings`）。这构成事实上的全局单例。

**第二层：工厂函数**

| 工厂函数 | 位置 | 说明 |
|---|---|---|
| `create_embedder(provider, model)` | `src/rag/embedder.py:118-120` | 创建 Embedder |
| `create_reranker(provider, **kwargs)` | `src/rag/reranker.py:257` | 按 provider 名创建重排序器，不支持的名字抛 `ValueError`（reranker.py:298-299） |
| `create_workflow(retriever, memory_manager)` | `src/graph/workflow.py:58` | 组装并编译 LangGraph |

**第三层：`partial` 绑定（Python 版的构造器注入）**

`src/graph/workflow.py:69-97`

```python
rag_node_bound = partial(rag_node, retriever=retriever, memory_manager=memory_manager)
entry_node_bound = partial(entry_node, memory_manager=memory_manager)
reply_node_bound = partial(reply_node, memory_manager=memory_manager)

workflow.add_node("entry", entry_node_bound)
workflow.add_node("rag", rag_node_bound)
workflow.add_node("reply", reply_node_bound)
```

`rag_node` 的签名把依赖声明为可选参数并给默认值 `None`（`src/graph/nodes.py:777-782`）

```python
def rag_node(state: AgentState, retriever=None, memory_manager=None, user_id: str = "") -> dict[str, Any]:
```

**这里有一处需要关注的设计特征。** `retriever` 默认值为 `None`，工具内部对此做了判空（`src/agent/tools.py:960-961`）

```python
if retriever is None:
    return "知识库当前不可用。请转人工客服。"
```

判空存在是好习惯，但也意味着**依赖装配失败时系统会静默降级为「知识库不可用」**，而非在启动阶段报错。这类降级在演示环境是加分项，在生产排查时是干扰项。运行期若出现大量「知识库当前不可用」，应优先怀疑 retriever 未注入，而非知识库缺内容。

**Retriever 实例来源**：`get_workflow()` 由 `src/api/dependencies.py` 提供，`src/websocket/routes.py:534` 导入使用。

### 3.6 离线专项检查结果

对 `src/` 全量扫描 `http(s)://`，排除 localhost / 127.0.0.1 / schema 后，外网地址分布如下。

**RAG 直接相关（本次重点）**

| 序号 | 文件:行 | 内容 | 风险 |
|---|---|---|---|
| 1 | `src/config.py:29` | `openai_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"` | **高**。默认值即外网，LLM 与 Embedding 共用此配置 |
| 2 | `src/config.py:30-32` | `embedding_model="text-embedding-v4"`、`embedding_provider="openai"` | **高**。默认指向百炼在线 embedding |
| 3 | `src/config.py:37-38` | `llm_model="qwen-plus"`、`llm_complex_model="qwen-max"` | 中。云端模型名，内网需覆盖 |
| 4 | `src/config.py:128` | `rerank_provider: str = "dashscope"` | **高**。一旦开启 rerank 即外呼 |
| 5 | `src/config.py:130` | `rerank_model = "gte-rerank"` | 中。配套外网 provider |
| 6 | `src/rag/reranker.py:130` | `self.api_base = api_base or "https://dashscope.aliyuncs.com/compatible-mode/v1"` | **高**。代码内硬编码，非配置项 |
| 7 | `src/rag/reranker.py:272-284` | `dashscope` 分支取 `os.getenv("OPENAI_API_KEY")` 作 api_key | 中。内网 key 为占位值 `ollama` |
| 8 | `src/config.py:44-47` | `langsmith_api_key` / `langsmith_tracing: bool = True` | **高**。外部追踪默认开启（内网配置已覆盖为 false） |

**RAG 模块内部的外网能力（需隔离，非默认路径）**

| 序号 | 文件:行 | 内容 |
|---|---|---|
| 9 | `src/rag/source_ingest.py:36-39` | `import httpx` / `httpx.get(...)`，网页抓取入库 |

**内网适配已做处理的地方**

| 文件:行 | 内容 |
|---|---|
| `src/rag/embedder.py:57-61` | embedding 端点可独立配置，`api_key` 缺省给占位值 `"ollama"`，注释明确说明内网 Ollama 场景 |
| `src/rag/embedder.py:82-98` | 处理 Ollama / vLLM 不支持 `dimensions` 参数的 400 降级重试 |
| `src/rag/vector_store.py:44-48` | Milvus 不可用自动降级 Chroma |

**其他模块的外网依赖（超出 RAG 范围，供改造参考）**

| 文件:行 | 内容 | 内网影响 |
|---|---|---|
| `src/websocket/multimodal.py:159` | `base_url="https://dashscope.aliyuncs.com/..."` | 图像/语音多模态处理外呼 |
| `src/rag/vision_engines/qwen_vision_engine.py:53` | 同上 | 视觉引擎外呼 |
| `src/api/admin.py:353` | `https://open.feishu.cn/open-apis/...` | 飞书告警推送 |
| `src/mcp_tools/dingtalk.py:29,63` | `https://oapi.dingtalk.com/...` | 钉钉集成 |
| `src/mcp_tools/feishu.py:22` | `https://open.feishu.cn/open-apis` | 飞书集成 |
| `src/mcp_tools/github.py:38` | `https://api.github.com` | GitHub 集成 |
| `src/mcp_tools/slack.py:28` | `https://slack.com/api/` | Slack 集成 |
| `src/channels/wechat.py:26` | `https://qyapi.weixin.qq.com/...` | 企业微信告警 |
| `src/mcp_tools/cloud_provider.py:53` | `https://cloudsync-assets.oss-cn-hangzhou.aliyuncs.com` | 样本数据中的占位 IP 字段 |

**离线合规总体判定**

代码**默认值层不合规**，**环境变量层合规**。内网两条运行时配置都已把外网地址覆盖为本地

`.env.intranet:14-22`

```
OPENAI_API_KEY=ollama
OPENAI_API_BASE=http://ollama:11434/v1
LLM_MODEL=qwen2.5:7b
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIMENSIONS=1024
```

`deploy/prod/docker-compose.prod.yml:32-35`

```yaml
- OPENAI_API_KEY=${OPENAI_API_KEY}
- OPENAI_API_BASE=http://127.0.0.1:11434/v1
- LLM_MODEL=${LLM_MODEL:-qwen2.5:7b}
- EMBEDDING_MODEL=${EMBEDDING_MODEL:-bge-m3}
```

**这个结构有一个真实风险**。合规性完全依赖环境变量注入，代码层没有任何「离线模式」断言或启动自检。一旦某个部署路径漏传 `OPENAI_API_BASE`，系统会静默回落到百炼地址，在内网表现为连接超时（而非明确的配置错误提示）。这个失效模式很隐蔽，建议加入启动自检。

---

## 4. 引用来源返回结论

### 结论：✅ 前端能拿到文档引用来源，且有专门字段承载

### 4.1 组装环节

引用组装分三步。

**第一步：rag_node 提取结构化文档**

`src/graph/nodes.py:938`

```python
retrieved_docs = _extract_retrieved_docs(result.get("intermediate_steps", []))
```

`_extract_retrieved_docs` 定义在 `src/graph/nodes.py:1549-1563`，从 `intermediate_steps` 的 observation 中抽取 list 类型的文档。

**第二步：资源工具结果并回**

`src/graph/nodes.py:943-944`

```python
if tool_docs:
    retrieved_docs = (retrieved_docs or []) + tool_docs
```

`tool_docs` 来自 `_extract_tool_citation_docs(result.get("messages", []))`（nodes.py:845），定义在 `src/graph/nodes.py:1570-1600`。该函数从 LangGraph 的 `ToolMessage` 中抽取云资源类工具的真实返回（`_RESOURCE_TOOL_NAMES = {"query_resources", "describe_resource", "get_resource_monitor"}`，nodes.py:1568），转成带完整元数据的 `Document`。

注释（nodes.py:1572-1578）说明了这个修复的动机：`create_agent` 预构建的 ReAct 不填 `intermediate_steps`，工具结果在 `ToolMessage` 里，rag_node 原先只读 `intermediate_steps`，导致资源查询调了工具但 citations 恒为空。

**第三步：路由层组装引用卡片**

`src/websocket/routes.py:750`

```python
citations = _build_citations(result.get("retrieved_docs") or [])
```

`_build_citations` 完整实现（`src/websocket/routes.py:478-517`），输出结构为

```python
citations.append({
    "title": title,       # meta.title 或 meta.source 或 doc_id 或 "未知文档"
    "content": content,   # page_content 截断至 500 字符
    "score": round(score, 4),
    "source": source,     # meta.source 或 meta.doc_id
    "doc_id": doc_id,
    "kb_id": kb_id,
})
```

**分数取值优先级**（`src/websocket/routes.py:500-508`）

```python
score = float(
    getattr(d, "score", 0)
    or (isinstance(meta, dict) and (meta.get("score") or meta.get("rrf_score") or 0))
    or 0
)
```

先取 `doc.score`，再回退 `metadata.score`，再回退 `metadata.rrf_score`。这是为了兼容两种来源的文档：LangChain 原生 `Document` 与补检路径注入伪分数的文档。补检注入逻辑见 `src/graph/nodes.py:981-987`，伪分数取 `1/(rank+1)`。

**注意伪分数的语义**。补检路径的 `score` 是按排名倒推的，反映排序位置，与向量余弦相似度不可比。测试中出现 `0.9999` 附近的分数属正常（Chroma relevance score 特性），而 `1.0` / `0.5` / `0.3333` 这类规整值则来自伪分数。这个区分在排查引用质量问题时会用到。

### 4.2 返回字段承载

**WebSocket 消息结构**（`src/websocket/routes.py:818-822`）

```python
# 完成标记（附带本回答引用的知识片段，供前端做「引用知识片段」气泡）
await websocket.send_json(build_streaming_chunk(
    session_id, text="", done=True, suggest_human=suggest_human,
    citations=citations,
))
```

**是的，有专门字段承载引用来源。** 字段名 `citations`，挂在 `type=streaming_chunk` 且 `done=true` 的结束帧上。

**另一条返回路径**：引用同时落库，`src/websocket/routes.py:836-840`

```python
await asyncio.to_thread(
    message_save, session_id, tenant_id, user_id, "assistant",
    final_response, intent=intent or "",
    metadata={"quality_score": quality_score, "citations": citations},
)
```

所以引用来源既通过 WebSocket 实时返回前端，也持久化到 PG 的消息 metadata 中，支持会话回放时还原引用。

**权限过滤提示的独立通道**（`src/websocket/routes.py:891-899`）

```python
access_filtered = result.get("access_filtered", 0)
if access_filtered > 0:
    await websocket.send_json({
        "type": "info",
        "session_id": session_id,
        "text": f"[注：本次检索有 {access_filtered} 条结果因权限不足被过滤]",
        "timestamp": time.time(),
    })
```

这是 `type=info` 的独立消息，不在 citations 内。

### 4.3 引用元数据缺失项

对照任务要求核查的四类元数据

| 要求项 | 是否具备 | 证据 |
|---|---|---|
| 文档名称 | ✅ 具备 | `title` 字段，routes.py:493 |
| 切片 ID | ⚠️ 部分具备 | `doc_id` 字段存在（routes.py:492），但该值来自 `metadata.doc_id`。Chroma 自行生成的主键 UUID 未透出。`src/rag/vector_store.py:160-163` 的注释明确说明「`add_documents` 由底层向量库自行生成主键 UUID，调用方拿不到这些 id」 |
| 页码 | ❌ 不具备 | `_build_citations` 输出结构（routes.py:509-516）中无 page 字段。元数据里也未检索到 page 相关字段 |
| 相似度分 | ✅ 具备 | `score` 字段，routes.py:512 |

页码缺失是合理的，因为切片策略按字符长度切分（`chunk_size=512`），不保留页边界。若要支持页码引用，需在 `src/rag/chunker.py` 或 `src/rag/loader.py` 阶段注入页码元数据。列入改造待办。

---

## 5. 配置项汇总

### 5.1 配置文件清单与位置

| 文件 | 绝对路径 | 作用域 |
|---|---|---|
| 代码默认值 | `C:\Users\hai\enterprise-agent\src\config.py` | 全局基线 |
| 云端环境 | `C:\Users\hai\enterprise-agent\.env` | docker-compose.yml 形态 |
| 内网环境 | `C:\Users\hai\enterprise-agent\.env.intranet` | thermo-chatbot 单容器形态 |
| 内网生产 | `C:\Users\hai\enterprise-agent\deploy\prod\.env.production` | deploy/prod 形态 |
| 内网生产模板 | `C:\Users\hai\enterprise-agent\deploy\prod\.env.production.example` | 模板 |
| 内网编排 | `C:\Users\hai\enterprise-agent\deploy\prod\docker-compose.prod.yml` | 编排 |
| 云端编排 | `C:\Users\hai\enterprise-agent\docker-compose.yml` | 编排 |
| 监控栈 | `C:\Users\hai\enterprise-agent\docker-compose.monitoring.yml` | 监控 |

### 5.2 RAG 相关配置项全表

| 配置 key | 文件:行 | 代码默认值 | 内网实际值 | 说明 | 离线合规 |
|---|---|---|---|---|---|
| `rag_service_url` | `src/config.py:84` | `http://localhost:8001` | 未设 | 远程 RAG 服务地址 | ✅ 本地 |
| `rag_service_timeout` | `src/config.py:85` | `10.0` | 未设 | HTTP 超时 | ✅ |
| `vector_store_backend` | `src/config.py:64` | `chroma` | `chroma`（`.env.intranet:28`） | 向量库后端 | ✅ 本地 |
| `chroma_persist_dir` | `src/config.py:57` | `./chroma_data` | `/app/chroma_data`（compose:37） | 持久化目录 | ✅ 本地卷 |
| `chroma_collection_name` | `src/config.py:58` | `knowledge_base` | 未设 | 集合名 | ✅ |
| `milvus_host` / `milvus_port` | `src/config.py:61-62` | `localhost` / `19530` | 未设 | Milvus 地址（可选路径） | ✅ 本地 |
| `embedding_provider` | `src/config.py:32` | `openai` | `openai`（`.env.intranet:20`） | provider 名 | ✅ 名字通用 |
| `embedding_model` | `src/config.py:30` | `text-embedding-v4` | `bge-m3`（`.env.intranet:21`） | 嵌入模型 | ⚠️ 默认值指向云端 |
| `embedding_dimensions` | `src/config.py:31` | `1024` | `1024` | 向量维度 | ✅ |
| `embedding_api_base` | `src/config.py:35` | `""`（空，回落 `openai_api_base`） | 未设 | 嵌入独立端点 | ⚠️ 回落目标含外网 |
| `embedding_api_key` | `src/config.py:36` | `""` | 未设 | 嵌入独立密钥 | ✅ |
| `chunk_size` | `src/config.py:88` | `512` | 未设 | 切片长度 | ✅ |
| `chunk_overlap` | `src/config.py:89` | `64` | 未设 | 切片重叠 | ✅ |
| `retrieval_top_k` | `src/config.py:90` | `5` | 未设 | 召回条数 | ✅ |
| `retrieval_rerank_top_n` | `src/config.py:91` | `3` | 未设 | 补检条数 | ✅ |
| `retrieval_min_tokens` | `src/config.py:92` | `200` | 未设 | 低置信度阈值 | ✅ |
| `retrieval_vector_only` | `src/config.py:96` | `False` | `true`（`.env.intranet:38`） | 纯向量模式 | ✅ |
| `retrieval_source_cap` | `src/config.py:102` | `2` | `2`（compose:54） | 单源片段上限 | ✅ |
| `rewrite_enabled` | `src/config.py:105` | `True` | `true`（compose:52） | 查询改写开关 | ✅ |
| `doc_weights` | `src/config.py:108-114` | 5 条文件名权重 | 同（compose:53） | 文档权重 | ✅ |
| `kb_similarity_threshold` | `src/config.py:116-118` | `0.2` | 未设 | 相似度阈值 | ✅ |
| **`kb_call_mode`** | `src/config.py:119-121` | `"always"` | 未设 | **调用模式，无消费点** | ⚠️ 假开关 |
| `kb_weights` | `src/config.py:122` | `""` | 未设 | 多知识库权重 | ✅ |
| `rerank_enabled` | `src/config.py:124-126` | **`False`** | 未设 | 重排序总开关 | ⚠️ 见下 |
| `rerank_provider` | `src/config.py:128` | **`dashscope`** | 未设 | 重排序 provider | ❌ 默认外网 |
| `rerank_model` | `src/config.py:130` | `gte-rerank` | 未设 | 重排序模型 | ❌ 默认外网 |
| `rerank_top_n` | `src/config.py:131` | `5` | 未设 | 重排后条数 | ✅ |
| `openai_api_base` | `src/config.py:29` | **百炼地址** | `http://ollama:11434/v1` / `http://127.0.0.1:11434/v1` | LLM + Embedding 端点 | ❌ 默认外网，已覆盖 |
| `openai_api_key` | `src/config.py:28` | `""` | `ollama` | 密钥占位 | ✅ 占位值 |
| `llm_model` | `src/config.py:37` | `qwen-plus` | `qwen2.5:7b` | 主模型 | ⚠️ 默认值指向云端 |
| `llm_complex_model` | `src/config.py:38` | `qwen-max` | `qwen2.5:7b` | 复杂任务模型 | ⚠️ 默认值指向云端 |
| `langsmith_tracing` | `src/config.py:47` | **`True`** | `false`（compose:56） | 外部追踪 | ❌ 默认外网，已覆盖 |
| `langsmith_api_key` | `src/config.py:45` | `""` | 未设 | 外部追踪密钥 | ✅ 空值 |
| `reflect_enabled` | `src/config.py:138` | `True` | `false`（`.env.intranet:36`） | 反思节点 | ✅ |
| `agent_minimal_tools` | `src/config.py:141` | `False` | `true`（`.env.intranet:33`） | 最小工具集 | ✅ |
| `max_reasoning_turns` | `src/config.py:134` | `5` | 未设 | 最大推理轮次 | ✅ |
| `storage_backend` | `src/config.py:155` | `auto` | `sqlite` / `auto` | 存储后端 | ✅ 本地 |

### 5.3 关键判定

**RAG 功能总开关**：**不存在**。`kb_call_mode` 是唯一候选，但无消费点（详见 2.3 节）。

**Chroma 连接配置**：无网络地址概念，Chroma 以嵌入式方式运行在应用进程内，通过 `persist_directory` 访问本地文件（`src/rag/vector_store.py:53-57`）。集合名 `knowledge_base`（`src/config.py:58`）。

**Ollama 配置**：

- 内网 `.env.intranet:15` `OPENAI_API_BASE=http://ollama:11434/v1`
- 内网生产 `deploy/prod/docker-compose.prod.yml:33` `OPENAI_API_BASE=http://127.0.0.1:11434/v1`（ollama 与 app 同容器，故用回环地址）
- LLM 模型 `qwen2.5:7b`，嵌入模型 `bge-m3`
- 容器内模型卷 `prod-ollama-models:/home/appuser/.ollama`（compose:72）

**检索参数**：top_k=5，相似度阈值=0.2，重排序默认关闭。

**外网地址配置**：8 处，见 3.6 节表格。

**一处需要特别标记的配置不一致**

`deploy/prod/.env.production:10` 中的 `JWT_SECRET` 为明文固定值

```
JWT_SECRET=<出厂默认占位弱口令，已于 Phase3 替换为 48 字节随机值>  # [必须修改]
```

文件中已注明「[必须修改]」，`src/config.py:49-53` 也对此有设计说明。这不是 RAG 问题，但属于内网上线前必须处理的项。

---

## 6. 代码层面缺失项与风险点

按严重度排序。

### 6.1 高风险

**R1. RAG 功能总开关缺失（假开关）**

`kb_call_mode` 在 `src/config.py:119` 定义、在 `src/config_center/schema.py:128` 注册为可热更配置，但无任何业务代码读取。配置中心界面能改、改完无效果。

危害在于排查误导。运维看到开关存在，会假定它生效；实际检索行为由 LLM 的 ReAct 决策支配，开关改变不了任何东西。

**R2. 外网地址硬编码在代码默认值层**

`src/config.py:29`、`src/rag/reranker.py:130`、`src/websocket/multimodal.py:159`、`src/rag/vision_engines/qwen_vision_engine.py:53` 四处把百炼地址写进代码，而非配置项。

`src/rag/reranker.py:130` 尤其需要注意，它连配置回退都不走

```python
self.api_base = api_base or "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

虽然调用方 `src/rag/retriever.py:707-712` 传了 `api_base=settings.openai_api_base`，内网时该值为 Ollama 地址，所以实际会用到本地。但回退值本身是外网地址，属于「靠上游传参正确」的隐式约定。

**R3. 无离线模式断言 / 启动自检**

代码层没有任何机制校验 `openai_api_base` 是否指向内网。漏配环境变量时，系统会尝试访问百炼并超时，错误信息不会指向配置问题。这是内网部署中最典型的一类「配错但不知道为什么错」。

**R4. `deploy/prod/.env.production` 含明文 JWT 密钥**

见 5.3 节。文件中已标注需修改，但当前值仍为可预测的固定字符串。

### 6.2 中风险

**R5. 依赖装配失败时静默降级**

`src/agent/tools.py:960-961` 对 `retriever is None` 返回「知识库当前不可用。请转人工客服。」而非抛出异常。运行期表现为业务降级，日志中无 ERROR 级记录，排查时容易误判为知识库缺内容。

**R6. 相似度阈值的作用范围不完整**

阈值仅在向量召回侧生效（`src/rag/retriever.py:435/441/456/565`），RRF 融合后未再过滤。BM25 召回的文档完全不受阈值约束。低质量 BM25 命中可能通过 RRF 进入最终上下文。

**R7. 重排序的三条 provider 路径中，默认那条依赖外网**

`rerank_enabled` 默认 `False`，当前安全。但 `rerank_provider` 默认 `dashscope`，内网配置未覆盖该项。一旦有人在配置中心把 `rerank_enabled` 打开，系统立即外呼百炼 gte-rerank。这是一个「今天没事、明天可能爆」的配置组合。

BGE 本地路径已存在（`src/rag/reranker.py:286-290` 的 `local_bge` 分支），改造时把 `rerank_provider` 改为 `local_bge` 即可闭环。

**R8. 检索是否发生无法从外部观测确定**

存在三条可能产生检索结果的路径

1. LLM 主动调用 `search_knowledge_base`
2. `rag_node` 的引用补检（`src/graph/nodes.py:952-997`）
3. `faq_node` 未命中后路由到 `rag_node`

前两条的触发条件不同，但最终都写入 `retrieved_docs`。仅凭输出无法反推哪条路径生效。工具层有结构化日志 `kb_search_done`（`src/agent/tools.py:988-996`）可区分路径 1，但补检路径只有 INFO 级日志（`src/graph/nodes.py:991-995`）。

**R9. `kb_call_mode` 枚举值定义前后不一致**

`src/config.py:120` 说明为 `always` / `smart`，`src/config_center/schema.py:128` 定义为 `("auto", "always", "never")`。同一字段两套可选值。

**R10. 引用元数据缺页码**

见 4.3 节。切片按字符长度切分，不保留页边界，故无法提供页码。

### 6.3 低风险 / 优化项

**R11. 补检路径的伪相似度语义混淆**

`src/graph/nodes.py:981-987` 注入 `1/(rank+1)` 作为伪分数，与真实相似度混在同一字段 `score` 中，前端无法区分。取值区间重叠（真实分可能恰为 1.0 / 0.5）。

**R12. 本地库缺少 `knowledge_base` 集合**

本地 `chroma_data` 仅有 `knowledge_base_sentences` 与空的 `long_term_memory`，无默认集合 `knowledge_base`。需确认标准粒度检索在本地形态下是否正常，是否所有切片都走了句子粒度路径。

**R13. 检索日志的 `hit_count` 未区分过滤前后**

`src/agent/tools.py:992` 记录 `hit_count = len(results)`，这是过滤后的最终条数。无法从日志判断召回多少、被阈值或权限滤掉多少。

**R14. 版本冲突处理的自定义逻辑较复杂**

`src/rag/retriever.py:919-1105` 约 190 行处理版本冲突与版本排序，含 `_extract_versions` / `_version_to_sort_key` / `_sort_versions` / `_get_latest_active_version`。自定义版本号解析逻辑是潜在 bug 源，且不易通过简单用例覆盖。

---

## 7. 内网离线改造待办建议

按优先级排列，每条含改动点与验收方式。

### P0 级（离线合规硬门槛）

| 序号 | 待办 | 改动位置 | 验收方式 |
|---|---|---|---|
| 1 | 把 `openai_api_base` 默认值改为内网地址或空值，强制显式配置 | `src/config.py:29` | 清空 `.env` 启动，确认不发起外网连接 |
| 2 | 把 `rerank_provider` 默认值改为 `local_bge`，`rerank_model` 改为 `BAAI/bge-reranker-base` | `src/config.py:128,130` | 开启 `rerank_enabled` 后确认无外呼 |
| 3 | 移除 `src/rag/reranker.py:130` 的外网硬编码回退值，改为必传或空 | `src/rag/reranker.py:130` | 不传 `api_base` 时抛配置错误而非静默用百炼 |
| 4 | 把 `langsmith_tracing` 默认值改为 `False` | `src/config.py:47` | 默认启动不产生 LangSmith 上报 |
| 5 | 把 `llm_model` / `llm_complex_model` 默认值改为内网模型名 | `src/config.py:37-38` | 默认配置下可直连 Ollama |
| 6 | 增加启动自检，检测 `openai_api_base` 是否指向私网地址，非私网时 WARN 或拒绝启动 | `src/api/server.py` 与 `main.py` 的 startup（**两处入口都要改**） | 故意填外网地址启动，确认有明确提示 |
| 7 | 更换 `deploy/prod/.env.production` 中的 JWT 密钥 | `deploy/prod/.env.production:10` | 用 `openssl rand -base64 48` 生成新值 |

> 第 6 项特别提示：本项目存在双入口，`main.py`（内网一体化入口）与 `src/api/server.py`（完整应用）各有一份 startup 逻辑。历史上已因只改一处造成 `init_db()` 与 `setup_logging()` 缺失。新增 startup 逻辑必须两处同步。

### P1 级（功能完整性）

| 序号 | 待办 | 改动位置 | 验收方式 |
|---|---|---|---|
| 8 | 实现 `kb_call_mode` 的真实语义，或从配置中心移除该字段 | `src/graph/nodes.py` 路由处 + `src/config_center/schema.py:128` | 设为 `never` 时确认不再检索 |
| 9 | 统一 `kb_call_mode` 的枚举值定义 | `src/config.py:120` 与 `src/config_center/schema.py:128` | 两处定义一致 |
| 10 | 补齐 `retriever is None` 的场景日志与告警 | `src/agent/tools.py:960-961` | 装配失败时产生 ERROR 日志 |
| 11 | 明确相似度阈值是否需作用于 RRF 融合后结果 | `src/rag/retriever.py:400` 后 | 依据产品决策补过滤或明确注释 |
| 12 | 在工具层日志中区分召回数与过滤后数 | `src/agent/tools.py:988-996` | 日志可还原「召回 N 条、保留 M 条」 |

### P2 级（体验与可观测）

| 序号 | 待办 | 改动位置 | 验收方式 |
|---|---|---|---|
| 13 | 引用元数据补页码，需在载入阶段注入 | `src/rag/loader.py` 或 `src/rag/chunker.py` | `citations` 中出现 page 字段 |
| 14 | 区分真实相似度与补检伪分数，或分字段承载 | `src/graph/nodes.py:981-987`、`src/websocket/routes.py:500-508` | 前端可识别分数来源 |
| 15 | 隔离 `source_ingest.py` 的网页抓取能力，内网形态下禁用 | `src/rag/source_ingest.py:36-39` | 内网模式下调用返回明确禁用提示 |
| 16 | 确认本地 `chroma_data` 缺 `knowledge_base` 集合是否符合预期 | 检索路径排查 | 标准粒度检索在本地可用 |

---

## 8. 待确认问题清单

以下问题无法仅凭代码阅读确定，需人工确认。

| 序号 | 问题 | 为什么无法确定 | 建议确认方式 |
|---|---|---|---|
| 1 | `prod-agent-chroma` 卷的真实数据基线（描述称 14 切片 + 2 长期记忆 = 16） | 读取该卷内容必须启动容器，本次受只读约束禁止 | 下次允许启动时执行 `docker run --rm -v prod-agent-chroma:/data alpine sh -c "ls /data"`，再用只读 sqlite 查 |
| 2 | 本地 `chroma_data` 实测为 956 块（`knowledge_base_sentences`）+ 0 块（`long_term_memory`），且无 `knowledge_base` 集合，与描述不符 | 无法判断哪个是权威基线 | 确认本地库是否为最近一次调试残留；确认内网基线取自哪个卷 |
| 3 | 监控栈 4 个容器为何处于运行状态，是否影响后续停机维护 | 无法从代码判断运维意图 | 与运维确认监控栈是否应纳管 |
| 4 | 相似度阈值不过滤 RRF 融合后结果是设计选择还是疏漏 | 代码无注释说明 | 依据产品检索质量要求判定 |
| 5 | `kb_call_mode` 的 `always` / `smart` / `auto` / `never` 哪套枚举为准 | 两处定义冲突 | 确认设计意图后统一 |
| 6 | 内网形态下 `rag_service_url`（`http://localhost:8001`）是否被使用 | 单容器形态下未启动独立 rag-service 容器，但 `vector_store_backend` 可为 `remote` | 确认内网部署是否走 remote 模式 |
| 7 | 引用是否需要页码 | 属产品需求，代码无法回答 | 与产品确认引用展示规格 |
| 8 | `_rerank_init_failed` 置位后进程内永久关闭重排序，是否符合预期 | 设计意图不明 | 确认是否需支持重试 |
| 9 | 版本冲突处理逻辑（约 190 行）的测试覆盖情况 | 本次未读测试文件 | 单独核查 `tests/` 中相关用例 |
| 10 | `.env`（云端）当前内容是否为内网改造后的残留 | 未读取该文件内容（含密钥，按安全惯例不展开） | 人工核对 |

---

## 附录 A：本次执行的方法与命令

**只读保证说明**

- 使用的读取手段：`ls` / `wc -l` / `grep`（检索定位）、文件 Read、`docker ps -a` / `docker volume ls`（查询类子命令）、`sqlite3` 以 `mode=ro` URI 只读打开本地 chroma 库
- 未执行：`docker compose up/start/restart/build`、`docker run`、任何文件写入（除本报告）、任何 `rm` / `mv` / `rename`
- 唯一新增文件：本报告

**关键命令与预期输出对照**

| 命令 | 预期关键输出 | 典型报错 |
|---|---|---|
| `docker ps -a` | 表头 `CONTAINER ID IMAGE ... STATUS NAMES`，含 `agent-grafana` 等 4 个 `Up (healthy)` | `error during connect: ... The system cannot find the file specified` 表示 Docker Desktop 未启动 |
| `docker volume ls` | 含 `prod-agent-chroma` 行 | 同上 |
| `ls src/` | 列出 `api/ graph/ rag/ websocket/ config.py` 等 | `No such file or directory` 表示工作目录不对 |
| `grep -rn "/ws/chat" src/` | `src/websocket/routes.py:101` | 无输出表示路径过滤过严 |
| 只读 sqlite 查 collections | 2 行，`knowledge_base_sentences` 与 `long_term_memory` | `no such table: collections` 表示打开的不是 Chroma 库 |

**已知环境坑（供下次复用）**

1. 本沙箱 Bash 的 PATH 会混入 Windows 风格条目导致 coreutils 失效，命令前需补 `export PATH="/usr/bin:/bin:$PATH"`。
2. 全仓库 grep 会扫到 `node_modules/` 与 `venv/` 导致 30 秒超时。检索时限定 `src/`、`tests/`、`scripts/` 等目录。
3. `docker cp` 与 Windows 原生程序不认 Git Bash 的 `/c/...` 路径，需传 `C:/...` 形式。

---

## 附录 B：核心调用链关键行号索引

```
src/websocket/routes.py:101      @router.websocket("/ws/chat")
src/websocket/routes.py:114      _resolve_ws_identity()  身份解析
src/websocket/routes.py:140      create_session()        建会话
src/websocket/routes.py:478      _build_citations()      引用组装
src/websocket/routes.py:520      _handle_ai_chat()       消息主处理
src/websocket/routes.py:573      get_workflow()          取工作流
src/websocket/routes.py:624      AgentState(...)         构造状态
src/websocket/routes.py:669      app.invoke()            执行图
src/websocket/routes.py:750      citations = _build_citations(...)
src/websocket/routes.py:819      done 帧带 citations     回传前端
src/websocket/routes.py:839      message_save metadata   引用落库

src/graph/workflow.py:38         _decide_route()         意图路由
src/graph/workflow.py:50         _decide_after_faq()     FAQ 未命中升级
src/graph/workflow.py:69         partial 绑定 retriever  依赖注入
src/graph/workflow.py:136-141    边定义 rag→reflect→reply

src/graph/nodes.py:537           router_node()           意图判定
src/graph/nodes.py:660           human → technical 改写
src/graph/nodes.py:777           rag_node()              RAG 节点
src/graph/nodes.py:826           CustomerServiceAgent()  构造 Agent
src/graph/nodes.py:841           run_with_trace()        ReAct 执行
src/graph/nodes.py:938           _extract_retrieved_docs()
src/graph/nodes.py:952-997       引用补检（兜底检索）
src/graph/nodes.py:1092-1099     return 含 retrieved_docs

src/agent/tools.py:946           search_knowledge_base() 检索工具
src/agent/tools.py:957           权限检查
src/agent/tools.py:970-974       top_k 读配置
src/agent/tools.py:976-982       retriever.search()
src/agent/tools.py:1005-1014     拼 prompt 上下文
src/agent/tools.py:1112          工具注册

src/rag/retriever.py:275         search()
src/rag/retriever.py:314         search_with_scores()    主流程
src/rag/retriever.py:350         向量检索 top_k*2
src/rag/retriever.py:353-356     BM25（vector_only 控制）
src/rag/retriever.py:366         RRF 融合
src/rag/retriever.py:384-385     重排序
src/rag/retriever.py:389-391     权限过滤
src/rag/retriever.py:400         版本冲突处理
src/rag/retriever.py:584-608     _filter_by_similarity()
src/rag/retriever.py:614-650     _rrf_fusion(k=60)

src/rag/vector_store.py:17-19    集合名与持久化目录
src/rag/vector_store.py:20       Embedder 注入
src/rag/vector_store.py:101-127  Chroma 带分检索

src/rag/embedder.py:29-66        provider 分支
src/rag/embedder.py:82-98        dimensions 参数降级

src/config.py:29                 外网 base URL 默认值
src/config.py:119                kb_call_mode（无消费点）
src/config.py:124-126            rerank_enabled 默认 False
src/config.py:128                rerank_provider 默认 dashscope
```

---

*报告结束。本次作业全程只读，未修改业务代码、未启停容器、未改动配置。*
