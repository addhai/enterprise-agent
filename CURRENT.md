# CURRENT.md — 当前状态（第 2 层）

> 这份文件回答「现在的真实状态是什么」。每完成一个阶段就覆盖更新一次。
> 与 PROJECT.md 配套：PROJECT.md 讲不变的，本文件讲在变的。
>
> 最后更新：2026-09-30
> 状态来源：`Phase5-后续待完善任务清单.md`（2026-09-27 只读核查）+ 本轮实测复核（2026-09-30）
> **本文件所有结论均可溯源，不接受「应该/大概」式描述。**

---

## 一句话状态

Phase3 → Phase5 性能基准**全部完成**，核心目标达成。
**唯一未收官主线**：Phase5「kb_call_mode 语义收口」完成 1/6 步，判据模块已写但未接入 `nodes.py`。
**当前卡死**：Docker daemon 未运行，所有容器级动作停摆。

---

## 头号风险（必须先处理）

### 286 条改动未入库，HEAD 停在 2026-09-22

| 项 | 实测值（2026-09-30 复核） |
|---|---|
| git HEAD | `b119f24` 2026-09-22 20:44:14 `docs: 新增生产部署与运维手册` |
| 未提交改动 | **286 条**（09-27 核查时为 280，三天内又增 6 条） |
| 未跟踪的关键文件 | `src/rag/call_policy.py`（16581 字节）、`tests/test_rag/test_call_policy.py` |

**这意味着 Phase3 → Phase5 的全部成果都还没有备份点。一次误操作可能全部丢失。**
动手改任何代码之前，先做快照（分支 / stash / 压缩包）。这是 P0-2。

---

## 阶段进度全景

| 阶段 | 内容 | 状态 | 回归基线 |
|---|---|---|---|
| Phase3 | 离线改造（LangGraph + Chroma + WebSocket + 多租户） | 完成 | — |
| Phase4a | 外网残留收口 + local_bge 补齐 | 完成 | 1407 passed |
| Phase4b | 生产配置收口 + 镜像重建 + WS 联调 + L3/L4/L5 修复 | 完成 | 1413 → 1417 passed |
| Phase5 P0 | Q1/Q3 功能状态核查 | 完成 | — |
| Phase5 P1 | 前端页码徽标 + kb_call_mode 测试 + T90 PDF 入库 + WS keepalive | 完成 | 1417 passed |
| Phase5 性能基准 | 镜像 14.7GB → 4.5GB；F02 查询 558s → 112s | 完成 | 1417 passed |
| **Phase5 主线** | **kb_call_mode 语义收口** | **进行中（1/6 步）** | — |

---

## 主线为什么卡住（技术核心）

### 已完成的部分

- `src/rag/call_policy.py`（337 行）判据模块**已写完**
- `tests/test_rag/test_call_policy.py`（299 行）单测**已写完**
- 但两者都是 `??` 未跟踪状态，未入库

### 卡在第 3 步：未接入

- `src/graph/nodes.py` 全文搜索 `call_policy|decide_retrieval|judge_probe|retrieval_decided_by` = **0 处命中**（2026-09-30 复核仍为 0）
- 三分支逻辑仍是 Phase3 旧版：归一化 `:1098-1102`、never 直答 `:1106-1135`、always 预检索 `:1137-1163`
- 非法值回落目标不符：`nodes.py:1100` 仍是回落 `smart`,而冻结决策要求回落 **`always`**

### 最致命的技术缺陷（P0-4）

`call_policy.py` 的 docstring 自己承认了设计缺口：

- `metadata["score"]` 是 RRF 组内**相对分**,`rerank_score` 是 min-max **归一化**分
- 两者 **top1 恒为 1.0**,无法用作「是否该检索」的判据
- 无绝对信号时退化为 `signal="nonempty"`（探测列表非空即命中）

**结论：不补绝对相似度信号，smart 语义上等价于 always,「语义收口」名不副实。**
这是整个 Phase5 主线里技术含量最高的一项。

---

## 代码与镜像的落差（4 项改动未上线）

现网镜像构建于 **2026-09-20 13:21**,落后于代码：

| 改动 | 位置 | 是否在现网镜像 |
|---|---|---|
| `StaticFiles` 条件挂载 | `src/api/server.py:427-446` | 否 |
| `COPY static/` | `Dockerfile:72`（HEAD 版无此行） | 否 |
| `health_checker.py` 修复 | `src/protocols/health_checker.py`（469 行） | 否，容器内仍是损坏版 |
| `logging.py` 改动 | `src/utils/logging.py` | 否 |

**坐实证据**：Phase4b 验收（2026-09-21）实测 `GET /` 返回 **404**（现网镜像不托管前端）。

---

## 生产口径注入缺失（P0-7）

| 文件 | `KB_CALL_MODE` | `RERANK_MODEL` |
|---|---|---|
| `deploy/prod/.env.production` | 无（2026-09-30 复核：0 处命中） | 无 |
| `deploy/prod/docker-compose.prod.yml`（`app.environment` 31-62 行） | 无 | 无 |

**注意**：只写 env 不生效，必须同时在 compose `environment:` 注入（Phase4b 已踩过同类坑）。

已就位的：`LLM_MODEL=qwen2.5:7b`、`AGENT_PROBE_ENABLED=false`（env + compose 第 62 行透传）、`POSTGRES_PASSWORD`/`JWT_SECRET` 已轮换。

---

## 当前阻塞（2026-09-30 复核）

| # | 阻塞 | 实测 | 影响 |
|---|---|---|---|
| 1 | **Docker daemon 未运行** | `docker version` → `failed to connect to the docker API at npipe:...` | P0-9~P0-11、P1-6、P1-7 容器部分、P3 全部停摆 |
| 2 | **286 条改动未入库** | `git status --short` 计数 286 | 误操作可能丢失全部成果 |
| 3 | **call_policy 判据信号缺陷** | `call_policy.py` docstring 自述 | smart 接入后仍等价 always |

---

## 下一步执行顺序（按依赖）

```
P0-1 启动 Docker Desktop
  ↓
P0-2 工作区快照（分支/stash/压缩包）
  ↓
┌────────────────┬────────────────┐
│ 开发侧         │ 运维侧         │
│ P0-3~P0-6      │ P0-7 生产口径  │
│ （含 P0-4）    │ KB_CALL_MODE   │
└────────────────┴────────────────┘
  ↓
P0-8 前端构建 static/
  ↓
P0-9 重建镜像 + 重建 app 容器
  ↓
P0-10 前端闭环验证 / P0-11 页码徽标实测 / P1-6 探针报错实测
  ↓
P1-7 全量回归 → P3 交付合规复验
```

关键命令（compose 必须显式指定文件，否则会操作到错误的编排）：

```powershell
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production build app
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app
```

---

## 任务清单索引

完整清单见 `docs/Phase5-后续待完善任务清单.md`（286 行，含行号级证据）。

| 组 | 数量 | 内容概要 |
|---|---|---|
| P0 | 11 项 | 阻塞项：Docker 启动、快照、主线接入、绝对信号、口径注入、重建镜像、闭环验证 |
| P1 | 9 项 | 功能补齐：chapter_path 透出、页码覆盖率、探针实测、全量回归 |
| P2 | 10 项 | 遗留缺陷：session_id 双写、WS 推理不取消、端到端延迟、代理变量清理 |
| P3 | 6 项 | 交付合规复验：外网审计、离线变量、数据完整性、文档归档 |

---

## 已确认修好的项（不要重复排查）

| 项 | 位置 | 状态 |
|---|---|---|
| pytest 并行参数 | `pyproject.toml:55-59` → `-n=4` | 已解 |
| vite 端口冲突 | `frontend/vite.config.ts` → `server.port: 5173` | 已解 |
| vite 构建输出 | `frontend/vite.config.ts` → `build.outDir: '../static'` | 已解 |
| WS keepalive | `deploy/prod/docker-compose.prod.yml:67` → 300s | 已就位 |
| 前端页码徽标代码 | `frontend/src/App.tsx:759-761`、`:1195-1196` | 代码就绪，待生产验证 |

---

## 待核实异常

- `health_checker.py` 行数口径冲突：完成度总报告（09-21）记 **529 行**,本轮实测 **469 行**（可编译）
- 需确认 469 行是否为最终修复版、是否曾被回退（P1-8）
- 前端产物滞后：`static/` 时间戳 09-17，`App.tsx` 已改到 09-22，需重新构建（P0-8）

---

## 更新规则

- 完成一个阶段 → 覆盖对应区块
- 阻塞解除 → 从「当前阻塞」移出，记入日志
- 决策了下一步 → 更新执行顺序
- **本文件建议控制在 200 行以内。** 详细证据链放 `docs/`，这里只保留结论与索引
