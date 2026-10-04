# Phase 3 热更新实测报告 — LLM 实例重建（llm_temperature / llm_max_tokens）

- 日期：2026-09-15
- 环境：`deploy/prod/docker-compose.prod.yml`（内网单容器）
- 容器：`prod-app-1`，`StartedAt=2026-09-15T14:26:24Z`，`Pid=21778`，全程未重启
- 新增验证资产：`tests/test_agent/test_llm_rebuild_hot_reload.py`（7 项）

---

## 一、结论摘要

| 验收要点 | 结论 | 依据 |
| --- | --- | --- |
| 配置变更后 LLM 实例被重建 | 通过 | 同一 Agent 实例上 `id(llm)` 变化 |
| 新实例携带新参数值 | 通过 | 新实例 `temperature=0.2`、`max_tokens=512` |
| 不重启容器 | 通过 | 四次 PUT 前后 `StartedAt` 与 `Pid` 完全一致 |
| 审计日志有记录 | 通过 | 两个参数各 2 条，含旧值/新值/操作人/时间 |
| 配置已复原 | 通过 | `0.0` / `2048` |
| `max_reasoning_turns` 一并验证 | 通过 | 走另一条链路（非重建），已验证（见第八节） |

**三处与任务单预期不符，其中第二处直接挡住了任务本身**，详见第七节。

---

## 二、初始配置值

### 2.1 任务单给的键名不存在

| 任务单的键名 | 实际结果 |
| --- | --- |
| `GET /api/v1/config/temperature` | **404** |
| `GET /api/v1/config/max_tokens` | **404** |

实际键名带 `llm_` 前缀。

### 2.2 实际初始值

| 配置项 | 值 | 默认值 | hot | 类型 | 约束 |
| --- | --- | --- | --- | --- | --- |
| `llm_temperature` | **0.0** | 0.0 | true | float | 0.0 ~ 2.0 |
| `llm_max_tokens` | **2048** | 2048 | true | int | 1 ~ 32768 |
| `max_reasoning_turns` | 5 | 5 | true | int | 1 ~ 20 |

注意：`llm_temperature` 的默认是 **0.0**，不是任务单示例里的 0.7。

---

## 三、重建代码路径（文件:行号）

全部在 `src/agent/agent.py`：

| 行号 | 内容 | 作用 |
| --- | --- | --- |
| 71 | `def _build_llm_and_agent(self) -> None:` | 按当前配置构造 LLM 与内部 agent |
| 84-90 | `llm_kwargs = {..."temperature": settings.llm_temperature, "max_tokens": settings.llm_max_tokens}` | **读取配置的准确位置** |
| 91 | `self.llm = ChatOpenAI(**llm_kwargs)` | LLM 实例构造 |
| 92 | `self.agent = create_agent(self.llm, ...)` | 内部 agent 一并重建 |
| 98 | `self._llm_config_version = get_config_center().version` | **记录本次构造所用的配置版本** |
| 102 | `def _ensure_llm_current(self) -> None:` | **重建的触发点** |
| 114 | `current = get_config_center().version` | 取当前版本号 |
| 117 | `if current != getattr(self, "_llm_config_version", -1):` | **版本比对（检查点）** |
| 119 | `self._build_llm_and_agent()` | **版本变化时触发重建** |
| 141 | `self._ensure_llm_current()`（`run()` 开头） | 入口一 |
| 225 | `self._ensure_llm_current()`（`run_with_trace()` 开头） | 入口二（图实际走的这条） |

---

## 四、多层缓存链路分析（任务单特别要求）

任务单问「Agent 对 LLM 实例是否有多层缓存，逐层确认哪一层在重建」。实测结论与预期不同，**这一节请务必看**：

| 层 | 是否缓存 | 说明 |
| --- | --- | --- |
| 图节点 → `CustomerServiceAgent` | **不缓存** | `src/graph/nodes.py:826` 在**节点函数体内**构造，每次图调用都新建。全仓无 `lru_cache`、无模块级单例、无依赖注入缓存 |
| `CustomerServiceAgent.llm`（ChatOpenAI） | 随 Agent 一起新建 | 构造时直接读当时的 settings |
| `CustomerServiceAgent.agent`（内部 LangGraph agent） | 同上层 | `create_agent` 在 `_build_llm_and_agent` 中一并重建 |
| `_ensure_llm_current()` | 兜底 | **仅当同一个 Agent 实例被复用多次时才起作用** |

### 这意味着什么

图路径上「改配置生效」的真正原因是：**每次请求都新建 Agent，构造时自然读到最新配置**。`_ensure_llm_current()` 在这条路径上不是必要条件。

而任务单的关键判据「`id()` 变化」在图形路径上**会无意义地通过**，因为每次调用本来就换新对象。所以本报告用另一种方式验证重建逻辑：**只保留一个 Agent 实例，中途改配置，再触发**。此时 `id()` 变化才有意义。

保留 `_ensure_llm_current()` 仍有价值：它覆盖「实例被复用」的场景（例如测试替身、未来若把 Agent 改为单例、或 A2A / worker 等长生命周期调用方）。当前生产路径没有这种用法。

---

## 五、进程内测试结果

`tests/test_agent/test_llm_rebuild_hot_reload.py`，7 项全过：

```
tests/test_agent/test_llm_rebuild_hot_reload.py .......  7 passed
```

### 5.1 重建与参数生效

| 测试 | 参数 | 旧值 | 新值 | 旧实例 id | 新实例 id | 是否重建 | 新参数是否生效 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `test_temperature_change_rebuilds_llm_with_new_value` | `llm_temperature` | 0.0 | 0.2 | 不同 | 不同 | **是** | **是**（0.2） |
| `test_max_tokens_change_rebuilds_llm_with_new_value` | `llm_max_tokens` | 2048 | 512 | 不同 | 不同 | **是** | **是**（512） |
| `test_sequence_and_restore` | `llm_temperature` | 0.0 | 0.2 → 0.9 → 0.0 | 每轮都不同 | 每轮都不同 | 三次全部重建 | **是**（0.2 / 0.9 / 0.0） |

> 说明：`id()` 的具体数值每次运行都不同（Python 对象地址），因此表中以「是否不同」呈现，这才是稳定可断言的判据。

### 5.2 关键反例（防止「无条件重建」蒙混过关）

| 测试 | 场景 | 断言 | 结果 |
| --- | --- | --- | --- |
| `test_no_config_change_means_no_rebuild` | 配置未改动，仅调用 `_ensure_llm_current()` | `id(llm)` **不变** | 通过 |

这一条很重要：它证明重建是**版本驱动**的，而不是每次调用都无脑重建。如果没有这条，上面的「id 变了」也可能只是「每次都重建」造成的假象。

### 5.3 集成路径与副作用

| 测试 | 断言 | 结果 |
| --- | --- | --- |
| `test_rebuild_happens_through_run_with_trace` | 走 `run_with_trace()`（图实际入口）也会触发重建，且新值为 0.7 | 通过 |
| `test_rebuild_does_not_lose_tenant_or_user` | 重建只换 LLM 与内部 agent，`user_id` / `tenant_id` 不丢 | 通过 |

### 5.4 走查到的链路细节

`_ensure_llm_current()` 中若重建失败（例如配置被改成不支持的模型名），代码会保留旧客户端并把版本号记为已处理，避免每次请求反复重试。这一点未单独构造失败用例，属已知未覆盖项。

---

## 六、API 层切换与容器状态

| 操作 | 接口响应 | 进程内回读 | 容器 StartedAt / Pid |
| --- | --- | --- | --- |
| 改动前 | — | 0.0 / 2048 | `14:26:24Z` / `21778` |
| PUT `llm_temperature` = 0.7 | old=0.0 new=0.7 version=1 | **0.7**（by admin-default） | 未变 |
| PUT `llm_max_tokens` = 1024 | old=2048 new=1024 version=2 | **1024**（by admin-default） | 未变 |
| PUT `llm_temperature` = 0.0（复原） | old=0.7 new=0.0 version=3 | 0.0 | 未变 |
| PUT `llm_max_tokens` = 2048（复原） | old=1024 new=2048 version=4 | 2048 | 未变 |
| 改动后 | — | 0.0 / 2048 | `14:26:24Z` / `21778` |

配置版本号 1→4 递增，回读值逐次跟随，容器自始至终同一进程。

---

## 七、与预期不符的三处

### 7.1 键名带 `llm_` 前缀

`temperature` / `max_tokens` 都是 404，实际是 `llm_temperature` / `llm_max_tokens`。

### 7.2 【阻塞性缺陷】`llm_max_tokens` 曾被误判为敏感字段，根本无法修改

这是本轮最值得记录的问题。初始状态下：

```
GET  /api/v1/config/llm_max_tokens
     -> {"is_sensitive": true, "value": "", "configured": true}

PUT  /api/v1/config/llm_max_tokens   {"value": 512}
     -> HTTP 400  字段 llm_max_tokens 属敏感配置，不提供在线修改接口
```

任务单第 3 步要求「改 `max_tokens` 从 1024 改为 512」，**在当前代码下无法完成**。

**根因**：敏感字段判定用的是**子串匹配**，关键词表里有 `token`，而 `llm_max_tokens` 含该子串，于是被当作凭据。同理 `retrieval_min_tokens` 也被误判。

**影响**：这两个字段既读不到值（被脱敏成空串），也不允许在线修改，配置中心对它们形同虚设。而它们恰恰是常见的调参对象。

**修复**：把子串匹配改为**按 `_` 切词的整词匹配**。切词后 `llm_max_tokens` → `[llm, max, tokens]`，`tokens` 是复数计量词，不命中；而 `openai_api_key` → `[openai, api, key]` 仍命中，凭据防护不受影响。

**改动前做了影响面核对**（避免安全回退）：

| 项 | 结果 |
| --- | --- |
| 原被判敏感的字段 | `llm_max_tokens`、`retrieval_min_tokens`（仅此 2 个，均为 int，默认 2048 / 200） |
| 改后仍判敏感的字段 | 0 个（可更新白名单里本就不含凭据） |
| 从「非敏感」变为「敏感」的字段 | **无** |

**顺带收敛了重复实现**：同一规则原先散落在 `src/api/config.py`、`src/config_center/service.py`、`src/config_center/audit.py` 三处，已统一到 `src/config_center/schema.py::is_sensitive`，三处改为委托调用（并加了一条测试断言三处结论一致）。

**修复后实测**：

```
GET  llm_max_tokens -> value=2048, is_sensitive=false
PUT  llm_max_tokens 1024 -> 200, new_value=1024
审计里记录的也是明文数值（它本就不是凭据，无需脱敏）
```

### 7.3 「id() 变化」这个判据在图路径上会假性通过

如第四节所述，Agent 每次图调用新建，因此即使重建逻辑完全失效，`id()` 每次也会不同。任务单把这条件为「关键反例」在本项目里不成立。本报告改用「单实例 + 中途改配置」的方式验证，并补了「配置未变则 id 不应变」的反例测试。

---

## 八、`max_reasoning_turns` 一并验证

任务单要求一并验证。它**不走 LLM 重建链路**，机制不同：

| 项 | 说明 |
| --- | --- |
| 读取位置 | 调用方构造 `AgentState` 时读配置：`src/api/routes.py:91`（REST）、`src/websocket/routes.py:623`（WS） |
| 此前的问题 | 两处都写死 `effective_max_turns=5`，导致配置项被调用方覆盖，改配置无效 |
| 修复 | 改为 `int(getattr(settings, "max_reasoning_turns", 5) or 5)` |
| 生效方式 | 每个请求重新读取，**不需要重建任何实例** |
| 消费点 | `src/graph/nodes.py:829` 传给 `CustomerServiceAgent(max_turns=...)` |

验证结果（`TestMaxReasoningTurnsHotReload`）：

| 场景 | 断言 | 结果 |
| --- | --- | --- |
| 配置设为 3，调 `/api/v1/chat` | 进入工作流的 state 中 `effective_max_turns == 3` | 通过 |
| 再改为 8，再次调用 | `effective_max_turns == 8`（即时跟随） | 通过 |

测试手法：用 `monkeypatch` 把 `get_workflow` 换成可捕获 state 的桩件，从而在不真实推理的前提下断言 state 内容。

---

## 九、审计日志

| 时间 | 配置项 | 旧值 | 新值 | 操作人 | 来源 | 热更 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-15T14:27:26.051 | `llm_max_tokens` | 1024 | 2048 | admin-default | api | True |
| 2026-09-15T14:27:24.552 | `llm_temperature` | 0.7 | 0.0 | admin-default | api | True |
| 2026-09-15T14:27:23.106 | `llm_max_tokens` | 2048 | 1024 | admin-default | api | True |
| 2026-09-15T14:27:21.650 | `llm_temperature` | 0.0 | 0.7 | admin-default | api | True |

字段齐备：`config_key`、`old_value`、`new_value`、`action`、`operator`、`operator_ip`、`hot_applied`、`source`、`created_at`。

新增键会在审计里带 `modified_at` / `modified_by`，读取接口也一并回显（见第六节回读列）。

---

## 十、复原与回归

```
llm_temperature = 0.0      （与初始值一致）
llm_max_tokens  = 2048     （与初始值一致）
GET /api/v1/health -> 200
容器 StartedAt=2026-09-15T14:26:24Z  Pid=21778  RestartCount=0
```

回归测试：`tests/test_api + tests/test_agent + tests/test_rag + tests/test_graph` = **604 passed / 21 skipped / 0 failed**。

---

## 十一、一句话结论

**temperature 与 max_tokens 的热更新是真生效的**：改完配置后，同一 Agent 实例的 LLM 会被重建并携带新参数；不重启容器；有审计记录。

但要说清楚两点：

1. **图路径上它「生效」的原因与设想不同**。因为 Agent 每次请求新建，光是「新实例读到新配置」就足以生效，重建逻辑在这条路径上并非必要条件。真要验证重建，必须固定一个实例再改配置。
2. **`max_tokens` 此前根本改不了**。它被敏感字段规则误判，读不到值也写不进去（PUT 返回 400）。这是一个会直接挡住调参的缺陷，已修复；顺带把散落三处的判定规则收敛到一处。

---

## 十二、遗留问题与建议

1. **敏感判定规则仍是关键词启发式**。整词匹配已能覆盖常见命名，但归根结底是约定。更稳的做法是在字段定义处显式标注 `sensitive=True`（pydantic Field 元数据），而不是靠名字猜。建议后续按此演进。
2. **`_ensure_llm_current` 的重建失败分支未被测试覆盖**。当前只会保留旧客户端并记版本，建议补一条用例锁住该行为。
3. **Agent 每请求新建的成本**。每次图调用都要构造 `ChatOpenAI` + `create_agent`，在内网单容器下开销可接受，但若未来请求量上去，值得评估复用一个长生命周期 Agent（届时 `_ensure_llm_current` 就从兜底变成关键路径）。
4. **配置不跨重启保留**。与上一轮相同：热更新只改内存，重启回落 `.env`。
