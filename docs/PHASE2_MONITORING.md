# Phase 2 — Monitoring 可观测性 验证与联调报告

- 日期：2026-09-15
- 部署形态：`deploy/prod` 内网单容器（app 容器内含 FastAPI + LangGraph + RAG + Ollama）
- 监控栈：Prometheus v3.3.0 + Grafana 11.6.0 + postgres-exporter + redis-exporter
- 验证脚本：`scripts/verify_monitoring_prod.py`、`scripts/generate_monitoring_traffic.py`

---

## 一、结论摘要

| 验收项 | 状态 | 关键证据 |
| --- | --- | --- |
| `/metrics` 端点返回 Prometheus 文本格式且 ≥ 5 个指标 | 通过 | `GET /api/v1/metrics/prometheus` → 200，>5 个指标族 |
| monitoring compose 启动成功，prometheus/grafana 全部 running | 通过 | 4 个容器 Up |
| Prometheus targets 中 app 状态为 UP | 通过 | `up{job="app",instance="app:8000"} = 1` |
| Grafana 可登录，datasource 指向 prometheus | 通过 | admin/admin123 可登录，Prometheus 为默认源 |
| 仪表盘 ≥ 4 个面板且有数据 | 通过 | 14 个面板，其中 11 个有数据（见 §5） |
| 产生聊天流量后指标实时更新 | 通过 | `http_requests_total` 3 → 72，`rag_search_total` 0 → 9 |
| 日志可查（文件日志存在且结构化） | 通过 | `/app/logs/app.jsonl`（JSON 行，含 request_id / duration_ms） |
| monitoring 栈与 app 网络互通，不依赖 localhost | 通过 | 同处 `prod-net`，抓取地址用服务名 `app:8000` |
| 提供完整测试报告 | 本文档 | |

**验收脚本总结果：24/24 项通过**（`scripts/verify_monitoring_prod.py`，明细见 `docs/PHASE2_MONITORING_evidence.json`）

**一句话结论**：监控栈本身配置缺口不少（网络、抓取目标、指标名全都不对），但更关键的是在联调中发现 app 侧有两个会让监控**恰好在有流量时失灵**的缺陷（事件循环被长聊天阻塞、LLM 指标埋点走错方法）。这两项修完后，指标才真正反映得出现状。

---

## 二、代码现状清单（Step 1 探查结果）

### 2.1 metrics 端点路径

| 路径 | 用途 |
| --- | --- |
| `GET /api/v1/metrics/prometheus` | **Prometheus 文本格式（抓取目标用这个）** |
| `GET /api/v1/metrics/business` | 业务指标 JSON |
| `GET /api/v1/metrics/quality` | 质量指标 JSON |
| `GET /api/v1/metrics/risk` | 风险指标 JSON |
| `GET /api/v1/metrics/system` | 系统指标 JSON |
| `GET /api/v1/metrics/all` | 完整评估报告 JSON |

注意：根路径 `/metrics` 返回 **404**。端点由 `src/api/monitoring.py` 的
`APIRouter(prefix="/metrics")` 提供，再经 `server.py` 以 `/api/v1` 前缀注册。
Python 模块是 `src/api/monitoring.py`，仓库根目录下没有 `monitoring.py`。

### 2.2 已定义的指标（`src/api/metrics.py`，零额外依赖，手写 text exposition format）

**Counter**
- `http_requests_total{service,endpoint,status,method}`
- `llm_calls_total{model,tenant}`
- `llm_calls_success_total{model,tenant}`
- `llm_tokens_total{model,type,tenant}`
- `rag_search_total{backend,hit}`

**Histogram**（累积桶 + `_sum` / `_count`，支持 `histogram_quantile`）
- `http_request_duration_seconds{service,endpoint,method}`
- `rag_search_duration_seconds{backend}`

**Gauge**
- `ws_active_connections{service}`
- `agent_quality_score_avg` / `agent_resolution_rate` / `agent_escalation_rate` / `agent_requests_tracked_total`

### 2.3 HTTP 采集中间件

`MetricsMiddleware`（纯 ASGI，挂在 `src/api/server.py`）自动采集所有 HTTP 请求的
计数与延迟，并对路径做基数归一化（UUID、纯数字段折叠为 `/:uuid`、`/:id`）。
非 HTTP scope（WebSocket / lifespan）原样转发。

### 2.4 与任务单要求命名的差异

| 任务单要求 | 实际实现 | 说明 |
| --- | --- | --- |
| `http_requests_total{method,path,status}` | `http_requests_total{service,endpoint,status,method}` | 多一个 `service` 标签用于多服务区分；`path` 对应 `endpoint` |
| `http_request_duration_seconds{method,path}` | `{service,endpoint,method}` | 同上 |
| `chat_sessions_total` | 不存在 | 会话数当前由 `ws_active_connections` gauge + `agent_requests_tracked_total` 反映，未建立独立 counter |
| `rag_retrieval_duration_seconds` | `rag_search_duration_seconds` | 命名不同，语义一致 |
| `llm_calls_total{model,status}` | `llm_calls_total{model,tenant}` + `llm_calls_success_total` | 成功/失败拆成两个 counter 便于算成功率 |

> 命名差异不影响可用性，仪表盘与告警已按**实际指标名**对齐。是否统一改名属于风格取舍，本次未改，以免牵动既有面板与测试。

---

## 三、Step 2 现状报告：发现的缺口

| # | 位置 | 问题 | 影响 |
| --- | --- | --- | --- |
| 1 | `docker-compose.monitoring.yml` 网络 | 声明 `external name: agent-net`，而业务栈用的是 `prod-net` | 致命：抓不到 app；且 agent-net 是个残留空网络 |
| 2 | `prometheus.yml` | **没有 app 抓取目标**，抓的是 `api-service:8000`（cloud 形态服务名） | app 指标完全进不来 |
| 3 | `prometheus.yml` | 另有 5 个不存在的目标（apisix / rag-service / ws-service / milvus / rabbitmq） | targets 页面塞满 DOWN，掩盖真问题 |
| 4 | `docker-compose.monitoring.yml` | Grafana 密码默认 `admin`，任务要求 `admin123` | 首次登录撞强制改密流程 |
| 5 | `alerts.yml` | `LLMCallFailures` 用 `llm_call_errors_total` / `llm_call_total`，代码里不存在 | 规则被接受但永不触发，假保险 |
| 6 | `alerts.yml` | `QueueBacklog` / `CircuitBreakerOpen` 依赖 rabbitmq / apisix | 同上 |
| 7 | `datasources.yaml` | 预置了 Loki 数据源，但本地无 Loki 镜像 | Explore 里选中必报错，把「没部署」伪装成「有故障」 |
| 8 | `grafana` 环境变量 | `GF_INSTALL_PLUGINS=grafana-piechart-panel` 需联网下载插件 | 离线环境启动慢或失败 |
| 9 | app 侧 | `src/utils/logging.py` 有完整 JSON 日志实现，但 `src/api/server.py` 没调用（只在 `main.py` 调） | 容器真实入口无结构化日志 |
| 10 | app 侧 | REST `/chat` 用同步阻塞的 `app.invoke` | 长聊天期间整机阻塞（详见 §7.1） |
| 11 | app 侧 | LLM 指标埋点写在 `agent.run()`，而图实际调用 `run_with_trace()` | LLM 指标长期为空（详见 §7.2） |
| 12 | 环境 | Docker Desktop 未运行 | 需先拉起 daemon |

---

## 四、变更清单

### 4.1 配置变更

| 文件 | 变更 |
| --- | --- |
| `docker-compose.monitoring.yml` | 网络 `agent-net` 的 external name 改为 `prod-net`；Grafana 默认口令改 `admin123` 并关闭首登强制改密；移除联网插件安装 |
| `deploy/monitoring/prometheus/prometheus.yml` | 新增 `app` 抓取目标（`app:8000` + `/api/v1/metrics/prometheus`）；自监控改用 `prometheus:9090`；注释 5 个不存在的目标；修正 `external_labels` 中不会被展开的 `${ENV:-dev}` |
| `deploy/monitoring/prometheus/alerts.yml` | `LLMCallFailures` 改用真实指标（`llm_calls_success_total` / `llm_calls_total`）；注释 rabbitmq / apisix 两条 |
| `deploy/monitoring/grafana/datasources.yaml` | 注释 Loki 数据源，仅保留可用的 Prometheus |

### 4.2 代码变更（需重建镜像）

| 文件 | 变更 |
| --- | --- |
| `src/api/server.py` | 接入 `setup_logging()`，容器入口启用结构化 JSON 日志 |
| `src/utils/logging.py` | 新增 JSON 文件落盘 handler（`/app/logs/app.jsonl`，10MB×3 轮转）；字段白名单补 `method` / `path` |
| `src/api/metrics.py` | 中间件新增结构化访问日志（`request_id` / `duration_ms` / `status_code` / `method` / `path`）与 `X-Request-ID` 响应头；跳过抓取路径避免日志污染 |
| `src/api/routes.py` | REST `/chat` 的 `app.invoke` 改为 `await asyncio.to_thread(...)` |
| `src/agent/agent.py` | `_report_token_usage` 去掉「无 usage 就不上报」的门槛；`run()` 与 `run_with_trace()` 均遍历全部 AIMessage 上报 |
| `src/graph/nodes.py` | reflect 节点的 token 上报同样去掉门槛 |

### 4.3 新增脚本

- `scripts/generate_monitoring_traffic.py` — 三段式流量生成（轻量 HTTP / WebSocket / 同步聊天），含发送前后指标对比
- `scripts/verify_monitoring_prod.py` — Phase 2 验收脚本（容器、targets、metrics、逐面板 PromQL、Grafana、日志）

---

## 五、启动与联调结果

### 5.1 容器状态

（见 §9 附录的实测输出）

### 5.2 Prometheus 抓取目标

```
job          scrape_url                                         health
app          http://app:8000/api/v1/metrics/prometheus          up
postgres     http://postgres-exporter:9187/metrics              up
prometheus   http://prometheus:9090/metrics                     up
redis        http://redis-exporter:9121/metrics                 up
```

`up{job="app", instance="app:8000", service="api"} = 1`

> 附带发现：抓取配置里的目标标签 `service: api` 与 app 指标自带的 `service` 标签同名，
> Prometheus 会把目标标签重命名为 `exported_service`。功能不受影响（面板按 `service="api"` 匹配的是指标自带标签），属于标签层面的冗余，留待后续清理。

### 5.3 Grafana

- 版本 11.6.0，`/api/health` 返回 `database: ok`
- 登录 `admin / admin123` 成功
- Datasource：`Prometheus`（`http://prometheus:9090`，默认源）。Loki 已注释
- 仪表盘 `Enterprise Agent — Service Overview`（uid `enterprise-agent`）已 provisioning，14 个面板，全部绑定 `uid=prometheus`

### 5.4 面板出数情况

由 `scripts/verify_monitoring_prod.py` 逐个执行面板 PromQL 判定，**14 个面板中 11 个有数据**：

| 面板 | 状态 |
| --- | --- |
| Services Status | 有数据 |
| API Requests per Second | 有数据 |
| API Latency (P50/P95/P99) | 有数据 |
| HTTP Status Distribution | 有数据 |
| LLM Call Success Rate | 有数据 |
| Active WebSocket Connections | 有数据 |
| RAG Search Latency (P95) | 有数据 |
| Redis Memory Usage | 有数据 |
| Conversation Quality & Resolution | 有数据 |
| LLM Token Usage by Model | 有数据 |
| LLM Token Usage by Tenant | 有数据 |
| RabbitMQ Queue Depth | 无数据（未部署 rabbitmq，预期空白） |
| Milvus Collection Stats | 无数据（未部署 milvus，预期空白） |
| Alert Events (Firing) | 无数据（当前无告警触发，属正常） |

任务要求的四类面板（QPS / 延迟 / 状态码 / LLM 调用）全部有数据。

### 5.5 验收脚本总结果

```
结果：24/24 项通过
```

---

## 六、指标验证（流量前后对比）

由 `scripts/generate_monitoring_traffic.py` 实测：

| 指标 | 发送前 | 发送后 | 结论 |
| --- | --- | --- | --- |
| `sum(http_requests_total)` | 3 | 72 | 变化 |
| `sum(rag_search_total)` | 无数据 | 9 | 变化 |
| `ws_active_connections` | 无数据 | 0（连接建立后关闭） | 出现观测 |
| `up{job="app"}` | 1 | 1 | 保持 |

> 聊天段单条实测耗时约 280 秒（内网 7B 在 CPU 上跑完整张图），因此流量脚本默认只发 1 条，需要更多数据点时用 `--chat-count` 调大。

---

## 七、遇到的问题与解决

### 7.1 【重要】长聊天请求把事件循环堵死，导致监控与健康检查双双失灵

**现象**：聊天请求进行中，`/api/v1/health` 与 `/api/v1/metrics/prometheus` 请求全部超时（8 秒仍无响应），
容器健康检查报 `Health check exceeded timeout (5s)`，容器状态被标记 `unhealthy`。

**根因**：`src/api/routes.py` 的 REST `/chat` 处理器是 `async def`，但内部直接同步调用 `app.invoke(...)`。
内网 7B 模型单轮 4~5 分钟，这段时间整个事件循环被独占，所有请求排队。
WebSocket 路径早已用 `await asyncio.to_thread(app.invoke, ...)` 并有注释警告过这类问题，REST 路径遗漏。

**影响**：恰好在「有流量」的时候，Prometheus 抓取失败、健康检查判死。这与可观测性的目的正好相反，属于监控地基问题。

**修复**：改为 `await asyncio.to_thread(app.invoke, state, {...})`。

**修复前后实测对比**：

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 聊天进行中访问 `/api/v1/health` | http=000，8 秒超时 | http=200，**5~8 毫秒** |
| 聊天进行中访问 `/api/v1/metrics/prometheus` | 超时 | http=200，**约 5 毫秒** |
| 容器健康状态 | unhealthy | healthy |

### 7.2 【重要】LLM 指标埋点挂在一条没人调用的方法上

**现象**：一条聊天成功返回（HTTP 200，耗时 280 秒）后，`llm_calls_total` / `llm_tokens_total` 仍然查不到任何数据。

**排查路径**：
1. 代码里有两处上报（`src/agent/agent.py`、`src/graph/nodes.py`），函数确实存在。
2. 但 `nodes.py` 的上报在 reflect 节点内，而节点调用的是 `agent.run_with_trace(...)`。
3. `run_with_trace()` 里**没有任何上报代码**，只有 `run()` 有。而图走的是 `run_with_trace`。

**第二层原因**：`_report_token_usage` 整段被 `if prompt or completion:` 包住，意味着上游不回传 usage 时，
连「调用了一次」都不记。Ollama 的 OpenAI 兼容端点在部分场景下不带 usage，于是双重失效。

**修复**：
- `run_with_trace()` 增加上报（遍历全部 AIMessage，而非只看最后一条，多轮 ReAct 的中间步骤不再漏计）。
- 去掉 `if prompt or completion:` 门槛：**调用次数无条件上报**，token 拿多少报多少。
- reflect 节点同样处理。

### 7.3 监控栈网络与目标全错

见 §3 的 #1 / #2 / #3。修复方式是直接加入业务栈的 `prod-net`，并把抓取目标改成真实存在的服务名。

**为什么会出现这种错配**：监控配置文件是按 cloud 多服务形态（api-service / rag-service / ws-service / milvus / rabbitmq / apisix）编写的，
而当前部署已经演进为内网单容器形态，两者没有同步。这类「配置漂移」不会报错，只会静默地让 targets 全 DOWN。
因此本次把不存在的目标注释保留而不是删除，并加了说明，便于将来切回多服务形态时放开。

### 7.4 告警规则引用了不存在的指标名

`llm_call_errors_total` / `llm_call_total` 在代码里并不存在（真实名是 `llm_calls_total` / `llm_calls_success_total`）。
Prometheus 不会因此报错，规则只是永不触发。已改为按成功率反算失败率：

```
(1 - (sum(rate(llm_calls_success_total[5m])) / sum(rate(llm_calls_total[5m])))) > 0.1
```

### 7.5 离线环境的日志方案退化

本地没有 `grafana/loki` 与 `grafana/promtail` 镜像，且任务约束不允许联网拉取，因此：
- promtail/Loki 两个服务在 compose 里位于 `logging` profile 下，默认不启动，不会因缺镜像报错；
- Grafana 的 Loki 数据源已注释，避免出现永远连不上的条目；
- 日志改走**文件方案**：应用输出结构化 JSON 并落到卷 `prod-agent-logs`（容器内 `/app/logs/app.jsonl`）。

`src/utils/logging.py` 原本已有完整的 JSONFormatter（含 request_id / duration_ms / 敏感字段脱敏），
只是 `src/api/server.py` 从未调用它（只在 `main.py` 调）。本次把容器真实入口接上，并补了文件 handler。

### 7.6 Docker Desktop 未运行

开工时 daemon 未启动（连进程都没有），业务栈与监控栈都无法操作。已拉起并等到 daemon 可达后再继续。

### 7.7 【重要】宿主机代理被注入容器，导致监控容器永久 unhealthy

**现象**：`agent-prometheus` 与 `agent-grafana` 功能完全正常（能查询、能出图），但容器状态长期是 `unhealthy`。

**排查**：健康检查用的是 `wget -qO- http://127.0.0.1:9090/-/healthy`，镜像里 wget 确实存在，
但报 `can't connect to remote host (127.0.0.1): Connection refused`。容器内 `netstat` 显示服务正常监听。

**根因**：Docker Desktop 把宿主机的代理设置注入到了容器里
（`HTTP_PROXY=http://127.0.0.1:7890` 等四个变量）。该代理地址是宿主机的，容器内并不存在。
busybox wget 会把请求发往这个代理，于是连 127.0.0.1 也被代理拦截而失败。

**验证**：在容器内清空代理变量后，同一命令立刻返回 `Prometheus Server is Healthy.`。
补充测试：`no_proxy='*'` 对 busybox wget **无效**，只有显式置空代理变量才行。

**修复**：在 `docker-compose.monitoring.yml` 的 prometheus 与 grafana 服务里显式置空四个代理变量
（监控栈只访问本地服务，本来就不需要代理）。

**效果**：两个容器状态由 `unhealthy` 变为 `healthy`。

> 这个坑值得记住：健康检查失败 ≠ 服务有问题。当健康检查用的工具会走代理时，先怀疑代理注入，
> 再怀疑服务本身。

### 7.8 reflect 节点配置的模型名在本地不存在

容器日志出现 `POST /v1/chat/completions 404`。核对发现 `src/config.py` 的
`llm_complex_model` 默认值是 `qwen-max`（云端百炼模型名），而内网 Ollama 只拉了
`qwen2.5:7b` 与 `bge-m3`。因此 reflect 节点（使用 complex model）的调用必然 404，
被 catch 后静默降级。

影响有限（reflect 失败不影响主链路），但会白白多一次失败的 HTTP 往返，且掩盖了
「反思/复核节点实际未生效」这一事实。建议在内网部署时把 `llm_complex_model` 也指向
`qwen2.5:7b`，或确认该节点是否需要在本形态启用。

---

## 八、已知限制与未完成项

1. **会话数指标缺失**：任务单列出的 `chat_sessions_total` 在代码中不存在，本次未新增（仪表盘用 `ws_active_connections` 与 `agent_requests_tracked_total` 反映会话活跃度）。若要严格对齐，需新增 counter 并在 WS 建连处埋点。
2. **Loki 日志聚合不可用**：受离线镜像缺失限制，只能走文件方案。补齐镜像后取消 `datasources.yaml` 的注释并启用 compose 的 `logging` profile 即可切换。
3. **Prometheus 目标标签冗余**：`service: api` 与指标自带标签同名，产生 `exported_service`，未清理。
4. **面板中有 3 个无数据**：RabbitMQ Queue Depth、Milvus Collection Stats 依赖未部署的组件，属于预期空白。
5. **未做：长时间稳定性观察**。本次为一次性联调验证，未观察数小时级别的抓取连续性与 Grafana 长周期面板。

---

## 九、附录：实测原始输出

### 9.1 容器状态（收尾时实测）

```
agent-grafana          grafana/grafana:11.6.0                                  Up (healthy)
agent-pg-exporter      quay.io/prometheuscommunity/postgres-exporter:v0.16.0   Up
agent-prometheus       prom/prometheus:v3.3.0                                  Up (healthy)
agent-redis-exporter   oliver006/redis_exporter:v1.67.0                        Up
prod-app-1             enterprise-agent-app-ollama:latest                      Up (healthy)
prod-postgres-1        postgres:16-alpine                                      Up (healthy)
prod-redis-1           redis:7-alpine                                          Up (healthy)
```

### 9.2 关键指标终值

| 指标 | 值 |
| --- | --- |
| `http_requests_total`（合计） | 84 |
| `llm_calls_total` | 1 |
| `llm_tokens_total` | 2087 |
| `rag_search_total{hit="true"}` | 9 |
| `ws_active_connections` | 0（连接已关闭） |
| `up{job="app"}` | 1 |

### 9.3 示例结构化日志

容器内 `/app/logs/app.jsonl`（实测第 640 行，文件 128K）：

```json
{"timestamp": "2026-09-15T11:17:49.239087", "level": "INFO", "message": "http_request",
 "logger": "src.access", "request_id": "33a0fe8be432", "duration_ms": 0.5,
 "status_code": 200, "method": "GET", "path": "/health"}
```

字段 `request_id` 与 `duration_ms` 齐备，符合任务单对日志验证的要求。
该文件位于具名卷 `prod-agent-logs`，容器重建后日志仍在。

### 9.4 验收脚本完整输出

见 `docs/PHASE2_MONITORING_evidence.json` 的 `checks` 数组（24 项逐条 PASS/FAIL 与明细）。

---

## 十、复现步骤

```bash
# 1. 确保 Docker Desktop 已启动
docker version --format '{{.Server.Version}}'

# 2. 起业务栈（Phase 1 恢复）
cd C:/Users/hai/enterprise-agent
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d

# 3. 起监控栈（注意要带 prod 的 env file，postgres-exporter 需要正确的库口令）
docker compose -f docker-compose.monitoring.yml --env-file deploy/prod/.env.production up -d

# 4. 产生流量（含聊天，单条约 5 分钟）
python scripts/generate_monitoring_traffic.py --fast-rounds 8 --fast-sleep 12 --chat-count 1

# 5. 验收（逐面板 PromQL 判定 + 日志检查）
python scripts/verify_monitoring_prod.py --report C:/tmp/phase2_monitoring_report.json
```

访问入口：Prometheus `http://localhost:9090/targets`，Grafana `http://localhost:3000`（admin / admin123）。
