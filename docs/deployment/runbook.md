# 部署与验证 Runbook（生产级全栈）

本文件把 README「能力边界」里那句"完整 12 服务栈长时间联跑尚未在本机完成"
变成**可复现、可判定**的操作。三类验证对应三条待闭环的缝：

| 缝 | 验证脚本 | 是否需要 docker | 证明什么 |
|----|----------|----------------|----------|
| 全栈真跑（应用层） | `scripts/verify_fullstack_local.py` | 否 | 多无状态副本 + 共享存储 + WS 活跃连接 gauge 运行时 +1 + 指标端点吐 agent_* gauge + RAG 检索命中 |
| 全栈真跑（容器栈） | `scripts/verify_fullstack.py` | 是 | 12 服务全部存活 + 经 APISIX 网关端到端建单/读单 |
| Grafana 真渲染 | `scripts/verify_monitoring.py` | 是 | Prometheus 抓取后，每个面板 PromQL 返回非空（非"JSON 合法却空白"） |

---

## 0. 前置（任何验证前）

```bash
cp .env.example .env        # 填入真实 key；仅在可信本机，key 永不上公网
npm install && npm run build   # 生成 static/（前端托管目录）
```

- **密钥红线**：真实 key 只在本机 `.env`，绝不进仓库、绝不挂公网。对外展示用 README 内嵌的 demo.gif / rag_demo.gif（真实 WS 对话驱动，非截图伪造）。
- 沙箱（CI / 无 docker daemon 环境）只能跑 `verify_fullstack_local.py`；容器栈与监控需在装有 Docker Desktop 的机器上跑。

---

## 1. 应用层全栈验证（无需 docker，沙箱可跑）

```bash
./venv/Scripts/python.exe scripts/verify_fullstack_local.py
```

- 起 2 个独立 uvicorn 实例（等价于 2 个容器副本），共用 SQLite 存储 + 本地 chroma。
- 断言：副本独立存活 / 共享存储一致（A 建单 B 读到）/ 持久 WS 连接时 `ws_active_connections` 指标真的 >=1 / 指标端点吐 `http_requests_total` 与 `agent_*` gauge / RAG 检索命中 / 各副本独立 accept WS。
- 退出码 0 = 通过。

> 这条已在沙箱实测通过（见最近一次 commit 的 CI 之外本地运行记录）。

---

## 2. 完整容器栈验证（需 docker daemon）

```bash
docker compose up -d --scale api-service=3 --scale ws-service=3
./venv/Scripts/python.exe scripts/verify_fullstack.py
docker compose down
```

- `verify_fullstack.py` 先 `docker compose up -d`，轮询 12 服务健康，再经 APISIX 网关（:9080）跑端到端建单/读单。
- **判定标准**：至少半数 HTTP 服务存活 + 网关端到端工单链路通过 = 全栈真跑验证通过。
- 这条在沙箱无法执行（daemon 未起），需在本地 Docker Desktop 环境补齐，并把结果回填 README「能力边界」。

---

## 3. Grafana 面板真渲染验证（需 docker daemon）

```bash
# 先起后端（让 Prometheus 有抓取目标）
./venv/Scripts/python.exe -m uvicorn src.api.server:app --port 8000 &
docker compose -f docker-compose.monitoring.yml up -d
./venv/Scripts/python.exe scripts/verify_monitoring.py
docker compose -f docker-compose.monitoring.yml down
```

- `verify_monitoring.py` 起 prometheus + grafana，等抓取若干轮后，逐面板执行 `deploy/monitoring/grafana/dashboards/agent-overview.json` 里的 PromQL，断言返回非空。
- **判定标准**：所有面板 PromQL 均返回数据 = Grafana 真能出数（非配置正确但空白）。
- 若某面板为空：先用 `curl localhost:9090/api/v1/query?query=<expr>` 手工确认，多半是 scrape 路径或数据源 uid 配置问题（C 档已修，正常应通过）。

---

## 4. 云资源真实性（受 key + 付费 阻断，需用户操作）

演示默认 `ALIYUN_DEMO_FALLBACK=true`：真实阿里云 API 优先，无匹配资源时回退样本（每条结果由 `src/mcp_tools/resource.py` 的 `_source_note` 标注数据来源）。要变"全真"：

1. 在阿里云账号购买/创建真实资源（涉及付费，需用户确认）。
2. `.env` 填真实 `ALIYUN_ACCESS_KEY_ID/SECRET`（子账号只读策略）。
3. `.env` 设 `ALIYUN_DEMO_FALLBACK=false`。
4. 重启后端，资源查询即走 100% 真实 API（`_source_note` 显示"数据来源：阿里云实时 API"）。

> 这一步的"全真"必须由用户付费 + 提供真实 key 完成；代理不擅自购买资源、不碰真实 key。

---

## 5. 验证清单（合并进简历话术）

- [x] 应用层全栈运行时验证（`verify_fullstack_local.py`，沙箱实测通过）
- [ ] 完整 12 服务容器栈（`verify_fullstack.py`，待 Docker 环境补齐）
- [ ] Grafana 面板出数（`verify_monitoring.py`，待 Docker 环境补齐）
- [x] RAG 检索命中（rag_demo.gif 真实验证 + 本地脚本 hit_test）
- [x] 多副本水平扩展（verify_multireplica.py）
- [x] 多租户 RBAC 隔离（test_ws_tenant_isolation.py）
- [x] 可观测性链路（test_observability.py）
