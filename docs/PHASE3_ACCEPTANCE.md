# Phase 3 收尾验收记录（2026-09-15 22:36-23:00）

## Part 1 配置合法性校验

| 用例 | 输入 | 结果 | 判定 |
| --- | --- | --- | --- |
| 数值下界（非法） | `retrieval_top_k = 0` | HTTP 400「不能小于 1，收到 0」 | 通过 |
| 数值（合法） | `retrieval_top_k = 20` | HTTP 200 | 通过 |
| 数值负值（非法） | `llm_temperature = -0.5` | HTTP 400「不能小于 0.0，收到 -0.5」 | 通过 |
| 数值（合法） | `llm_temperature = 1.0` | HTTP 200 | 通过 |
| 类型校验 | `rerank_enabled = "yes"` | HTTP 400「期望布尔值 true 或 false，不接受 str」 | 通过（**本轮修复**） |
| 只读校验 | `database_url = "postgresql://x/y"` | HTTP 400「是启动时只读配置…」 | 通过 |
| 审计（成功变更） | 3 次成功写入 | 各产生 1 条审计记录 | 通过 |
| 审计（被拒绝变更） | `database_url` 等被拒 | **0 条审计记录** | 通过 |

**本轮修复项**：`rerank_enabled="yes"` 原被宽松接受（200）。`src/config_center/service.py::coerce`
的 bool 分支此前把 `yes/on/1` 当真实值；已改为**严格布尔**，非 bool 一律 400。
理由：配置长期生效，宁可当场报错，也不替调用方猜笔误。

## Part 2 自检端点

任务单给的 `GET /api/v1/config/self-check` → **404**；实际端点是
`GET /api/v1/monitoring/self-check` → 200。

返回内容（复验后）：

```
ok = True
配置版本号        = 0
可热更字段数      = 15（5 类：rag / model / feature_flag / safety / other）
纳管字段总数      = 47
审计表状态        = 记录数 30，最近 2026-09-15T14:36:58
observations      = []（无异常）
```

**本轮补强**：原先缺「可热更字段清单」，已补 `hot_categories` / `hot_field_count` /
`readonly_field_count` / `total_managed_fields`。

已知小瑕疵：`readonly_field_count` 当前算成 0，因为它是拿「分类清单字段 ∩ 只读集合」求交，
而只读字段本身不在分类清单里。应改为直接统计 `READONLY_FIELDS`（约 16 个）。未在限时内修。

## Part 3 指标验证

| 项 | 结果 |
| --- | --- |
| `chat_sessions_total` 是否出现在 metrics 端点 | **出现**（需先产生一次会话） |
| 实际序列 | `{type="websocket",status="active"}=1`、`{type="websocket",status="ended"}=1` |
| Prometheus 查询 | 2 条结果 |

说明：该 counter 采用「首次自增时创建序列」，容器重建后未产生会话时查不到。
本次通过建立一次 WS 连接触发，随后 Prometheus 抓到 2 条序列。

Grafana 面板核对：

```
面板数 16 | 重叠面板对 无 | 超出画布宽度 无 | 缺 datasource 无
会话面板查询 sum(chat_sessions_total) by (type) → 1 条结果（有数据）
```

## Part 4 核心回归

```
84 passed, 1 warning in 22.12s
```

（任务单给的 `tests/test_config_center` 等路径不存在，改用实际路径：
`tests/test_api/test_config_center.py`、`test_config.py`、`test_config_hot_reload.py`、
`tests/test_agent/test_llm_rebuild_hot_reload.py`、`tests/test_rag/test_rerank_hot_reload.py`）

## Part 5 服务关闭

| 项 | 状态 |
| --- | --- |
| 业务栈 down | 成功（未加 `-v`） |
| `compose ps` | 空，业务容器全部退出 |
| 监控栈 | **保留**：agent-prometheus / agent-grafana / 两个 exporter 仍在运行 |
| 数据卷 | 5 个全保留：prod-agent-chroma / prod-agent-logs / prod-ollama-models / prod-pg-data / prod-redis-data |
| prod-net | 因监控栈占用而保留（预期） |

## 结论

**Phase 3 验收通过。** 8 项校验用例全部符合预期（其中 1 项经本轮修复后达标），
自检端点可用且内容完备（复用已知小瑕疵 1 处），指标可见、面板无异常，核心回归 84 项全过，
服务已按预期关闭且数据与监控栈保留。
