# 监控指标定义（P4-1）

> 上线后需监控的核心指标，含定义、计算方式、告警阈值、数据来源。
> 只定义指标和阈值，监控实现是 P4-2 或运维侧工作。
> 告警阈值依据：性能基准数据（P2-5 / P4-1）上浮 50% 作为缓冲。

---

## 1. 业务指标

| # | 指标名 | 定义 | 计算方式 | 告警阈值 | 数据来源 |
|---|---|---|---|---|---|
| 1.1 | 日均对话数 | 每日用户发起的对话总数（含 AI + 人工） | `count(chat_message) WHERE date = today` | < 10 持续 3 天（流量异常低） | WebSocket 日志 / session_manager |
| 1.2 | 用户活跃度 | 每日发起至少 1 次对话的独立用户数 | `count(DISTINCT user_id) WHERE date = today` | < 3 持续 3 天 | session_manager / DB |
| 1.3 | 平均对话轮次 | 单会话内用户消息数的平均值 | `avg(message_count) GROUP BY session_id WHERE date = today` | > 8（用户反复问 = AI 答不好） | DB message_list |
| 1.4 | 转人工率 | 转人工会话占总会话的比例 | `count(needs_human=true) / count(sessions) * 100%` | > 30%（AI 自主解决率低） | tracker.record_chat |
| 1.5 | 会话解决率 | 未转人工且 quality_score > 0.3 的会话比例 | `count(resolved=true) / count(sessions) * 100%` | < 60% | tracker.record_chat |

## 2. 性能指标

| # | 指标名 | 定义 | 计算方式 | 告警阈值 | 数据来源 |
|---|---|---|---|---|---|
| 2.1 | API P95 延迟 | REST API 95 百分位响应延迟 | `histogram_quantile(0.95, http_request_duration_seconds_bucket)` | > 3s（基准 P95=8.8ms 上浮 50% 后加 LLM 1-2s） | Prometheus |
| 2.2 | 首 token 延迟 | WebSocket 从发送消息到收到第一个 streaming_chunk 的时间 | 每条消息记录 `(first_chunk_time - send_time)` 取 P95 | > 5s（预估首 token 600ms-3.5s，上浮 50%） | WebSocket 日志 |
| 2.3 | 并发连接数 | 同时活跃的 WebSocket 连接数 | `gauge ws_active_connections` 实时值 | > 200（单容器 1GB 内存上限） | Prometheus |
| 2.4 | RAG 检索延迟 | hit_test 接口 95 百分位响应延迟 | `histogram_quantile(0.95, rag_search_duration_seconds_bucket)` | > 500ms（基准 P95=2260ms 含冷启动，稳态 234ms 上浮 50%） | Prometheus |
| 2.5 | LLM 调用成功率 | LLM 调用成功数 / 总调用数 | `llm_calls_success_total / llm_calls_total * 100%` | < 95% | Prometheus |

## 3. 质量指标

| # | 指标名 | 定义 | 计算方式 | 告警阈值 | 数据来源 |
|---|---|---|---|---|---|
| 3.1 | 未收录触发率 | 触发 find_missing_identifiers 的消息占比 | `count(missing_identifiers != []) / count(chat_messages) * 100%` | > 20%（用户大量问知识库外问题 = 覆盖不足） | tools.py 日志 |
| 3.2 | 幻觉人工抽检率 | 每日人工抽检发现幻觉的比例 | `count(hallucination_found) / count(spot_checked) * 100%` | > 10%（基准幻觉率 6.6%，上浮 50%） | 人工抽检记录 |
| 3.3 | 用户反馈差评率 | 满意度评分 1-2 分（满分 5）的比例 | `count(score <= 2) / count(satisfaction_submitted) * 100%` | > 15% | satisfaction API |

## 4. 系统指标

| # | 指标名 | 定义 | 计算方式 | 告警阈值 | 数据来源 |
|---|---|---|---|---|---|
| 4.1 | 容器 CPU 使用率 | thermo-intranet 容器 CPU 占用 | `docker stats --no-stream thermo-intranet` CPU% | > 80% 持续 5 分钟 | docker stats / cAdvisor |
| 4.2 | 容器内存使用率 | thermo-intranet 容器内存占用 | `docker stats --no-stream thermo-intranet` MEM% | > 80%（1GB 上限的 80% = 800MB） | docker stats / cAdvisor |
| 4.3 | GPU 显存使用率 | ollama 容器 GPU 显存占用 | `nvidia-smi --query-gpu=memory.used,memory.total` | > 90%（7B 模型需 ~5GB，限值 7500MiB） | nvidia-smi |
| 4.4 | OOM 次数 | 容器因内存不足被杀的次数 | `docker inspect --format '{{.State.OOMKilled}}' thermo-intranet` | > 0（任何一次 OOM 都需告警） | docker inspect |
| 4.5 | 容器重启次数 | thermo-intranet 非主动重启次数 | `docker inspect --format '{{.RestartCount}}' thermo-intranet` | > 3 次/天 | docker inspect |

---

## 指标统计

| 类别 | 指标数 |
|---|---|
| 业务指标 | 5 |
| 性能指标 | 5 |
| 质量指标 | 3 |
| 系统指标 | 5 |
| **合计** | **18** |

## 告警阈值依据

| 指标 | 基准数据 | 上浮比例 | 阈值 | 依据 |
|---|---|---|---|---|
| API P95 | 8.8ms（框架开销） | +50% + LLM 1-2s | 3s | 框架 13ms + LLM 2s + 缓冲 |
| 首 token | 600ms-3.5s（预估） | +50% | 5s | 预估上限 3.5s + 缓冲 |
| RAG 检索 | 234ms（稳态） | +50% + 冷启动 | 500ms | 234 * 1.5 = 351 + 冷启动余量 |
| 幻觉率 | 6.6%（P3-3 实测） | +50% | 10% | 6.6 * 1.5 = 9.9% |
| 转人工率 | 设计预期 20-25% | +50% | 30% | 预期上限 25% * 1.2 |
