# Agent 通信与协调效率优化

> 范围：enterprise-agent 多智能体系统的 A2A 通信层 + Orchestrator 协调层
> 日期：2026-08-25
> 状态：A / B(修正) / C 已落地并通过测试；D 留待本地验证

## 定位到的瓶颈（带代码证据）

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| A | 每次 A2A 委托都重拉 Agent Card + 新建 httpx client | `a2a_server.py` `delegate_to_expert` | 静态元数据零缓存，每次白跑一次 HTTP 往返 |
| B | 专家委托工具用 `_asyncio.run` 包协程 | `a2a_server.py` 两工具 | 在异步 Agent 路径下会抛嵌套事件循环错误（被 except 吞掉→静默失效）；且每次起新事件循环 |
| C | Orchestrator 只委托 `best_match` 单 agent | `orchestrator_agent.py` `orchestrate()` | `matched_agents` 里其它命中者被丢弃，「多专家协同」是空壳、纯串行 |

## 已落地改动

### A. A2A Agent Card + Client 缓存（通信效率）
- 新增 `src/protocols/a2a_cache.py`：`AgentCardCache` 进程级 TTL 缓存（默认 60s，由 `config.a2a_card_cache_ttl` 控制），按 agent URL 缓存 `(card, httpx.AsyncClient)`，带 `asyncio.Lock` 防缓存击穿。
- `delegate_to_expert` 改造为：命中缓存→直接复用 card + 复用连接池 client；未命中→建持久化 client + 拉一次 card 后写入缓存。本地回退链路保持不变。

### B. 专家委托工具（修正方向）
- **结论**：保持工具为 *同步*（`def` + `_asyncio.run`）。原因：本项目 Agent 始终走 `agent.invoke`（同步），langchain 会把 sync 工具放进线程池执行，因此 `_asyncio.run` 不会触发嵌套循环错误；若改成 `async def`，langchain 生成 `StructuredTool` 反而**不支持 `.invoke`**，会破坏现有同步调用路径（已实测报 `NotImplementedError`）。
- 通信/协调效率收益由 **A（省去重复 HTTP 拉 Card）** 与 **C（并行扇出）** 承担，本项仅保留原桥接方式、补注释说明。

### C. Orchestrator 并行扇出 + 聚合（协调效率）
- `orchestrate()` 改为：对 `route_request` 命中的**全部** agent 用 `asyncio.gather` 并行委托（各自独立、可并发），异常隔离（单 agent 失败不影响其它）。
- 新增 `_aggregate_responses()`：单 agent 命中时 `final_response` 语义与旧版一致（向后兼容）；多 agent 命中时按路由优先级拼接并标注来源。
- 输出新增 `coordinated_agents` 字段，便于可观测。

### 配置
- `src/config.py` 新增 `a2a_card_cache_ttl: float = 60.0`。

## 验证
- 新增 `tests/test_protocols/test_a2a_optimization.py`：
  - AgentCardCache 单测（get/set/过期/clear）
  - `delegate_to_expert` 缓存命中：同一 URL 两次委托只拉一次 Card（mock A2A 客户端）
  - 委托工具 `.invoke` 同步桥接到底层异步委托协程
  - Orchestrator 并行扇出 + 聚合 + 异常隔离 + 单 agent 向后兼容
- 结果：`test_a2a_optimization.py` + `test_orchestrator.py` + `test_expert_agents.py` 共 **63 passed**。
- 唯一失败 `test_expert_timeout_config`（断言 `a2a_expert_timeout==30`，沙箱实际 120）为**预存在的环境问题**（沙箱 `.env` 无 a2a 覆盖，走默认 120），与本次改动无关。

## 未做（后续项，需本地 env 验证）
- **D. LangGraph 节点异步化**：`nodes.py:543/604/1012`、`agent.py:109/162` 的 sync `.invoke` 在 `workflow.ainvoke` 异步路径下会阻塞事件循环。改动需转换多个节点为 `async def` 并验证 graph 可 compile/ainvoke，但**沙箱缺 `langchain` 元包无法跑通**，按「无证据不通过」原则本轮不做，留作本地验证项。
- Orchestrator 的 `_delegate_via_a2a` 同样每次重拉 Card，可后续复用同一缓存（本轮聚焦 customer_service→expert 热路径）。
- 缓存 client 失效策略：仅在 `get_agent_card` 失败时关闭；若 send_message 失败未主动 expire，靠 TTL 自然过期（回退链路已保证不崩）。
