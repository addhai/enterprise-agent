# CURRENT.md — 当前状态（第 2 层）

> 这份文件回答「现在的真实状态是什么」。每完成一个阶段就覆盖更新一次。
> 与 PROJECT.md 配套：PROJECT.md 讲不变的，本文件讲在变的。
>
> 最后更新：2026-10-04 22:05（本轮全量实测复核）
> 状态来源：`git` 实测 + `pytest` 实跑 + 源码检索，不接受「应该/大概」式描述。
> **本文件所有结论均可溯源，不接受「应该/大概」式描述。**

---

## 一句话状态

代码侧全部收官：23 个 commit 已入库并 push，**286 条未入库风险已消除**。
全量回归 `1472 passed, 17 skipped`（本轮实测，271s）。
**唯一未收官主线**：Phase5「kb_call_mode 语义收口」—— 判据模块与单测已入库（76 用例全绿），但**调用方 `rag_node` 尚未接入**。
**当前卡死**：Docker daemon 未运行，所有容器级动作停摆。

---

## 头号风险（已解除）

### ~~286 条改动未入库~~ → 已解决（2026-10-04）

| 项 | 2026-09-30 实测 | 2026-10-04 实测 |
|---|---|---|
| git HEAD | `b119f24` 2026-09-22 | **`47768bc` 2026-10-04 19:39** |
| 未提交改动 | **286 条** | **0 条**（工作区与暂存区均干净） |
| 未跟踪文件 | 132 个 | **1 个**（`.pytest_tmp_run/`，pytest 临时目录，非产物，可删） |
| 与 `origin/master` 差异 | 未推送 | **0 / 0 完全同步** |
| 远端跟踪文件 | — | **657 个** |
| `call_policy.py` / `test_call_policy.py` | `??` 未跟踪 | **已入库**（commit `1fbe790`） |

**结论：Phase3 → Phase5 全部成果已有远端备份点，误操作丢失风险已解除。**

⚠️ 剩余 1 个未跟踪项是 pytest 的 `--basetemp` 目录，属临时产物，不应提交。

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
| **P0/P1 交付文档** | API / 上线 / 回滚 / 监控 / 安全 / 测试 / 质量基线 | **完成（入库）** | — |
| **P2 部署套件** | 独立 Dockerfile + compose + Grafana→飞书告警链路 | **完成（入库）** | — |
| **kb_call_mode 主线** | 判据模块已入库，调用方未接入 | **进行中（1/6 步）** | 单测 76 passed |

**当前回归基线（本轮实测）：`1472 passed, 17 skipped, 1 warning in 271.24s`**

---

## 主线：kb_call_mode 语义收口（唯一未收官项）

### 已完成（已入库，实测复核）

| 文件 | 行数 | 状态 |
|---|---|---|
| `src/rag/call_policy.py` | 454 行 | 已入库（`1fbe790`），**单测 76 passed / 8.54s** |
| `tests/test_rag/test_call_policy.py` | 421 行 | 已入库（同上） |
| `docs/Phase5-kb_call_mode语义收口-拆解方案.md` | — | 已入库 |

### 卡在第 3 步：调用方未接入

**实测结论（2026-10-04）：`src/graph/nodes.py` 中 `call_policy|decide_retrieval|judge_probe|retrieval_decided_by` 命中数 = 0。**

⚠️ **修正旧记录的错误**：旧版 CURRENT.md 称「三分支逻辑在 `nodes.py:1098-1163`，非法值回落 `smart` 需改为 `always`」。实测该结论**不成立**：

- `nodes.py` 全文**不存在任何 `kb_call_mode` 分支**（`call_mode|== "never"|== "always"|== "smart"` 均 0 命中）
- `nodes.py:1085-1165` 实际内容是 `final_response` 节点的**意图澄清 / 低置信度拒答 / 回复精简**逻辑，与 kb_call_mode 无关
- `nodes.py` 末次改动为 `c97a02c fix(ci): 修复测试体系并使 CI 转绿`

**即：不是「三分支待改造」，而是「三分支从未实现，接入时按拆解方案新建」。** 接入时需按 `call_policy.py` 的 docstring 约束实现三分支，非法值回落 `always`（`MODE_ALWAYS` 为默认，见 `call_policy.py:48-50`）。

### 最致命的技术缺陷（P0-4，仍未解决）

`call_policy.py` docstring 自述（第 13-30 行）：

- `metadata["score"]` 是 RRF 组内**相对分**（`retriever.py:320-334`），top1 恒为 1.0
- `metadata["rerank_score"]` 由 `BaseReranker._normalize` min-max 归一化（`reranker.py:91-111`），top1 同样恒为 1.0
- RRF 原始分 `raw_score` 由排名决定（权值 /(k+rank+1)），单榜区间 0.0164~0.0328，窄且与语义相关性无单调关系

**结论：不补绝对相似度信号，smart 语义上等价于 always，「语义收口」名不副实。**

模块已给的三级退化路径（docstring 已写明）：
1. `metadata["vector_similarity"]`（未归一化绝对分）→ 门槛 `kb_similarity_threshold`
2. 调用方显式传 `min_raw_score` → 用 RRF 原始分下限（**需生产实测标定**）
3. 两者皆无 → 退化为 `signal="nonempty"`（探测列表非空即命中，保守）

**要让 smart 真正有判别力，必须让检索侧补出方案 1 的绝对信号。**

---

## 代码与镜像的落差（4 项改动仍未上线）

Docker daemon 未运行，无法读取现网镜像状态。改用 `git log` 取证：

`Dockerfile` 末次改动为 `a07d7d2`（**2026-07-15 05:57**），只 `COPY` 了 `requirements.txt` / `src/` / `scripts/`。以下 4 项代码已就位但**不在镜像覆盖范围内**：

| 改动 | 位置 | 缺什么 |
|---|---|---|
| `StaticFiles` 条件挂载 | `src/api/server.py:425-441` | Dockerfile 无 `COPY static/` |
| 前端构建产物 | `frontend/vite.config.ts` → `outDir: '../static'` | 未纳入镜像构建 |
| `health_checker.py` 修复 | `src/protocols/health_checker.py`（**526 行**，末次改动 `44f8943`） | 未重新构建镜像 |
| `logging.py` 结构化 JSON 日志 | `src/utils/logging.py` | 同上 |

**坐实证据**：Phase4b 验收（2026-09-21）实测 `GET /` 返回 **404**（现网镜像不托管前端）。
⚠️ `static/` 被 `.gitignore` 忽略，CI 与纯后端环境不存在该目录 —— `server.py:419-424` 注释记录了 GitHub Actions 曾因此连续红灯，代码已用 `is_dir()` 守卫解决，**但 Dockerfile 侧仍需显式构建前端或明确接受只发 API**。

---

## 生产口径注入缺失（P0-7，仍未做）

| 文件 | `KB_CALL_MODE` | `RERANK_MODEL` |
|---|---|---|
| `deploy/prod/.env.production` | **0 处命中** | **0 处命中** |
| `deploy/prod/docker-compose.prod.yml`（`app.environment`） | **未注入** | **未注入** |

**注意**：只写 env 不生效，必须同时在 compose `environment:` 注入（Phase4b 已踩过同类坑）。

已就位的：`LLM_MODEL=qwen2.5:7b`、`AGENT_PROBE_ENABLED=false`（env + compose 第 62 行透传）、`POSTGRES_PASSWORD` / `JWT_SECRET` 已轮换为随机值。
**配置定义侧已完整**（不阻塞，只欠注入）：`src/config.py:100` 默认 `"always"`、`src/config_center/schema.py:125` 枚举三项、`categories.py:37` 已列入配置中心、`src/api/config.py:48` 已列入可热更新白名单。

---

## 当前阻塞（2026-10-04 实测）

| # | 阻塞 | 实测证据 | 影响 |
|---|---|---|---|
| 1 | **Docker daemon 未运行** | `docker version` → `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine` | P0-9~P0-11、P1-6、P1-7 容器部分、P3 全部停摆 |
| 2 | **`rag_node` 未接入 call_policy** | `nodes.py` 检索命中数 = 0 | Phase5 主线停滞，smart 模式线上不存在 |
| 3 | **无绝对相似度信号** | `call_policy.py` docstring 自述 | 即使接入，smart ≡ always |
| 4 | **生产口径未注入** | `.env.production` 0 处命中 | 线上跑的是 `always` 默认值 |

---

## 下一步执行顺序（按依赖）

```
P0-1 启动 Docker Desktop
  ↓
┌────────────────────────────────────────┐
│ 开发侧（不依赖 Docker，可立即做）        │
│ P0-4 检索侧补 vector_similarity 绝对信号 │
│ P0-3 rag_node 接入 call_policy 三分支   │
│ P0-6 call_policy 三分支单测补齐          │
└────────────────────────────────────────┘
  ↓
P0-7 生产口径注入 KB_CALL_MODE + RERANK_MODEL
  ↓
P0-8 前端构建 static/ → 纳入 Dockerfile
  ↓
P0-9 重建镜像 + 重建 app 容器
  ↓
P0-10 前端闭环验证 / P0-11 页码徽标实测 / P1-6 探针报错实测
  ↓
P1-7 全量回归 → P3 交付合规复验
```

⚠️ **顺序已调整**：原 P0-2「工作区快照」已完成（代码全部入库并 push），从序列中移除。
**P0-4 提到 P0-3 之前** —— 先有绝对信号，smart 接入才有意义，否则接了也是 always。

关键命令（compose 必须显式指定文件，否则会操作到错误的编排）：

```powershell
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production build app
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app
```

---

## 任务清单索引

完整清单见 `docs/Phase5-后续待完善任务清单.md`（286 行，含行号级证据）。
kb_call_mode 主线的技术方案见 `Phase5-kb_call_mode语义收口-拆解方案.md`（已入库）。

| 组 | 数量 | 内容概要 | 状态 |
|---|---|---|---|
| P0 | 11 项 | 阻塞项：Docker 启动、主线接入、绝对信号、口径注入、重建镜像、闭环验证 | 快照已解，余 10 项 |
| P1 | 9 项 | 功能补齐：chapter_path 透出、页码覆盖率、探针实测、全量回归 | 部分随本轮入库推进 |
| P2 | 10 项 | 遗留缺陷：session_id 双写、WS 推理不取消、端到端延迟、代理变量清理 | **部署套件已入库** |
| P3 | 6 项 | 交付合规复验：外网审计、离线变量、数据完整性、文档归档 | **交付文档已入库**，复验待做 |

---

## 本轮（2026-10-04）已解决项 —— 不要重复排查

### 修复的 6 个实质缺陷

| # | 缺陷 | 位置 | 性质 |
|---|---|---|---|
| 1 | QPS 用 `max(latencies)` 当总耗时，并发被忽略（并发 1 与 20 算出同数） | `scripts/benchmark/bench_chat_concurrency.py` | 性能数据失真 |
| 2 | 用了 `urllib.request` 但未 import，走到登录/建库分支直接 `NameError` | `tests/rag_eval/eval_recall.py` | 脚本必崩 |
| 3 | 启动时打印 `FEISHU_WEBHOOK[:50]`，机器人 URL 本身就是凭据 | `deploy/monitoring/feishu_adapter/app.py` | **凭据泄露** |
| 4 | 测试 6「引用片段截断」写死 `True`，等于没测 | `scripts/acceptance_test.py` | 假验证 |
| 5 | `base_url` 无协议校验，误传 `file:///etc` 会读本地文件 | `scripts/benchmark/` 三个脚本 | 路径穿越 |
| 6 | 默认绑 `0.0.0.0` 且无认证，等于把代理开放给整个局域网 | `scripts/proxy_relay.py` | 暴露面 |

修复 #1 后实测：并发 1/5/20 → **9.9 / 49.4 / 192.1 QPS**（理论值 10/50/200）。

### 已确认修好的历史项

`.txt` 上传（`0dd8e34`）、配置中心热更新 + 审计（`f88bc1f`/`173fd0d`）、结构化 JSON 日志（`2cae275`）、A2A 缓存 / 文档权重 / 来源配额 / 查询改写（`d2a12c3`）、上传安全校验 / LLM 热重建 / `recursion_limit`（`9270c55`）、`pyproject.toml:55-59` 的 `-n=4`、vite 端口 5173 与 `outDir: '../static'`、WS keepalive（`docker-compose.prod.yml:67` → 300s）。
**代码就绪待生产验证**：前端页码徽标 `frontend/src/App.tsx:759-761`、`:1195-1196`。

### 归档与仓库卫生

`dev/` 归档区已建（探针、验收残片、前端截图去重）；`.pre-commit-config.yaml` 的 ruff / ruff-format 加 `exclude: ^dev/`；`dev/acceptance_report_2026-09.md` 已在 `dev/README.md` 标注「内容残缺含写死常量，不要当作有效验收结论」；远端 657 文件仅 `.example` 与 Helm 占位符，gitleaks 扫 23 个 commit 零泄漏。

---

## 待核实异常

- `health_checker.py` 行数三方口径冲突：完成度总报告（09-21）记 **529 行** → 旧 CURRENT.md 记 **469 行** → 本轮实测 **526 行**（`44f8943`）。需确认 526 行是否为最终修复版、是否曾被回退（P1-8）
- 前端产物滞后：`static/` 时间戳 09-17，`App.tsx` 已改到 09-22，需重新构建（P0-8）
- `static/` 被 `.gitignore` 忽略，Dockerfile 需决定：构建前端，还是明确只发 API

---

## 更新规则

- 完成一个阶段 → 覆盖对应区块
- 阻塞解除 → 从「当前阻塞」移出，记入日志
- 决策了下一步 → 更新执行顺序
- 行号引用**必须实测复核**，代码一改行号就漂移（旧记录已因此产生三处错误行号）
- **本文件控制在 240 行以内。** 详细证据链放 `docs/` 与 `Phase*-改动清单与验收报告.md`，这里只保留结论与索引
