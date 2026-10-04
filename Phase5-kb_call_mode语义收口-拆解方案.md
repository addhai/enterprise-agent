
# Phase5 拆解方案：kb_call_mode 语义收口

- 项目：enterprise-agent（工业知识库 AI Agent，内网全离线）
- 代码基线：`C:\Users\hai\enterprise-agent`（行号取自当前源码实时读取，非历史报告转述）
- 版本：v1.0 冻结（2026-09-22）——三模式判据、生产默认值、非法值回落目标均已拍板，§2/§5 冻结后作为实施契约
- 前置状态：Phase4b 已收官（生产部署套件 7 文件入库、工作区干净、明文凭据扫描通过）
- 用途：明确 kb_call_mode 现状基线 → 语义定义 → 改动范围 → 验收口径 → 与后续两项（rerank 固化、页码/章节展示）的依赖，作为实施与验收依据

---

## 0. 基线修正（必须先看，结论与旧判断不同）

旧判断"三模式语义可能不真实、只是透传"——**实测不成立**。`kb_call_mode` 在 Phase3 离线改造时已实现真三分支，且有测试覆盖：

| 事实 | 证据 |
|---|---|
| 已是真开关，非透传 | `src/config.py:120-126`（定义，默认 `always`）；`src/graph/nodes.py:1098`（唯一消费点读取） |
| 三值均为真实分支 | `never` 短路直答 `nodes.py:1104-1135`；`always` 强制预检索 `nodes.py:1137-1162`；`smart` 走 Agent 自主决策 `nodes.py:1164+` |
| 已有测试覆盖三模式 + 非法值 | `tests/test_graph/test_nodes_llm.py:345 / 369 / 406 / 432`；接口层枚举校验 `tests/test_api/test_config_center.py:252` |
| `src/` 全量检索仅 4 个文件命中 | `config.py`、`config_center/{schema,categories,service}.py`、`graph/nodes.py`，无第二消费点 |

> 仓库内历史报告（`docs/`、旧验收报告）中"kb_call_mode 是死配置"的定性已过时，**不可再引用**，一律以本次实时基线为准。

**因此 Phase5 主线的真实工作量不是"从零实现语义"，而是"把已有三模式从不严谨的语义收紧为可定义、可观测、可验收的语义"**，即补齐四个缺口：

1. **smart 是语义黑洞**：无任何程序化判据，检索与否完全交给 ReAct Agent（工具 `search_knowledge_base`，`src/agent/tools.py:946`，提示词引导 `src/agent/prompt.py:30`）。7B 小模型下不可预测、不可单测、不可回归——"地基不稳"的真实位置。
2. **默认值与生产口径未定**：代码默认 `always`，但 `deploy/prod/.env.production` 与根 `.env` 中均**无 `KB_CALL_MODE` 键**，生产实际行为是隐性默认值，会随代码改动静默漂移（Phase4b 已踩同类坑：写进 env 不等于注入容器）。
3. **非法值回落方向可疑**：`nodes.py:1099-1101` 非法值回落 `smart`（最不确定的分支）。安全方向应为回落到行为最确定的模式。
4. **always 复用边界未定**：预检索结果按 `page_content[:100]` 去重后并入 `retrieved_docs`（`nodes.py:1289-1302`），但 Agent 仍可二次检索 → 检索次数上界、内容级去重口径均未定义（本次已补，见 §2.5）。

### 0.1 拍板结论摘要（2026-09-22 冻结）

| # | 议题 | 冻结结论 |
|---|---|---|
| 1 | smart 判据信号 | **A + C 组合**：规则前置短路 + 探测式分数判定；零外呼、纯函数可单测、不引入额外 LLM 依赖 |
| 2 | 生产默认值 | **`always`**（内网离线检索无外呼成本，溯源确定性最高，漏检风险远大于多检）；`smart` 作可热更成本优化项，不作默认；`never` 不作生产默认 |
| 3 | 非法值回落目标 | **`always`**（与生产默认值对齐，行为最可预测）；同步改测试断言（`test_nodes_llm.py:432`）与告警文案 |
| 4 | always 复用边界 | 内容级去重 + 检索次数软上限 3 次 + 超限 warn（见 §2.5） |
| 5 | 探测式语义 | 探测即"正式检索的第一次调用"，结果直接复用，**不做二次检索**（见 §2.2.2） |

---

## 1. 现状基线（行号级）

### 1.1 配置层与调用链

| 环节 | 位置 | 内容 |
|---|---|---|
| 定义/默认值 | `src/config.py:120-126` | `kb_call_mode: str = "always"`，注释区分三语义 |
| 枚举校验 | `src/config_center/schema.py:128-130` | `("always", "smart", "never")`，注明"原 auto 等价 smart" |
| 分类/热更新 | `src/config_center/categories.py:30` | 归入 `retrieval`，支持热更新 |
| 热更新落点 | `src/config_center/service.py:334` | `setattr(settings, field_name, new_value)`，改完即生效、无需重启 |
| 节点装配 | `src/graph/workflow.py:70-71`、`:97`；`src/graph/workflow_dag.py:286` | `partial(rag_node, ...)` → `add_node("rag", ...)` |
| 生产 env | `deploy/prod/.env.production`、根 `.env` | 无 `KB_CALL_MODE` 键（未显式配置） |

### 1.2 分支行为

| 模式 | 位置 | 行为 |
|---|---|---|
| 校验 | `nodes.py:1098-1102` | strip/lower 归一；非法值 warning 后回落 `smart`；打 `[kb_call_mode=%s] 检索策略已应用` 日志 |
| `never` | `nodes.py:1104-1135` | 不构建 Agent、不检索；自建 `ChatOpenAI` 依据对话历史直答；异常置空 → `answer_status="refused"`；`retrieved_docs=[]`，直接 return |
| `always` | `nodes.py:1137-1162` | Agent 构建前 `retriever.search(...)`，`top_k` 钳制 1-50；失败 warning 后回落"LLM 自主决策" |
| `always` 并回 | `nodes.py:1289-1302` | `page_content[:100]` 去重后并入 `retrieved_docs` |
| `smart` | `nodes.py:1164+` | 无预检索，直接构建 `CustomerServiceAgent`，检索与否由 LLM 决定 |
| 尾部补检 | `nodes.py:1317-1350` | Agent 跑完仍无文档 → 再检索一次（条数取 `retrieval_rerank_top_n`，默认 3，钳制 1-20），异常仅 debug |

### 1.3 降级链现状（4 条）

1. 非法配置值 → 回落 `smart`（`nodes.py:1099-1101`）→ **本次改为回落 `always`**
2. `always` 预检索异常 → 回落 LLM 自主决策（`nodes.py:1158-1162`）
3. `never` 作答异常 → 置空并标 `refused`（`nodes.py:1125-1135`）
4. Agent 无文档 → 尾部引用补检（`nodes.py:1317-1350`）

### 1.4 后续两项现状（决定依赖关系）

**rerank 固化：已基本达成，剩余量小。**

| 环节 | 位置 | 状态 |
|---|---|---|
| 开关/Provider/模型路径默认值 | `src/config.py:145-153` | `rerank_enabled=True`、`local_bge`、`/app/models/bge-reranker-base` |
| 权重随镜像预置 | `Dockerfile:71` | `COPY models/bge-reranker-base` |
| 离线约束 | `Dockerfile:73-74` | `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` |
| 开关实时读取（避免假热更新） | `src/rag/retriever.py:813-818` | property 实时读 `settings.rerank_enabled` |
| 三级降级 | `retriever.py:799-807`、`reranker.py:59-66`、`retriever.py:860-862` | init 失败禁用 / 打分异常保序 / 调用异常保序 |
| 剩余缺口 | `src/rag/reranker.py:178-181` | docstring 仍写"首次加载需下载模型"，与预置+离线口径不一致（仅文档性偏差） |
| 剩余缺口 | `deploy/prod/.env.production` | 无 `RERANK_MODEL` 键（走代码默认容器路径，可用但口径未显式固化） |

**页码/章节展示：page 已通，chapter_path 断层。**

| 环节 | 位置 | 状态 |
|---|---|---|
| `page` 产出 | `src/rag/loaders/pdf_loader.py:52-55`、`:141` | 已产出（按页标记累计） |
| `page` 透出 | `src/websocket/routes.py:479`（构建）、`:837`、`:855` | 已进 citations 与会话落库 |
| `page` 前端渲染 | `frontend/src/App.tsx:752-762`、`:1186-1197` | 已渲染（非 PDF 为 `null` 时不显示徽标） |
| `chapter_path` 产出 | `src/rag/outline.py:236`、`src/rag/loaders/docx_loader.py:145` | 切片层已产出 |
| `chapter_path` 透出 | `src/websocket/routes.py:510-520` | **citations 输出字典无该字段 → 到此处被丢弃** |
| `chapter_path` 前端 | `frontend/src/` 全量检索 | **无任何消费** |

> 结论修正：页码项的真实缺口不是"前端没做展示"，而是"章节字段产出→透出断层"；`page` 链路已完整。

---

## 2. 语义定义（实施契约，已冻结）

### 2.1 三模式精确边界

| 维度 | `always` | `smart` | `never` |
|---|---|---|---|
| 是否构建 Agent | 是 | 是 | 否 |
| 是否主动检索 | 是（强制 1 次预检索，Agent 仍可再检） | 由 A+C 判据决定（探测命中即注入） | 否 |
| 检索次数上界 | 软上限 3 次（含预检索；超限 warn，不硬截断） | 软上限 3 次（含探测；超限 warn） | 0 |
| 引用产出 | 必有（检索失败/无命中除外） | 探测命中则有，否则空 | 恒空 |
| 空结果行为 | 保留无引用回答，尾检兜底 | 同左 | 直接 `refused` |
| 对外话术约束 | 可声称查阅知识库 | 同左 | **不得声称查阅知识库/文档** |
| 成本特征 | 最高（≥1 次检索 + Agent） | 中（规则短路时 0 检索） | 最低（1 次 LLM） |
| 适用场景 | **生产默认**、强合规溯源 | 闲聊与专业问答混流、成本敏感（热更开启） | 纯对话/兜底/知识库不可用时降级运行 |

### 2.2 smart 判据：A + C 组合（冻结）

**执行顺序：规则前置短路（A）→ 未短路则探测式判定（C）**

#### 2.2.1 A 段：规则前置短路（零成本，命中即不检索）

| 规则类 | 判定内容 | 命中结果 |
|---|---|---|
| 闲聊/社交 | 问候、致谢、道歉、告别（白名单词表 + 短句判定） | 不检索，`retrieval_decided_by="rule"` |
| 纯操作指令 | 转人工、创建工单、查询工单状态、投诉登记 | 不检索，交由 Agent/工具链处理 |
| 指代承接 | 纯指代短句（如"继续说"、"展开"）且上一轮已有可信引用 | 不检索（复用上轮上下文） |

规则风格沿用项目既有先例（`nodes.py` 中 `_is_resource_query` 的"规则识别、宁可漏放不误放"），实现为零依赖纯函数，**不新增外呼、不加载模型**。

#### 2.2.2 C 段：探测式判定（探测即正式检索，不重复调用）

**语义定义（本次冻结，回答"top1 还是 top-k"与"是否复用"两个问题）**：

- **探测 = 正式检索的第一次调用**：`probe_docs = retriever.search(query, top_k=retrieval_top_k, ...)`，参数与 `always` 预检索完全一致，不引入新配置项。
- **判定信号 = top-k 覆盖率 + top1 双信号**：
  - 主判据（决定是否注入）：`hit_count = |{d ∈ probe_docs : score(d) ≥ kb_similarity_threshold}|`，`hit_count ≥ 1` 即命中（阈值取 `src/config.py:120` 的 `kb_similarity_threshold`，默认 0.2）；
  - 辅助信号（仅日志/可观测，不改变决策）：top1 分数 `probe_docs[0].score`，用于区分"擦边命中"与"高置信命中"。
  - 取 top-k 覆盖率而非仅 top1 的理由：单条高分只证明"存在相关切片"，覆盖率决定可注入的引用条数与回答可支撑度；仅看 top1 会漏掉"高分切片少但确实相关"的场景。
- **复用规则（关键）**：探测已拿到结果 → **判定命中时直接作为 `pre_retrieved_docs` 注入，不再发起第二次检索**；判定未命中时不注入（结果不进上下文、不出引用），`retrieval_decided_by="score_reject"`。
- **计数**：探测计为 1 次检索调用（`retrieval_count=1`），杜绝"一次 query 两次检索"的浪费。
- **未命中后仍保留自主性**：Agent 仍持有 `search_knowledge_base` 工具，可自行再检（计入软上限）；若最终无文档，走既有尾部补检兜底（`nodes.py:1317-1350`）。

#### 2.2.3 判据输出契约

纯函数签名（建议置于新模块 `src/rag/call_policy.py`）：

```
decide_retrieval(question: str, history: list, probe_docs: list | None, config) -> PolicyDecision
PolicyDecision = {should_retrieve: bool, reason: Literal["rule","score","score_reject","fallback","always","never"], hit_count: int, top1_score: float | None}
```

- 输入不含任何网络/模型依赖；`probe_docs=None` 时仅执行 A 段规则。
- 全部判定结果写入日志与回答元数据（见 §2.4），供验收取证。

### 2.3 降级策略（改造后统一口径）

| 触发条件 | 目标行为 | 理由 |
|---|---|---|
| 判据内部异常/超时 | **按 always 处理**（执行检索） | 宁可多检不漏检；工业客服漏检代价 > 多检代价 |
| 探测检索异常 | 回落为不注入、由 Agent 自主决策（保留现有 `always` 预检索异常口径） | 不因探测失败阻断主链路 |
| 检索返回空 / 全部低于阈值 | 不产生引用，回答不得编造来源 | 防止引用幻觉 |
| 配置值非法 | 回落 **`always`**（本次修正，原为 `smart`） | 异常时选行为最确定的路径 |
| `never` 下 LLM 失败 | 保持 `refused`，不静默转检索 | 模式契约不可被降级悄悄破坏 |

### 2.4 可观测性（新增，便于验收取证）

在回答元数据/结构化日志中固化三要素：`kb_call_mode`（生效模式）、`retrieval_decided_by`（`rule` / `score` / `score_reject` / `fallback` / `always` / `never`）、`retrieval_count`（实际检索次数）。
不改 WS 协议必填字段，只落 metadata 与日志，避免前端改造连带。

### 2.5 always 复用边界（缺口 4 收口，冻结）

**问题**：现实现用 `page_content[:100]` 去重（`nodes.py:1289-1302`），截断式键会把"前 100 字符相同、后续不同"的切片误判为重复；且 Agent 二次检索次数无上界。

| 项 | 冻结口径 |
|---|---|
| 去重键 | **内容级去重**：`sha1(normalize(page_content))`，`normalize` = 去除首尾空白 + 折叠连续空白/换行 + 统一全角半角；同时以 `(doc_id, page)` 作辅助键（两者任一命中即视为重复） |
| 冲突处理 | 同键保留 `score` 更高者；分数相同保留先入者，并打 debug 日志 |
| 应用范围 | 预检索/探测结果与 Agent 自主检索结果**合并时**统一去重（合并点即现 `nodes.py:1289-1302`），去重后列表作为 `retrieved_docs` 输出 → citations 自然继承去重结果，无需改 `routes.py` |
| 检索次数软上限 | **同一 query 累计 3 次**（含预检索/探测 1 次 + Agent 自主 ≤2 次 + 尾部补检共用同一计数） |
| 超限行为 | **软上限：允许完成调用，但打 `warning`**，日志含 `retrieval_count`、超限来源（`agent_tool` / `tail_backfill`）与 query 摘要；**本次不做硬截断**（硬截断需在工具层加 per-query 计数，列为可选增强，不在本次范围） |
| 统计方式 | 预检索/探测由节点自计；Agent 自主调用通过回复 `messages` 中工具调用记录（`search_knowledge_base` 的 `AIMessage.tool_calls` 计数）事后统计，复用已有 `_extract_tool_citation_docs` 的同源解析逻辑 |
| 目的 | 让 always 模式的引用质量与延迟可控、可观测，避免"同 query 反复检索"拖长延迟并污染引用 |

---

## 3. 改动范围

| 层 | 文件 | 改动性质 | 说明 |
|---|---|---|---|
| 配置层 | `src/config.py:120-126` | 默认值确认为 `always` + 注释口径对齐 | 与 §5 决策 2 一致 |
| 配置层 | `deploy/prod/.env.production` + compose `app.environment` | 新增显式键 `KB_CALL_MODE=always` + 注入 | **必须同时改 compose `environment:`**，只写 env 不生效（Phase4b 已踩坑） |
| 配置中心 | `schema.py` / `categories.py` | 不变 | 枚举已对齐，热更新已通 |
| 检索路由（新增） | 新文件 `src/rag/call_policy.py` | 新增纯函数判据模块 | A 段规则短路 + C 段分数判定 + 统一 `PolicyDecision`；零外呼、可单测 |
| LangGraph 节点 | `src/graph/nodes.py:1098-1162` | 改造 `smart` 分支 + 非法值回落目标 | `smart`：先 A 段 → 未短路则探测检索 → 命中即注入（复用探测结果）；`always` 保持预检索但**去重与计数口径按 §2.5 收口**；不新增图节点（避免动 `workflow_dag.py:286` 与图拓扑） |
| 合并/去重 | `nodes.py:1289-1302` | 改为内容级去重 + 计数与超限 warn | 见 §2.5 |
| 降级链 | `nodes.py` 四处降级 | 收敛口径 | 见 §2.3 |
| 数据模型 / API | 无变更 | — | `kb_call_mode` 已可热更新；回答元数据仅新增可选字段 |
| 测试 | `tests/test_graph/test_nodes_llm.py`、新增 `tests/test_rag/test_call_policy.py` | 扩展 | 见 §4 |
| 文档 | `deploy/prod/README-生产部署与运维手册.md` | 补三模式口径、默认值与热更新方式 | — |

> **不做的事**（边界声明）：不改检索器内部（RRF/权限过滤/rerank 顺序）、不改前端、不改 WS 协议必填字段、不新增 LangGraph 节点、不引入任何外呼依赖、不做检索次数硬截断。

---

## 4. 验收口径

### 4.1 三模式用例

| # | 用例 | 断言要点 |
|---|---|---|
| 1 | `always` 强制预检索 | Agent 构建前检索次数 ≥1；`top_k` 透传正确；预检索结果去重后进入 `retrieved_docs` 与 citations |
| 2 | `never` 跳过检索 | 检索器零调用；不构建 Agent；`retrieved_docs==[]`；回答不含"知识库/文档"声称；LLM 失败时 `answer_status="refused"` |
| 3 | `never` 不被隐式兜底 | `never` 下即使检索器可用也不产生任何检索调用 |

### 4.2 smart 正反类用例（A+C）

| 类型 | 输入示例 | 期望 |
|---|---|---|
| 反类（规则短路） | "你好"、"谢谢"、"帮我转人工"、纯闲聊 | `decided_by="rule"`，检索器**零调用**，citations 为空 |
| 正类（探测命中） | "XX 报警代码 E1042 怎么处理"、设备型号/参数类提问 | `decided_by="score"`，`hit_count≥1`，注入探测结果，citations 非空且为知识库真实切片 |
| 正类（探测复用） | 同上，mock 打点计数 | **检索调用恰好 1 次**（探测结果被复用，无第二次调用） |
| 边界类（探测未命中） | 知识库外问题 | `decided_by="score_reject"`，不注入结果、无引用、不编造来源 |
| 判据异常类 | 判据抛错/超时（mock） | 回落执行检索，`decided_by="fallback"`，打 warning |

### 4.3 always 复用边界用例（缺口 4）

| # | 用例 | 断言要点 |
|---|---|---|
| 1 | 内容级去重 | 构造"前 100 字符相同、后续不同"的两条切片 → 均保留（旧截断式去重会误删，作为回归对照）；完全相同的切片 → 仅保留分数高者 |
| 2 | 合并去重范围 | 预检索 + Agent 工具返回的同内容切片 → `retrieved_docs` 仅 1 条，citations 同步为 1 条 |
| 3 | 软上限 warn | mock 使检索调用达 4 次 → 第 4 次完成但出现 warning，日志含 `retrieval_count` 与超限来源；**无异常抛出、无调用被阻断** |
| 4 | 计数正确性 | 预检索 1 次 + Agent 自主 2 次 → `retrieval_count=3`，不触发 warn |

### 4.4 回归兼容

- 基线：`1417 passed / 23 skipped / 0 failed`，必须保持不退化。
- 执行口径：`--deselect tests/test_mcp_tools/test_kb_phase2.py` 后全量并行 + 该文件单独串行（隔离 Windows 下 `torch_cpu.dll` 并行崩溃导致 xdist worker errors 的干扰）。
- 报告需区分 `failures`（断言失败）与 `errors`（worker 丢失），后者查事件日志确认 faulting module 再定性，不得计入代码回归。
- `test_nodes_llm.py:432`（非法值回落）断言与告警文案需随决策 3 同步更新为回落 `always`。

### 4.5 生产验证

容器内实测（不只看 env 文件）：
```powershell
docker compose -f deploy/prod/docker-compose.yml exec app sh -c "env | grep KB_CALL_MODE"
docker compose -f deploy/prod/docker-compose.yml logs app | Select-String "kb_call_mode"
```
并验证热更新路径：`PUT /api/v1/config/kb_call_mode` 改值后，下一次问答日志中 `[kb_call_mode=...]` 立即变化、无需重建容器。

---

## 5. 决策记录（2026-09-22 冻结）

| # | 议题 | 决策 | 理由 |
|---|---|---|---|
| 1 | smart 判据信号选型 | **A + C 组合** | 规则前置短路 + 探测式分数阈值；零外呼、纯函数可单测、不引入额外 LLM 依赖，符合内网离线约束 |
| 2 | 生产默认值 | **`always`** | 内网离线检索无外呼成本，溯源确定性最高，漏检风险远大于多检；`smart` 作可热更成本优化项，不作默认 |
| 3 | 非法值回落目标 | **`always`** | 与生产默认值对齐，行为最可预测；同步改测试断言与告警文案 |
| 4 | always 复用边界 | 内容级去重 + 软上限 3 次 + 超限 warn | 边界不定义则引用质量与延迟不可控（见 §2.5） |
| 5 | 探测式语义 | 探测即正式检索的第一次调用，命中即复用 | 避免"一次 query 两次检索"的浪费（见 §2.2.2） |

---

## 6. 与后续两项的依赖关系

| 任务 | 与 kb_call_mode 的耦合 | 并行结论 |
|---|---|---|
| rerank 本地模型固化 | **无代码交叉**：rerank 在 `retriever` 内部（`retriever.py:430-431`），kb_call_mode 在 `nodes` 层 | 可并行，**但待 kb_call_mode 主体代码合入后再启动**，避免 review 交叉 |
| 页码 / 章节展示 | **弱耦合**：`page` 链路已通、无需再动；`chapter_path` 只需在 `routes.py:510-520` 补字段 + 前端补渲染，不触碰检索决策 | 同上 |
| 耦合点（需注意） | smart 改造后会减少检索调用，进而减少 citations 出现频率 → 展示层收益取决于最终默认值 | 默认值已冻结为 `always`，展示层收益口径明确 |

**排期**：kb_call_mode 先行（判据 + 降级 + 生产口径 + 复用边界）→ 主体合入后，rerank 固化与页码/章节展示**并行**收口。

---

## 7. 工作量预估

| 工作项 | 预估 |
|---|---|
| 判据模块 `call_policy.py`（A+C）+ 单测 | 0.5~1 天 |
| `nodes.py` 三分支改造 + 降级口径收敛 + 去重/计数收口 + 日志元数据 | 1~1.5 天 |
| 配置层默认值 + 生产 env/compose 注入 + 热更新实测 | 0.5 天（含容器 recreate） |
| 测试扩展（正/反/边界/异常/去重/上界）+ 1417 回归 | 1 天 |
| 文档口径更新（运维手册） | 0.5 天 |
| 合计 | **3.5~4.5 天**（含回归与生产实测；较 v0 增加，因去重与计数收口纳入本次） |

---

## 8. 开工顺序

1. 冻结本方案 §2 语义契约与 §5 决策记录（已冻结）
2. 新增 `call_policy.py` 与单测（不接节点，先自证 A/C 两段与输出契约）
3. 改造 `rag_node`：smart 分支接入判据、非法值回落改 `always`、去重与计数收口
4. 配置层默认值 + 生产 env/compose 注入 + 容器内实测（含热更新验证）
5. 用例扩展与全量回归（隔离口径）
6. 文档口径收口，标记 Phase5 主线封版
7. 主体合入后启动 rerank 固化与页码/章节展示（并行）
*（内容由AI生成，仅供参考）*