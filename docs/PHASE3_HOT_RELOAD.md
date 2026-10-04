# Phase 3 热更新实测报告 — retrieval_top_k

- 日期：2026-09-15
- 环境：`deploy/prod/docker-compose.prod.yml`（内网单容器）
- 容器：`prod-app-1`，`StartedAt=2026-09-15T13:57:11Z`，`Pid=5878`，全程未重启
- 新增验证资产：`tests/test_api/test_config_hot_reload.py`、`scripts/verify_config_hot_reload.py`

---

## 一、结论摘要

| 验收要点 | 结论 | 依据 |
| --- | --- | --- |
| 全程不重启容器，配置即时生效 | 通过 | 三次 PUT 前后 `StartedAt` 与 `Pid` 完全一致 |
| 结果数量随配置值变化 | 通过 | 真实知识库下 5→5 条、2→2 条、10→10（工具侧） |
| 不再是硬编码的 5 | 通过 | 工具传给检索器的 top_k 逐次跟随配置 |
| 审计日志有对应记录 | 通过 | 6 条记录，含旧值/新值/操作人/时间/来源 |
| 配置值已复原 | 通过 | 最终 `retrieval_top_k = 5` |

**但任务单预设的验证路径走不通**，实际验证方式与任务单不同，偏差见第六节。这一节请务必看。

---

## 二、初始配置值

`GET /api/v1/config/retrieval_top_k`（2026-09-15 21:52 实测）：

```json
{
  "key": "retrieval_top_k",
  "type": "int",
  "default": 5,
  "value": 5,
  "is_default": true,
  "is_sensitive": false,
  "readonly": false,
  "hot": true,
  "category": "retrieval",
  "category_label": "检索配置",
  "constraints": { "min": 1, "max": 50, "note": "召回条数，设 0 会导致检索恒空" },
  "modified_at": null,
  "modified_by": null
}
```

初始值 **5**，标记为可热更新（`hot: true`），带范围约束（1~50）。

---

## 三、检索端点：任务单猜的路径不成立

### 3.1 项目里没有 `/retrieval/search` 这类端点

OpenAPI 里与检索相关的只有知识库管理接口，其中唯一能做检索的是：

```
POST /api/v1/admin/knowledge/{kb_id}/hit_test
```

### 3.2 但这个端点不读 retrieval_top_k

源码 `src/api/knowledge.py`：

```python
results = retriever.search_with_scores(
    req.query,
    top_k=req.top_k,          # ← 取自请求体
    tenant_id=tenant_id,
    ...
)
```

`top_k` 直接来自请求体，**与配置中心无关**。拿它做热更新实测，看到的条数只会跟随请求体里的数字变化，从而得出「配置改了没效果」的错误结论。它的正确用途是「验证某个 top_k 下检索效果如何」，不是「验证配置热更新」。

### 3.3 真正的配置消费方

全仓检索路径上读 `settings.retrieval_top_k` 的只有一个地方：

| 位置 | 说明 |
| --- | --- |
| `src/agent/tools.py` 的 `search_knowledge_base` 工具 | Agent 在做知识库检索时调用，**这是唯一在运行时读取该配置的检索入口** |
| `src/mcp_tools/kb.py` 的 `kb_search` 工具 | 默认值走配置（哨兵 0），但未接入当前 Agent |
| `src/rag/vector_store.py` | 仅在调用方未传 top_k 时兜底，主链路都会显式传值 |

这个工具**只能由 Agent 在对话中调用**，没有独立的 REST 入口。因此下面用两种方式取证：

1. **进程内测试**（`tests/test_api/test_config_hot_reload.py`）：用 TestClient 让接口与工具跑在同一进程，复现线上单进程 uvicorn 的语义。
2. **真实知识库验证**（`scripts/verify_config_hot_reload.py`）：在容器内调用真实工具，并在检索器上挂探针，记录它**实际收到的 top_k** 与**返回条数**。

---

## 四、基线结果数

真实知识库 `KBS-FA45FD`（4 文档 / 14 切片），检索词 `XG-9000 腔体预热温度`。

**基线（配置值 5）**：

```
工具传给检索器的 top_k = 5
检索器实际返回文档数   = 5
工具返回体 [Doc] 标记数 = 5
```

三方一致，说明探针可信。工具实际命中的是 `kb_md_manual.md` 的「1. 腔体预热规程」等内容，返回体首段含「腔体预热温度为 187 摄氏度」。

---

## 五、三次配置变更后的结果数

### 5.1 检索条数随配置变化（真实知识库，进程内）

| 配置值 | 工具传给检索器的 top_k | 检索器实际返回条数 | 工具返回体 `[Doc]` 标记数 | 是否符合预期 |
| --- | --- | --- | --- | --- |
| 5（初始） | 5 | 5 | 5 | 是 |
| **2** | 2 | **2** | **2** | 是 |
| **10** | 10 | **6** | **6** | 部分（见下） |
| 5（复原） | 5 | 5 | 5 | 是 |

关于 10 那一行：**工具确实把 10 传给了检索器，但检索器只返回 6 条**。原因是知识库只有 14 个切片，且检索链有来源配额（`retrieval_source_cap=2`：同一来源最多保留 2 条），实际可召回的上限低于 10。这属于任务单预先说明的「或受限于实际命中数」。

这一行恰好是「不再是硬编码」的有力证据：如果 top_k 仍是写死的 5，**永远不会出现「传 10」这个动作**。

### 5.2 进程内测试（6 项全过）

```
tests/test_api/test_config_hot_reload.py ......  6 passed
```

关键断言：

| 测试 | 断言内容 | 结果 |
| --- | --- | --- |
| `test_default_value_is_used_by_tool` | 未改动时工具用配置默认值 5 | 通过 |
| `test_put_then_tool_uses_new_value[2]` | PUT 改 2 后，工具立即传 2 | 通过 |
| `test_put_then_tool_uses_new_value[10]` | PUT 改 10 后，工具立即传 10 | 通过 |
| `test_sequence_5_2_10_restore` | 连续切换 2→10→5，工具逐次跟上 | 通过 |
| `test_tool_returns_matching_doc_count` | 工具返回体条数随配置变化（2 条 / 4 条） | 通过 |
| `test_config_endpoint_reflects_new_value` | 读取接口回显新值且带修改人/时间 | 通过 |

### 5.3 API 层：启动时间未变（证明没重启）

| 操作 | 接口响应 | 进程内回读 | 容器 StartedAt / Pid |
| --- | --- | --- | --- |
| 改动前 | — | 5 | `13:57:11Z` / `5878` |
| PUT = 2 | old=5 new=2 version=1 hot_applied=true | 2（by admin-default） | 未变 |
| PUT = 10 | old=2 new=10 version=2 hot_applied=true | 10（by admin-default） | 未变 |
| PUT = 5 | old=10 new=5 version=3 hot_applied=true | 5（by admin-default） | 未变 |
| 改动后 | — | 5 | `13:57:11Z` / `5878` |

配置版本号 1→2→3 递增，回读值逐次跟随，容器自始至终是同一个进程。

---

## 六、偏差说明（三个必须讲清楚的问题）

### 6.1 任务单给的检索端点不读配置

见第三节。`hit_test` 的 top_k 来自请求体。**这是本次实测最大的偏差**：如果按任务单字面用 `hit_test` 验证，会得到「改了配置但条数不变」的假失败。

### 6.2 用 `docker exec` 观察热更新是无效的

我在容器内第一次用 `docker exec python /tmp/verify.py` 做实测时，把配置改成 2 后工具**仍然读到 5**。查下来是观察方式的问题，不是热更新失效：

| 观察者 | 读到的值 | 说明 |
| --- | --- | --- |
| API 进程自己（`GET /api/v1/config/retrieval_top_k`） | **2** | PUT 已生效 |
| `docker exec` 起的新进程 | 5 | 独立进程，重新加载 settings |

热更新的实现是 `setattr(settings, field, value)`，改的是**当前进程**的内存。`docker exec` 每次都起新进程，各有各的 settings 对象，内存不共享，因此永远读到启动时的值。

**这一点很关键**：它意味着任何「另起一个进程去观察热更新」的验证都是无效的，必须在同一进程内验证。上面的进程内测试与容器内探针都是按这个前提设计的。

### 6.3 部署容器里无法用「聊天」作为条数探针

任务单第 4 步设想「不重启，再发一条检索请求，记录返回结果数量」。在部署容器里，读取 `retrieval_top_k` 的检索入口是 Agent 工具，**只能由对话触发**，没有独立的 REST 入口。实测尝试：

- 发一条 `POST /api/v1/chat`（提问 `XG-9000 的腔体预热温度是多少摄氏度`）
- 结果：**900 秒超时，未返回**。原因有二：内网 7B 在 CPU 上单轮推理极慢（实测 14 tok/s，prompt 处理就占 70 秒以上）；且该模型不必然调用知识库工具，本次它转去调了云资源查询工具。

因此部署容器里的「条数随配置变化」改由上述两种方式取证，而**不是**靠对话。

附带发现：配置项 `kb_call_mode` 取值为 `always`，看起来能强制调用知识库。但全仓搜索显示**它没有任何消费点**，是个死配置（与修复前的 `retrieval_top_k` 同类问题）。这条值得后续单独修。

---

## 七、审计日志

`GET /api/v1/config/audit?key=retrieval_top_k`（共 6 条，倒序）：

| 时间 | 动作 | 旧值 | 新值 | 操作人 | 来源 | 热更 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-15T14:03:43.619 | update | 10 | 5 | admin-default | api | True |
| 2026-09-15T14:03:42.184 | update | 2 | 10 | admin-default | api | True |
| 2026-09-15T14:03:40.726 | update | 5 | 2 | admin-default | api | True |
| 2026-09-15T14:03:02.038 | update | 5 | 10 | verify-script | verify | True |
| 2026-09-15T14:02:57.502 | update | 5 | 2 | verify-script | verify | True |
| 2026-09-15T13:52:39.384 | update | 5 | 2 | admin-default | api | True |

说明：后三条中的 `verify-script` 是本文档第五节的真实知识库探针（每次独立进程，起点都是 5，所以显示 `5→2`、`5→10`）。`source` 字段把程序化验证与人工操作区分开，便于审计时辨认。

字段齐备：`config_key`、`old_value`、`new_value`、`action`、`operator`、`operator_ip`、`hot_applied`、`source`、`created_at`。

---

## 八、遗留问题与建议

1. **配置变更不跨重启保留**：热更新只改内存，容器重启后回落到 `.env` 的值（实测重启后 `modified_at` 变回 `null`）。这是当前设计（原接口文档也这么写），但审计日志里能看到改过、重启后却无痕，容易让人困惑。若要持久化，需要把覆盖值落库并在启动时加载。
2. **多副本部署下热更新不广播**：`setattr` 只影响收到请求的那个进程。未来 `replicas>1` 时必须加广播（Redis pub/sub 或数据库轮询），否则各副本配置不一致。
3. **`kb_call_mode` 是死配置**：定义了但无人读，`always` 不生效。
4. **建议给检索加一条可观测输出**：本次已在 `src/agent/tools.py` 的检索工具里补了 `kb_search_done` 结构化日志（含 `top_k` 与 `hit_count`）。这样在线上能直接看出某次回答用的是几条召回，也便于日后用真实对话验证热更新。
5. **`hit_test` 的语义值得澄清**：它是「按指定 top_k 试检索效果」，与配置中心无关。建议在其接口文档里写明，避免再被误当作热更新验证工具。
