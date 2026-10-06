# PROJECT.md — 项目全景（第 1 层）

> 这份文件回答「这个项目是什么」。内容稳定，阶段变更时才需要动。
> 每次开新 AI 会话时，把本文件 + CURRENT.md 一起提供给 AI，它就能恢复现场。
> 不要往这里写进度、待办、临时决策，那些属于 CURRENT.md。

---

## 一句话定位

**工厂级智能客服**：面向工业设备知识库的 AI Agent，支持 RAG 问答、故障查询、多轮对话、引用溯源（含页码）。

**全内网离线部署，运行时零外网依赖。**

项目根目录：`C:\Users\hai\enterprise-agent`
运行环境：Windows 10 + Docker Desktop（WSL2），**纯 CPU 推理**

---

## 技术栈（硬性事实，改动前先确认）

| 层 | 技术 | 关键约束 |
|---|---|---|
| 后端 | FastAPI + LangGraph + LangChain | 端口 8000，入口 `src/api/server.py` |
| 向量库 | Chroma（持久化） | 生产基线 322 块，容器内路径 `/app/chroma_data` |
| LLM | Ollama 本地 `qwen2.5:7b` | CPU 推理，无外网 |
| Embedding | Ollama `bge-m3`（本地） | — |
| Rerank | `bge-reranker-base`（本地） | safetensors 权重内置镜像，约 1.1GB |
| 数据库 | PostgreSQL 16 + Redis 7 | 独立容器，非单容器内嵌 |
| 部署 | Docker Compose | 单容器 app + 独立 pg/redis |
| 监控 | Prometheus + Grafana | **独立栈，4 个容器**，Grafana:3000 / Prometheus:9090 |

---

## 容器拓扑

| 容器 | 栈 | 说明 |
|---|---|---|
| `prod-app-1` | 业务 | 主应用，端口 8000 |
| `prod-postgres-1` | 业务 | 数据库 |
| `prod-redis-1` | 业务 | 缓存 |
| Grafana | 监控 | 端口 3000 |
| Prometheus | 监控 | 端口 9090 |
| node-exporter | 监控 | — |
| cadvisor | 监控 | — |

**数据卷（绝不可丢）**：`prod-agent-chroma` / `prod-postgres-data` / `prod-redis-data`

---

## 三大用户决策（贯穿全项目，不可擅自更改）

| 决策 | 内容 | 当前状态 |
|---|---|---|
| Q1 | `kb_call_mode` 实现真实语义（always / never / smart） | 主线进行中，1/6 步 |
| Q2 | 启用 rerank，用本地 `local_bge` | 已落地 |
| Q3 | 引用需展示页码 | 页码断链根因已修复（chunker 盖物理页戳+WS+前端徽标+单测，2026-10-07），待授权重建索引后生产验证 |

---

## 红线约束（违反会出事故）

1. **运行时零外网依赖**（构建期临时联网除外）
2. **功能完整性优先于镜像体积**,不得以「精简运行时」裁剪 RAG 核心能力
3. **所有结论附文件路径 + 行号证据**,不接受「应该/大概」式描述
4. **compose 操作必须显式指定文件**：`-f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production`
   （不带会操作到项目根目录的旧编排/容器）
5. **未经授权不重启/重建容器、不改业务代码**
6. **重建只重建 app**,postgres/redis 不动，数据卷不丢
7. **改动前先备份**：镜像 tag 备份 + Chroma 卷备份

---

## 执行纪律（全程遵守）

1. 每步执行前先**只读确认**,不跳过验证直接操作
2. 每步验收通过后再进下一步，不累积未验证改动
3. 构建期可临时联网，运行时必须验证离线
4. 遇到异常立刻停止，排查根因后再继续，不绕过

---

## 代码规模（用于判断上下文预算）

- Python 源文件 178 个，前端 TS/TSX 文件 25 个
- **结论：无法一次性读完全量代码。** AI 接手时必须依赖本文件 + CURRENT.md 建立认知，再按需定点读取，不要尝试全量扫描

---

## 文档地图（哪些该读、哪些别碰）

### 权威入口（每次会话都该读）

| 文件 | 作用 |
|---|---|
| `PROJECT.md` | 本文件，项目全景 |
| `CURRENT.md` | 当前状态、阻塞、任务索引 |
| `docs/INDEX.md` | 全项目文档地图，按读者角色分组 |

### 核心参考（按需定点读取）

| 文件 | 内容 |
|---|---|
| `docs/Phase5-后续待完善任务清单.md` | **当前最重要的任务清单**,286 行，行号级证据 |
| `桌面/项目回顾与剩余任务执行计划-PM视角.md` | PM 视角的执行计划，含 T1-T5 详细步骤 |
| `deploy/prod/README-生产部署与运维手册.md` | 生产部署运维 |
| `docs/TESTING.md` | 测试与覆盖率的权威口径 |
| `docs/journal/` | 会话日志（第 3 层，只追加） |
| `PITFALLS.md` | 踩坑清单 |

### 阶段报告（历史归档，按需查阅）

- `Phase3-改动清单与验收报告.md`
- `Phase4a-改动清单与验收报告.md`
- `Phase4b-改动清单与验收报告.md`
- `Phase5-P0-Q1Q3核查报告.md`

### 禁区（体积大或含敏感值，不要加载）

| 文件 | 体积 | 原因 |
|---|---|---|
| `docs-update-1.md` ~ `docs-update-5.md` | 合计约 390KB | 历史快照，全量读取会瞬间耗尽上下文 |
| `.env` / `.env.intranet` / `deploy/prod/.env.production` | 小但含密钥 | 含真实密钥，不要读取或输出内容 |
| `.coverage` | 114KB | 覆盖率二进制数据 |
| `*.bak` 系列 | 分散 | 历史备份，非当前版本 |

---

## 关键命令（必须显式指定 compose 文件）

```powershell
# 只读检查
docker version
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"

# 重建镜像（构建期需临时联网）
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production build app

# 重建 app 容器（pg/redis 不动，数据卷保留）
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app

# 健康检查
curl.exe -s http://localhost:8000/api/v1/health
docker inspect prod-app-1 --format "{{.State.Health.Status}}"

# 全量回归（按冻结口径）
.\venv\Scripts\python.exe -m pytest -o addopts="" -q -n 4 --basetemp=".pytest_tmp" -p no:cacheprovider --deselect tests/test_mcp_tools/test_kb_phase2.py
```

---

## 相关文件

- 当前状态、阻塞、任务索引 → `CURRENT.md`
- 会话日志与决策记录 → `docs/journal/`
- 完整文档导航 → `docs/INDEX.md`
