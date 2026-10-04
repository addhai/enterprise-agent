
# Phase4b 验收报告

> 项目：enterprise-agent（工业知识库 AI Agent，内网全离线私有部署）
> 阶段：Phase4b 生产栈部署收尾验收
> 报告生成：2026-09-21

---

## 一、执行概述

| 项 | 内容 |
|---|---|
| 执行时间 | 2026-09-21（单次验收会话，分 5 步顺序执行） |
| 执行环境 | Windows 11（Build 26200）+ Docker Desktop（WSL2 后端，Docker ServerVersion 29.7.2）；Shell 为 PowerShell 5.1；测试解释器 Python 3.14.2 / pytest 9.1.1 |
| 执行范围 | 业务栈 `deploy/prod`（容器 `prod-app-1` / `prod-postgres-1` / `prod-redis-1`，compose 项目名 `prod`） |
| 明确不动 | 监控栈容器（prometheus / grafana / redis-exporter / pg-exporter）、数据卷、业务代码、镜像构建 |
| 执行方式 | Marvis Agent 分步执行 + 人工逐步确认（每步完成后暂停，等待确认再进入下一步） |

约束遵守情况：全程未执行 `docker compose up`（无 `-f` / `--no-build` 的裸跑）、未构建或重建镜像、未修改业务代码、未删除数据卷、未操作监控栈容器。

---

## 二、前置状态

1. 业务栈容器执行前处于**关闭**状态；
2. 监控栈 4 个容器（prometheus / grafana / redis-exporter / pg-exporter）**持续运行**，由 Docker restart 策略自动拉起，与本次操作无交集；
3. 第二次构建产出的新镜像**已生成但未经部署验证**；
4. 数据卷**完整保留**，执行期间未做任何清理或重建。

---

## 三、分步执行结果

### 第1步：镜像验证

**证据**

- `docker images` 中 enterprise-agent 相关镜像：
  - `enterprise-agent-app-ollama:latest` → **ID `e798a4a3f4ee`**，大小 **4.5GB**，CREATED **2026-09-20 13:21**；
  - 同仓库另有 `backup-14.7gb` 标签（旧镜像），及 `ws-service` / `rag-service` / `agent-worker` / `api-service`（2026-08-10 或 09-19/20）。
- `docker inspect prod-app-1` → 容器实际锁定镜像摘要 `sha256:e798a4a3f4ee...`，与 `latest` 完全一致。

**附带事实**：`agent-feishu-adapter` 容器锁定 `3801b188b4f0`（`backup-14.7gb` 旧镜像），该容器由 `docker-compose.monitoring.yml`（项目 `enterprise-agent`）创建，**不在业务栈范围内**。

**结论**：新镜像存在，且已被业务容器实际使用。

---

### 第2步：compose 一致性验证

**证据**

- 真实编排文件路径：`C:\Users\hai\enterprise-agent\deploy\prod\docker-compose.prod.yml`（项目根目录**无**此文件）；
- 执行命令：

```
cd C:\Users\hai\enterprise-agent\deploy\prod
docker compose -p prod -f docker-compose.prod.yml --env-file .env.production up -d --no-build
```

- 输出：`Container prod-app-1 Running`（**unchanged**），`prod-postgres-1` / `prod-redis-1` 同为 unchanged。

**过程说明**：首次在项目根目录执行失败，报 `couldn't find env file .env.production`，原因是 `.env.production` 实际位于 `deploy\prod`；经用户确认后改在该目录执行并显式指定 `-p prod`，得到零变更结果。

**结论**：compose 配置与实际运行状态无漂移，容器未被重建。

---

### 第3步：健康检查

**证据**

- 容器日志（`docker logs prod-app-1 --tail 80`）：
  - `datetime` / `dateutil` / `strptime` 相关报错 **0 命中**；
  - 无 `ERROR` / `CRITICAL`；
  - 启动序列完整，`rerank=True`，嵌入模型为 `bge-m3`（1024d）。
- 唯一 WARNING：`Health checker start failed: unexpected indent (health_checker.py, line 24)`。
- HTTP 端点实测：

| 端点 | 状态 | 返回 |
|---|---|---|
| `GET /api/v1/health` | **200** | `{"status":"ok", ...}` |
| `GET /api/v1/metrics/prometheus` | **200** | 7759 字节 |
| `GET /health` | 404 | 根路径**无**该路由 |
| `GET /metrics` | 404 | 根路径**无**该路由 |

> 注意：项目统一使用 `/api/v1/` 前缀，根路径 404 属正常，非故障。

**已知问题**：`health_checker.py` 第 24 行缩进错误，导致后台健康检查组件未启动；**不影响 HTTP 端点与主链路**，本次记录不修复。

**结论**：服务健康，`monitoring.py` 的 UTC 兼容修复已生效并通过实测验证。

---

### 第4步：WebSocket 端到端联调

**证据**

- 端点：`ws://localhost:8000/ws/chat`（**非** `/ws`）。源码确证：`src\websocket\routes.py:101` `@router.websocket("/ws/chat")`。
- 鉴权：JWT 经 URL query `?token=` 传入（`src\websocket\routes.py:70-73`），HS256 校验，与 REST 共用 `JWT_SECRET`；登录接口 `POST /api/v1/auth/login`（`admin` / `admin123`，`super_admin`，`tenant=default`，JWT 有效期 12h）。
- 测试问题：**ThermoView T100 的测温范围是多少？**
- 执行结果：

| 指标 | 结果 |
|---|---|
| 握手 | 成功（`State=Open`） |
| 耗时 | 22 秒 |
| 流式文本 | 含 **"-20℃ 至 550℃"** |
| 末帧 | `done=true` |
| citations | **3 条** |
| 关闭 | `State=Closed`（正常关闭） |

- citations 详情：

| # | 文档 | doc_id | score |
|---|---|---|---|
| 1 | product_spec_manual.md | KB-406367 | 1.0 |
| 2 | product_spec_manual.md | KB-406367 | 0.964 |
| 3 | application_guide.md | KB-B4DB00 | 0.9095 |

kb_id：`KBS-050822`。

- **token 生效验证**：`GET /api/v1/admin/sessions` 返回 31 条会话，其中承载本次提问的持久化会话 `c0f68278-1de4-44cf-b189-0cd0d40d8e4e` 的 `user_id = admin-default`（**非** `anonymous`），`last_message_preview` 与本次提问内容一致。据此判定 JWT 身份已生效，匿名降级分支未触发。

**已知问题（第4步相关）**

1. **citations.page 全为 null** —— 经源码定性为**设计如此**：`page` 唯一注入点在 `src\rag\loaders\pdf_loader.py:22-56`（仅 PDF，按 `---PAGE-BREAK---` 标记计数页码）；`src\rag\loaders\markdown_loader.py:27-65` 不写入 page；引用层 `routes.py:519` 取不到即置 `None`。当前知识库仅两份 `.md` 文档，故 page 必然为 null。
2. **session_id 双写不一致** —— 建连阶段 `routes.py:112` 无条件自生成 uuid 并随首帧 `session_ready` 下发（`ecd349d4-7716-483d-a003-0d6a9b53a7cc`）；客户端传入的 `c0f68278-...` 在 `chat_message` 阶段被采纳（`routes.py:332-333`）并落库，两 id 并存。定性为**设计瑕疵**，非单纯预期行为。
3. **session_ready 帧不带 tenant/user 字段** —— `routes.py:149-154` 与 `routes.py:381-386` 两处发送点均仅含 `type / session_id / message / timestamp`；身份解析结果保留在服务端属**防伪造设计**，但连接日志（`routes.py:121`）与会话日志（`session_manager.py:137-141`）均无身份回执，**可观测性不足**。

**结论**：WS 主链路通过，RAG 检索命中正确文档，token 生效已闭环。

---

### 第5步：全量回归测试

**证据**

- 执行目录：`C:\Users\hai\enterprise-agent`（非 `deploy/prod`）
- 执行命令：

```
cd C:\Users\hai\enterprise-agent
.\venv\Scripts\python.exe -m pytest -o addopts=-q
```

- 结果（耗时 **286.71s**，退出码 **0**）：

| 指标 | 数值 |
|---|---|
| 收集 | 1440 |
| **passed** | **1417** |
| **skipped** | **23** |
| **failed** | **0** |
| errors | 0 |

- 跳过归因：23 条与 `requires_llm` / `integration` marker 的收集数完全一致；在未设 `RUN_LLM_TESTS=1` 时按设计跳过（需真实 LLM/Embedding 凭据），非异常缺失。
- 测试配置：唯一配置位于 `pyproject.toml` `[tool.pytest.ini_options]`（`testpaths=["tests"]`、`asyncio_mode="auto"`、markers 为 `integration` / `requires_llm`）；`tests\conftest.py` 的 session 级 autouse fixture 强制 `sqlite:///:memory:`，Redis 相关用例经 monkeypatch 降级内存，**不连接生产数据库/中间件**；98 个 `test_*.py`，16 个子目录。
- **已知配置问题**：`pyproject.toml` 的 `addopts` 中 `-n auto` 在本机 pytest 9.1.1 下被解析为 `' auto'`（带前导空格），默认命令报 `invalid parse_numprocesses value: ' auto'` 并以退出码 4 终止；本次以 `-o addopts=-q` 规避，副作用是 `--cov=src` 覆盖率门禁（`fail_under=40`）未生效。该文件属工程配置，本次**未修改**，需单独授权。
- 与 Phase4a 对比：passed **1407 → 1417**（+10），skipped 均为 **23**。

**结论**：无回归。

---

## 四、已知问题与遗留项（汇总表）

| 编号 | 问题 | 严重度 | 类型 | 位置 | 本次处理 |
|---|---|---|---|---|---|
| 1 | health_checker.py:24 缩进错误 | 中 | 代码缺陷 | `src/api/health_checker.py` | 记录，未修复 |
| 2 | citations.page 恒 null（md 文档） | 低 | 设计约束 | `routes.py:519` / `markdown_loader.py` | 记录，设计如此 |
| 3 | session_id 双写不一致 | 中 | 设计瑕疵 | `routes.py:112` / `routes.py:332` | 记录，待改进 |
| 4 | session_ready 无身份回执 | 低 | 可观测性缺口 | `routes.py:149-154` | 记录，待改进 |
| 5 | role 解析后零消费 | 低 | 代码冗余 | `routes.py:114` | 记录，待清理 |
| 6 | pyproject.toml `-n auto` 兼容问题 | 中 | 配置问题 | `pyproject.toml` | 记录，需单独授权修正 |
| 7 | agent-feishu-adapter 跑旧镜像 backup | 低 | 范围外 | monitoring compose | 记录，不在本次范围 |

---

## 五、验收结论

- Phase4b 核心目标**全部达成**：新镜像验证通过、业务栈健康且在位、WebSocket 端到端联调成功、全量回归无失败；
- 上述 7 项已知问题**均不影响主链路**，已逐条记入台账待后续处理；
- 验收结论：**通过**。

---

## 六、附件

### 6.1 关键命令

| 步骤 | 命令 |
|---|---|
| 第1步 | `docker images`；`docker inspect prod-app-1` |
| 第2步 | `cd C:\Users\hai\enterprise-agent\deploy\prod` → `docker compose -p prod -f docker-compose.prod.yml --env-file .env.production up -d --no-build` |
| 第3步 | `docker logs prod-app-1 --tail 80`；`curl http://localhost:8000/api/v1/health`；`curl http://localhost:8000/api/v1/metrics/prometheus` |
| 第4步 | `POST /api/v1/auth/login`（admin/admin123）取 JWT → 连 `ws://localhost:8000/ws/chat?token=<JWT>` 发送 `{"type":"chat_message","message":"ThermoView T100 的测温范围是多少？","session_id":"<guid>"}`；`GET /api/v1/admin/sessions` 核对 `user_id` |
| 第5步 | `cd C:\Users\hai\enterprise-agent` → `.\venv\Scripts\python.exe -m pytest -o addopts=-q` |

### 6.2 原始数据摘要

- **镜像**：`enterprise-agent-app-ollama:latest` = `e798a4a3f4ee`，4.5GB，2026-09-20 13:21；`prod-app-1` 实际镜像摘要 `sha256:e798a4a3f4ee...`。
- **容器**：业务栈 3 个（`prod-app-1` / `prod-postgres-1` / `prod-redis-1`，项目 `prod`）；监控栈 4 个（项目 `enterprise-agent`，本报告不涉及）。
- **端点**：`/api/v1/health` 200；`/api/v1/metrics/prometheus` 200（7759 字节）；`/api/v1/auth/login` 可用；`/ws/chat` 可握手并完成流式问答。
- **检索**：kb_id `KBS-050822`，命中 `product_spec_manual.md`（KB-406367）、`application_guide.md`（KB-B4DB00），最高分 1.0。
- **测试**：收集 1440 / passed 1417 / skipped 23 / failed 0 / errors 0；耗时 286.71s；退出码 0。

### 6.3 中间产物

- WS 联调脚本：`...\workspace\conv_dd80506987324a388548664e2391b887\temp\ws_chat_test.ps1`
- WS 输出落盘：`...\workspace\conv_dd80506987324a388548664e2391b887\temp\ws_chat_out.txt`
- app 日志导出：`...\temp\prod-app-1-logs80.txt`

---

*本报告为 Phase4b 验收一次性归档，仅记录事实与证据，不含未经验证的推断。*
*（内容由AI生成，仅供参考）*