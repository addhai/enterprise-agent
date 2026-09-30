# CLAUDE.md — AI 协作约定

> 这份文件放在项目根目录，AI 编码工具打开项目时会自动读取。
> 它的作用是告诉 AI：这个项目的上下文该怎么读，以及哪些事绝对不能做。

---

## 第一步：恢复上下文（每次新会话必做）

**只读这两份，不要全量扫描项目：**

1. `PROJECT.md` — 项目全景（定位、技术栈、容器拓扑、红线约束）
2. `CURRENT.md` — 当前状态（阻塞、阶段进度、任务索引）

如本次任务涉及前端构建、Docker 操作、Agent 通信，再加读：

3. `PITFALLS.md` — 踩坑清单

**需要详细任务清单时**，读 `docs/Phase5-后续待完善任务清单.md`（含行号级证据）。

**读完这些才能开始动手。** 这是本项目的硬性要求。

---

## 项目规模认知（重要）

- Python 源文件 178 个，前端 TS/TSX 文件 25 个
- **不要尝试全量读取代码。** 这个体量会瞬间耗尽上下文
- 正确做法：先读上述文件建立认知，再按需定点打开具体文件
- 需要找文件时用搜索（Grep/Glob），不要遍历

---

## 当前项目处于什么阶段（会变化，以 CURRENT.md 为准）

截至 2026-09-30:

- Phase3 → Phase5 性能基准**全部完成**,回归基线 1417 passed / 0 failed
- **唯一未收官主线**：Phase5「kb_call_mode 语义收口」完成 1/6 步，判据模块已写但未接入 `nodes.py`
- **头号风险**：286 条改动未入库，HEAD 停在 2026-09-22，可能一次误操作全丢
- **当前卡死**：Docker daemon 未运行，容器级动作全部停摆

---

## 绝对禁止

### 禁止全量读取这些文件

| 文件 | 原因 |
|---|---|
| `docs-update-1.md` ~ `docs-update-5.md` | 合计约 390KB，历史快照，读了必然爆上下文 |
| `.env` / `.env.intranet` / `deploy/prod/.env.production` | 含真实密钥，不要读取、不要输出内容 |
| `.coverage` | 114KB 二进制覆盖率数据 |
| `*.bak` 系列 | 历史备份，非当前版本 |

### 禁止的操作

1. **不要不带 `-f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production` 执行 compose**
   不带会操作到项目根目录的旧编排/容器，这是本项目的高危坑

2. **不要重建 postgres / redis 容器**
   只重建 app。数据卷 `prod-agent-chroma` / `prod-postgres-data` / `prod-redis-data` 绝不可丢

3. **不要再往项目根目录加 `docs-update-N.md`**
   这种编号递增的命名是文档失控信号。新文档进 `docs/` 对应子目录

4. **不要在未读 `PROJECT.md` 的情况下修改代码**
   本项目有 7 条红线约束和 4 条执行纪律，违反会出事故

5. **不要删除 `.bak` 文件**（需先与用户确认哪些可清理）

6. **不要读取或打印任何 `.env` 里的值**

7. **不要修改 `.context_backup/` 目录下的备份**

---

## 上下文更新规则（会话结束时）

**每完成一个阶段，更新对应的层。**

| 变化类型 | 更新哪个文件 | 方式 |
|---|---|---|
| 项目定位/技术栈/容器拓扑/红线变了 | `PROJECT.md` | 覆盖对应章节 |
| 完成阶段、阻塞解除、新增风险 | `CURRENT.md` | 覆盖对应区块 |
| 本次改了什么、为什么这么改、否掉了什么方案 | `docs/journal/YYYY-MM-DD-主题.md` | 新建文件，只追加 |
| 踩了新坑 | `PITFALLS.md` | 追加条目 |

**关键：`CURRENT.md` 是覆盖式的，`docs/journal/` 是只追加的。**
不要往 `CURRENT.md` 里堆历史，那会导致它膨胀失效。

---

## 环境要点

- 项目根目录：`C:\Users\hai\enterprise-agent`
- 运行环境：Windows 10 + Docker Desktop（WSL2），**纯 CPU 推理**
- Windows 中文系统：涉及 `psycopg2` 时需 `PYTHONUTF8=1` / `PGCLIENTENCODING=UTF8`
- 容器名：`prod-app-1` / `prod-postgres-1` / `prod-redis-1`
- 前端源码 `frontend/`,构建输出到 `static/`（由 `vite.config.ts` 的 `build.outDir: '../static'` 指定）
  - **注意：不是 `frontend/dist`**,这是本项目容易搞错的地方
- 改前端后必须 `npm run build`,否则容器看到的是旧产物
- 验证前端前先 `Ctrl+Shift+R` 清缓存

---

## 与 git 的分工

- **git commit** 记录「改了哪些文件」
- **`docs/journal/`** 记录「为什么这么改、否定过什么方案」

两者互补。不要用 commit message 承担决策记录的职责，也不要指望 git log 能还原思路。

---

## 文档地图

- 项目全景 → `PROJECT.md`
- 当前状态 → `CURRENT.md`
- 踩坑清单 → `PITFALLS.md`
- 详细任务清单 → `docs/Phase5-后续待完善任务清单.md`
- 会话日志 → `docs/journal/`
- 全项目文档导航 → `docs/INDEX.md`
- 历史快照（勿全量读） → `docs-update-*.md`
