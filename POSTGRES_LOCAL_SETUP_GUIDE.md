# 本地 Postgres 部署验证指南（手把手）

> 用途：在你自己的电脑上跑一个真实 PostgreSQL，验证「对话/知识库持久化」这条生产级链路
> （我的 sandbox 没有 Docker，所以这一步只能由你来做）。
> 前置：项目已在 `C:\Users\hai\enterprise-agent`，且 `venv` 已建好（`psycopg2-binary` 已安装）。

---

## 第 0 步：确认 Docker 已安装

1. 打开 **PowerShell**（不是 Git Bash 也行）。
2. 运行：
   ```powershell
   docker --version
   ```
   - 如果显示版本号（如 `Docker version 27.x`）→ 已装好，跳到第 1 步。
   - 如果提示“不是内部或外部命令” → 去 https://www.docker.com/products/docker-desktop 下载 **Docker Desktop for Windows** 安装，
     安装完**重启电脑**，再打开 Docker Desktop 等它右下角变绿（引擎已启动）。

---

## 第 1 步：启动一个 Postgres 容器

二选一，**推荐用 A（最简单）**。

### 方案 A：一条命令起一个单机 Postgres（推荐新手）

在 PowerShell 里运行（**整段一起复制**）：

```powershell
docker run --name agent-postgres `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=agent `
  -p 5432:5432 `
  -d postgres:16-alpine
```

验证容器在跑：
```powershell
docker ps
```
看到 `agent-postgres` 且 STATUS 是 `Up ...` 就成功了。

> 想停掉它：`docker stop agent-postgres`；想彻底删掉重来：`docker rm -f agent-postgres`。

### 方案 B：用项目自带的 docker-compose 只起 postgres

```powershell
cd C:\Users\hai\enterprise-agent
docker compose -f docker-compose.yml up -d postgres
```

（compose 里 postgres 服务名就叫 `postgres`，账号密码默认 `postgres/postgres`，库名 `agent`，和方案 A 一致。）

---

## 第 2 步：把数据库连接信息写进 `.env`

用任意文本编辑器（VS Code / 记事本）打开项目根目录的 `.env` 文件，
找到下面这几行（现在应该是空值），**改成**：

```ini
# ===== 数据库（Postgres 持久化）=====
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=agent
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/agent
# 存储后端：auto = 连得上 PG 就用 PG，连不上自动回退 SQLite 文件；postgres = 强制 PG（连不上就报错，方便暴露问题）
STORAGE_BACKEND=postgres
```

> 小提示：`.env` 是纯文本，直接改等号右边的值即可，别动别的行。
> `STORAGE_BACKEND` 设成 `postgres` 而不是 `auto`，是为了**强制走 PG**——如果 PG 没起来会直接报错，
> 而不是悄悄回退到 SQLite（那样你就以为验证成功了，其实没用到 PG）。

---

## 第 3 步：启动后端（连 PG 版本）

在项目根目录打开 **Git Bash**（或 PowerShell），运行：

```bash
cd /c/Users/hai/enterprise-agent
export VECTOR_STORE_BACKEND=chroma
venv/Scripts/python.exe -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000
```

---

## 第 4 步：确认“真的用上了 Postgres”

看启动日志（第 3 步那个终端窗口），找这几行：

- ✅ 成功信号：日志里应当**不再出现** `falling back to SQLite` / `SQLite` 相关提示；
  并且应当能看到类似 `Database backend: postgres` 或连接 PG 成功的字样。
- ❌ 失败信号：如果日志报 `could not connect to server` / `connection refused` /
  `FATAL: password authentication failed` → 说明 PG 没起或账号密码不对，回到第 1、2 步检查。

想更直接地确认表已建好，另开一个 PowerShell：

```powershell
docker exec -it agent-postgres psql -U postgres -d agent -c "\dt"
```

应当能看到一堆表，包括 `conversations`、`messages`（对话持久化）、`kb_sets`、`satisfaction_records` 等。

---

## 第 5 步：验证“重启不丢数据”（核心价值点）

1. 在浏览器打开 `http://127.0.0.1:8000/` → 聊几句（比如连发 3 条消息）。
2. **直接按 Ctrl+C 关掉第 3 步的后端终端**（模拟服务重启）。
3. 重新运行第 3 步的启动命令，后端起来。
4. 浏览器刷新页面 → 之前聊的内容应当还在（前端 `App.tsx` 会用 `localStorage` 里的
   `session_id` 自动续接，**注意：后端这块的 resume 我正在补，见下方“已知缺口”**）。
   也可以打开管理后台的「会话」tab 看历史列表（走 `/api/v1/admin/sessions`，直接读 PG）。

只要第 4 步确认了 PG 在用、第 5 步历史能查到，就说明持久化生产链路验证通过。

---

## 第 6 步（可选）：跑完整 docker-compose 全家桶

如果你想要“和线上一样”的完整栈（apisix 网关 + api/ws/worker + rag + pg + milvus + minio + redis + rabbitmq + nginx）：

```bash
cd C:\Users\hai\enterprise-agent
# 先构建前端产物（进 static/）
cd frontend && npm install && npm run build && cd ..
# 再起全栈（后台运行）
docker compose up -d
```

> 全家桶对机器内存要求高（建议 16G+），新手先别碰，用第 1~5 步验证就够了。

---

## 常见问题排查

| 现象 | 原因 | 解决 |
|---|---|---|
| `docker: command not found` | Docker 没装/没启动 | 第 0 步重装并启动 Docker Desktop |
| 启动后端报 `FATAL: password authentication failed` | `.env` 密码和容器不一致 | 容器用 `postgres/postgres`，`.env` 也写一样 |
| 启动后端报 `connection refused` / `could not connect` | PG 容器没起，或端口被占 | `docker ps` 看容器；或换端口 `-p 5433:5432` 并改 `.env` 的 `5432` |
| 日志仍显示 fallback to SQLite | `DATABASE_URL` 没填对 / `STORAGE_BACKEND` 还是 `auto` 且连不上 | 按第 2 步核对，设 `STORAGE_BACKEND=postgres` 让它报错暴露问题 |
| `ModuleNotFoundError: psycopg2` | 驱动没装 | `venv/Scripts/python.exe -m pip install psycopg2-binary` |

---

## 已知缺口（不用你管，我后端来修）

- 后端 WebSocket 目前**不处理**前端发来的 `resume_session` 消息类型，所以“刷新页面后续接旧会话”
  在服务重启后还不稳。这是后端 bug，我会自己补一个 `resume_session` 分支（复用已有 `session_id`，
  不再每次新建），修完推 GitHub，你拉代码即可。
- 项目里存在两套会话 API：你前端用的 `/api/v1/admin/sessions`（legacy）和我阶段三加的
  `/api/v1/conversations`。功能重叠，我后续会统一到一套，不影响你本机验证。
