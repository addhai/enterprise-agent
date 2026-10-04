# Phase 3 热更新实测报告 — rerank_enabled

- 日期：2026-09-15
- 环境：`deploy/prod/docker-compose.prod.yml`（内网单容器）
- 容器：`prod-app-1`，`StartedAt=2026-09-15T13:57:11Z`，`Pid=5878`，全程未重启
- 新增验证资产：`tests/test_rag/test_rerank_hot_reload.py`（6 项）、`scripts/verify_rerank_hot_reload.py`

---

## 一、结论摘要

| 验收要点 | 结论 | 依据 |
| --- | --- | --- |
| 开关切换即时生效，不重启 | 通过 | 两次 PUT 前后 `StartedAt` 与 `Pid` 完全一致 |
| `false` 时重排序逻辑被跳过 | 通过 | 门控函数调用次数 0，桩件调用 0，无 `reranked` 标记 |
| `true` 时重排序正常执行 | 通过 | 门控函数调用 1 次，桩件收到 5 个候选，结果顺序被改变 |
| 审计日志有记录 | 通过 | 14 条，含 `admin-default/api` 与 `verify-script` 两类来源 |
| 配置已复原 | 通过 | 最终 `rerank_enabled = false`（与初始值一致） |

**但有两处与任务单预期不符，且第二处会影响你对「重排序生效」的预期**，详见第五节。

---

## 二、初始配置值

`GET /api/v1/config/rerank_enabled`（2026-09-15 22:08 实测）：

```json
{
  "key": "rerank_enabled",
  "type": "bool",
  "default": false,
  "value": false,
  "is_default": true,
  "is_sensitive": false,
  "readonly": false,
  "hot": true,
  "category": "rerank",
  "category_label": "重排序",
  "modified_at": null,
  "modified_by": null
}
```

**初始值是 `false`，不是任务单预期的 `true`**。`default` 也是 `false`，即这是出厂默认值，从未被改过。

关联配置：

| 配置项 | 值 | 说明 |
| --- | --- | --- |
| `rerank_provider` | `dashscope` | 阿里云百炼，**公网 API** |
| `rerank_model` | `gte-rerank` | |
| `rerank_top_n` | `5` | 重排后保留条数 |

---

## 三、重排序代码路径与关键行

调用链：

```
Agent 决定调工具
  └─ src/agent/tools.py:976            retriever.search(query, top_k=配置值, ...)
       └─ src/rag/retriever.py:384     if self._rerank_enabled and final:     ← 门控行
            └─ src/rag/retriever.py:748  def _rerank(query, candidates)
                 └─ src/rag/retriever.py:762  reranker = self.reranker        ← 懒加载属性
                      └─ src/rag/retriever.py:693  def reranker -> _get_reranker
```

关键行清单：

| 文件:行号 | 内容 | 作用 |
| --- | --- | --- |
| `src/agent/tools.py:976` | `results = retriever.search(...)` | 知识库工具发起检索，重排序的入口 |
| **`src/rag/retriever.py:384`** | `if self._rerank_enabled and final:` | **门控行。开关就是在这里被判断的** |
| `src/rag/retriever.py:693` | `def reranker(self)` | 懒加载重排序器 |
| `src/rag/retriever.py:703` | `if not self._rerank_enabled: return None` | 关闭时直接不构造重排序器 |
| **`src/rag/retriever.py:734`** | `def _rerank_enabled(self) -> bool:` | **实时取值的 property（本次热更新的核心）** |
| **`src/rag/retriever.py:738`** | `return bool(getattr(settings, "rerank_enabled", False))` | 每次访问都重新读配置 |
| `src/rag/retriever.py:741-744` | `_rerank_top_n` property | 同上，条数也实时读 |
| `src/rag/retriever.py:767` | `return candidates` | 重排序器为 None 时直接返回原序 |
| `src/rag/retriever.py:777` | `doc.metadata["reranked"] = True` | 成功重排的标记，可作为观察证据 |
| `src/rag/retriever.py:781-782` | `logger.warning("Rerank failed, using original order")` + `return candidates` | 失败降级为原序 |

### 为什么这是「真热更新」

原实现（本次 Phase 3 修复前）是：

```python
self._rerank_enabled = settings.rerank_enabled   # 构造时快照
```

现在是 property，每次访问重新读 settings。这一行之差决定了配置改动能否生效。

判据：**如果检索器构造一次后中途改配置仍然生效，就说明是读取时取值**。下面的测试正是按这个判据设计的。

---

## 四、进程内测试结果

### 4.1 测试文件

`tests/test_rag/test_rerank_hot_reload.py`，6 项全过：

```
tests/test_rag/test_rerank_hot_reload.py ......  6 passed
```

手法：**检索器只构造一次**，中途改配置再检索。只把「数据从哪来」换成固定候选（打桩 `_vector_search` / `_bm25_search`），RRF 融合、合并、门控行、权限过滤全部走真实实现。

### 4.2 开关状态与重排序是否被调用

| 测试 | 开关状态 | 重排序函数调用次数 | 桩件调用次数 | 结果顺序 | 是否通过 |
| --- | --- | --- | --- | --- | --- |
| `test_gate_reads_config_at_call_time_not_construction_time` | false（构造时） | **0** | 0 | 原序 | 是 |
| 同上，构造后改为 true | true | **1** | 1 | 改变 | 是 |
| 同上，再改回 false | false | 1（未增） | 1（未增） | 原序 | 是 |
| `test_sequence_on_off_on` | true → false → true | — | **1 / 0 / 1** | — | 是 |
| `test_result_order_changes_when_enabled` | false vs true | — | — | on == reversed(off) | 是 |
| `test_reranked_metadata_only_when_enabled` | false | 结果**无** `reranked` 标记 | — | — | 是 |
| 同上 | true | 结果**全部带** `reranked=True` | — | — | 是 |
| `test_rerank_top_n_follows_config` | 7 后改 2 | — | 传入 top_n 依次为 **7、2** | — | 是 |
| `test_init_failure_latches_off_even_if_config_is_true` | true 但闩锁置位 | **0** | — | 原序 | 是（固定既有行为） |

**核心那一行**：构造时配置为 false（调用 0 次），构造之后把配置改成 true，同一个检索器实例立刻开始重排序（调用 1 次）。若门控是构造时快照，这里会一直是 0 次。

### 4.3 容器内真实工具路径（真实知识库 + 桩重排序器）

`scripts/verify_rerank_hot_reload.py`，在 `prod-app-1` 内调用真实工具，检索词 `XG-9000 腔体预热温度`：

| 开关状态 | `_rerank` 调用次数 | 桩件调用次数 | 桩件收到候选数 | 桩件收到 top_n | 返回文档数 | 结果来源顺序 |
| --- | --- | --- | --- | --- | --- | --- |
| **true** | **1** | 1 | 5 | 5 | 5 | txt → pdf → md → docx → md |
| **false** | **0** | **0** | — | — | 5 | md → docx → md → pdf → txt |
| **true（再开）** | **1** | 1 | 5 | 5 | 5 | txt → pdf → md → docx → md |

三点全部成立：
- `false` 时门控函数 **0 次**被调用，桩件也 **0 次**，证明重排序逻辑真的被跳过（不是调用了但内部空转）
- `true` 时调用 **1 次**，桩件收到 5 个候选
- **顺序确实变化**：开启时的顺序恰好是关闭时的反转，证明重排序的实际效果能作用到最终结果上
- 再开能恢复，不存在「关掉就再也开不回来」的问题

---

## 五、与预期不符的两处（重要）

### 5.1 初始值是 false，不是 true

任务单预期 `true`，实测 `false`（`default` 也是 false）。这会影响后续判断：在本部署里重排序**默认就是关闭的**，如果期望它生效，需要显式打开。

### 5.2 真实重排序器在内网不可用，打开也只是空转

不注入桩件、走真实依赖时（`--real-reranker` 模式）：

| 开关状态 | `_rerank` 调用次数 | 结果来源顺序 | 实际发生的事 |
| --- | --- | --- | --- |
| true | 1 | md → docx → md → pdf → txt（**未变**） | 尝试调用真实重排序器，报错后降级 |
| false | 0 | 同上（**未变**） | 未尝试 |
| true（再开） | 1 | 同上（**未变**） | 同上 |

脚本 stderr 捕获到的真实报错：

```
Rerank failed (DashscopeReranker: HTTP Error 404: Not Found), falling back to original order
```

原因：`rerank_provider=dashscope` 指向阿里云公网 API，而本部署的 `openai_api_base` 是容器内的 Ollama（`http://127.0.0.1:11434/v1`），该端点没有 rerank 接口，因此 404。**内网环境下真实重排序不可用。**

**这不影响「开关是否生效」的结论**，两者是两件事：
- 开关生效：`false` 时不调用、`true` 时调用 → 已由桩件模式与进程内测试双重证明
- 重排序有实际效果：需要外部模型可达 → 当前不可用

换句话说，**开关是好的，依赖是缺的**。如果哪天需要真正启用重排序，要么让内网能访问 DashScope，要么改用 `rerank_provider=local_bge` 并准备本地 BGE-reranker 模型。

### 5.3 附带确认的既有行为：初始化失败闩锁

`retriever.py:725` 在重排序器初始化失败时会置位 `_rerank_init_failed`，此后即使配置为 `true` 也不再重排序，直到进程重启。这是刻意的保护（避免每次检索都白跑一次注定失败的初始化），但它意味着**一旦失败过，热更新改回 true 不会恢复**。已用测试 `test_init_failure_latches_off_even_if_config_is_true` 把这个行为固定下来，避免日后被误当 bug 改坏。

本次实测未触发闩锁，因为桩件注入时 `_get_reranker` 首行就短路返回，不会走构造失败的路径。

---

## 六、API 层切换与容器状态

| 操作 | 接口响应 | 进程内回读 | 容器 StartedAt / Pid |
| --- | --- | --- | --- |
| 改动前 | — | false | `13:57:11Z` / `5878` |
| PUT = true | old=False new=True version=4 hot_applied=true | **true**（by admin-default） | 未变 |
| PUT = false | old=True new=False version=5 hot_applied=true | **false**（by admin-default） | 未变 |
| 改动后 | — | false | `13:57:11Z` / `5878` |

配置版本号 4→5 递增，回读值逐次跟随，容器自始至终是同一个进程（`StartedAt` 与 `Pid` 完全一致）。

---

## 七、审计日志

`GET /api/v1/config/audit?key=rerank_enabled`（共 14 条）。其中由 API 操作产生的两条（最relevant）：

| 时间 | 动作 | 旧值 | 新值 | 操作人 | 来源 | 热更 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-15T14:12:22.683 | update | True | False | admin-default | api | True |
| 2026-09-15T14:12:21.300 | update | False | True | admin-default | api | True |

其余 12 条来自容器内验证脚本（`verify-script`），`source` 分别为 `verify`（脚本内的开关切换）与 `verify-restore`（脚本结束时复原）。示例：

| 时间 | 旧值 | 新值 | 操作人 | 来源 |
| --- | --- | --- | --- | --- |
| 2026-09-15T14:10:07.807 | False | True | verify-script | verify |
| 2026-09-15T14:10:07.929 | True | False | verify-script | verify-restore |

审计字段齐备：`config_key`、`old_value`、`new_value`、`action`、`operator`、`operator_ip`、`hot_applied`、`source`、`created_at`。`source` 字段让人工操作与程序化验证可区分，这也是上一轮加它的原因。

---

## 八、复原确认

```
GET /api/v1/config/rerank_enabled → value = false   （与初始值一致）
GET /api/v1/health → 200
容器 StartedAt=2026-09-15T13:57:11Z  Pid=5878  RestartCount=0
```

回归测试：`tests/test_rag + tests/test_api + tests/test_agent` = **428 passed / 18 skipped / 0 failed**。

---

## 九、给出结论的一句话

**`rerank_enabled` 的热更新是真生效的**：关闭时门控行不进入、重排序函数零调用；开启时进入并实际改变结果顺序；改成什么值就立即是什么行为，且不重启容器。

但要清楚当前部署下打开它**并不会真的改善检索**，因为 DashScope 不可达，每次都会静默降级为原序（日志里有 warning）。要让重排序产生实际效果，需要先解决依赖。
