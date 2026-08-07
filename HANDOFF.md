# HANDOFF.md — enterprise-agent（模仿阿里云 AI 助理的智能客服）交接文档

> **写给完全没上下文的接手者**：假设你是第一次接触这个项目，没参加过之前任何对话、没看过任何一个文件。从「第 0 节」往下读，读完就能接手继续干。
>
> 最后更新：**2026-08-07 晚间版**。本次把「引用气泡 + 隔离核查 + P0 全量推送」「作品集文档并入」「P1 多租户运行化完成并推送」三件事并入；前半部分「当前活跃任务快照」先读。
> 代码位置：`C:\Users\hai\enterprise-agent`
> 仓库：`https://github.com/addhai/enterprise-agent`（GitHub，master 分支）

---

## ⚡ 当前活跃任务快照（2026-08-07 凌晨结束 · 给刚接手的你 / 先读这段）

> 📌 **项目背景必读**：本文件第 0 节「一句话背景」讲清了这是什么、谁在做、为什么做（个人简历作品集，对标阿里云 AI 助理智能客服）。**先读第 0 节再往下。**
> 上一轮（2026-08-06 前端 Design System v2 重设计）快照已并入文末第 9 节「历史折叠」，本段是**最近一次会话（2026-08-07 凌晨）的真实状态**。

### 本次会话在干什么
收尾「对标阿里云智能客服」的三件事：① 坐席聊天**引用气泡（citations）**；② 知识库**命中测试做精**；③ **多租户 + RBAC 隔离核查**（含 P0 修复）。

### 已经完成了什么（已验证，已推送 GitHub）
- **引用气泡全链路打通**（前端 + 协议层 + 节点补检 + 路由层）：
  - `src/websocket/protocol.py`（约 101-103 行）：`if citations:` 改 `if citations is not None:`（空列表 `[]` 也能挂字段，之前被真值判断吃成 `None`）。
  - `src/graph/nodes.py`（rag_node，`_extract_retrieved_docs` 之后）：补检 fallback——`retrieved_docs` 为空时，用原始 `content` 调 `retriever.search(content, top_k=3, user_id=…, tenant_id=…, user_access_levels=…)` 拿结构化 Document 填入。
  - `src/websocket/routes.py` `_build_citations`：score 读取从 `getattr(d,"score",0)` 扩到 metadata（`rrf_score`/`score`）兜底。
  - `frontend/src/App.tsx`：`ChatCitation` 接口 + `details/summary` 渲染「引用知识片段 N」可展开气泡；`loadSession` 从 `metadata.citations` 恢复。
  - `frontend/src/App.css`：`.chat-citations` / `.chat-citation` 玻璃风深色样式。
  - `frontend/src/components/AdminDashboard.tsx`：命中测试加「采用 / 低于阈值」徽章 + 文档标题 + 内容折叠。
- **端到端实测通过**：`.workbuddy/tmp_ws_test.py`（登录拿 JWT → WS 发问 → 验 `citations`）。ECS 问题命中 1 条《ECS 远程连接排障 SOP》✓；价格问题 0 条（正确不引用）。
- **多租户 + RBAC 隔离核查报告**：`docs/多租户-RBAC隔离核查.md`。结论：SQL 级 + 向量级隔离**代码已实现并通过走查**；生产级多租户运行化（P1）**已完成并端到端验证**（新增 `Tenant` 表、租户 CRUD、`tickets.py` 动态取 tenant、注册归属租户、超级管理员租户端点，两真实租户互不可见已测）。
- **P0 修复（已实施）**：`src/rag/retriever.py`（租户隔离规则 1）改为「空 tenant 文档默认归 default，跨租户不可见」→ 堵住"漏打 tenant 的文档对所有租户可见"后门。同时修了一处回归：`src/graph/nodes.py` 两处 `state.get("tenant_id", "")` 改 `... or "default"`（WS 匿名聊天 tenant 原本是空串，被 P0 挡在 default 库外，气泡被打挂，兜底修好）。

### 当前卡在哪
- **功能不卡**。引用气泡 / 命中测试 / 隔离核查 / P0 修复 / P1 多租户运行化均已完成并验证。
- 剩余未决（非阻塞）：P2 多租户（RBAC 加租户维度校验、WS 匿名 `tenant_id` 独立化）尚未做；其余均为低优打磨项。

### 下一步计划（按优先级）
1. **多租户 P2**：RBAC 加租户维度校验；WS 匿名 `tenant_id` 独立化。
2. **收尾小 bug**：`routes.py` 的 `asyncio` 局部变量名 WARNING（WS 握手时打，非阻塞）；加速 milvus→chroma 冷启动 fallback。
3. **作品集文档**：更新 `resume-project.md` / README（引用气泡 + 命中测试 + 隔离核查 + P0 + P1 多租户 + JWT 已并入，测试数 313→315）已并入并推送。
4. **真实云 API 接入那批后端文件**：`aliyun_client.py` / `cloud_provider.py` / `resource.py` 等已于 2026-08-07 全量推送（commit `4620860`），无需再决策。

### 踩过的坑（绝对不要再踩 · 本次会话新增，前端历史坑见第 5 节坑 32-36）
- **坑 37（气泡根因）**：`search_knowledge_base` 工具返回**格式化字符串**，而 `nodes.py:_extract_retrieved_docs` 只认 `observation` 为 list → `retrieved_docs` 永远空 → 气泡断链。修复是在 rag_node 补检 `retriever.search`。
- **坑 38**：RRF 融合分(0.01~0.06 量级) 被 chroma 尺度阈值 0.2 卡掉；且 protocol.py `if citations:` 真值判断把空列表吃成 None。**两处都改了**，缺一不可。
- **坑 39（改隔离必看）**：WS 匿名聊天 `tenant_id` 一路是空字符串 → P0 把隔离变严后，default 库文档对它不可见 → 气泡被打挂。兜底 `or "default"` 修好。**教训：改隔离逻辑前，先确认匿名/默认租户这条路径，否则会误伤 demo。**
- **坑 40（内存）**：两个 python 进程同时加载 chroma（uvicorn + 直测脚本）会 OpenBLAS OOM。验证 retriever 时**先 taskkill 旧 uvicorn，单进程跑**。
- **坑 41**：retriever 没有 `get_retriever()` 工厂函数，要 `from src.rag.retriever import HybridRetriever; r = HybridRetriever(backend="chroma")` 直接实例化。
- **坑 42**：git bash 没有 `seq`；等后端起来用 `i=1; while [ $i -le 40 ]; do ...; i=$((i+1)); done` POSIX 循环。
- **坑 43**：chroma cold start 慢（首次 ~60s，含 milvus→chroma fallback）；health 轮询要等够久，别在 10s 内判死。

---

## 0. 一句话背景（必须先读，否则后面全误解）

**这是什么**：一个用 Python（FastAPI + LangGraph + RAG + MCP）写的**智能客服系统**，前端是 React/TypeScript。

**谁在做、为什么做（最重要的一条）**：
- 这是**用户（hai）的个人项目**，**不是团队项目**。
- 目的是**作为简历作品集（portfolio）展示全栈 AI 工程能力**。
- **对标对象：模仿「阿里云 AI 助理」的智能客服形态**（官网那个 AI 智能客服 / 智能助手）。

**因此开发方向是**：做出一个**完整、能跑、看得见、生产级**的作品。用户明确说过："就算放简历也不该只是做个 demo"，要按**完整产品 / 生产级标准**开发。

> ⚠️ **致命误导警告**：仓库根目录有一份 `团队技术提升方案.md`，写满"团队 code review 会""资深开发带练""8 周路线图""覆盖率提到 80%"。**这份文档按"团队协作"假设写，对当前个人作品集项目不适用**——不要当 KPI 推。质量目标是「作品集 / 生产级标准」：CI 能绿、能本地一键跑起来、前端页面完整可演示、关键链路有持久化与监控，而非硬刷 80% 覆盖率。

---

## 1. 我们在做什么任务

这是一个**持续演进的智能客服作品集**。开发重心已多次转移：

**第一阶段（质量基础设施，已完成并推送）**：CI/CD 质量门禁——让"能跑"变成"敢改、改了不崩"。

**第二阶段（让作品生产级可用，后端 6 阶段，已完成并推送）**：持久化 + 真实可演示链路（对话持久化、知识库隔离、真实监控、会话增删查、管理端历史可见）。

**第三阶段（本次 2026-08-06，前端视觉重设计，已完成并推送）**：把前端整套换肤成深色玻璃拟态设计系统 v2，并定稿 Hero 背景为扁平几何色块。

> 注意：本项目的本质是**后端工程为主**。前端（App.tsx 浮动聊天 + AdminDashboard 多 Tab）用户自己早已写得相当完整，**很多"缺口"其实已经存在**，别据旧文档（如 `改动方案.md`）找不存在的缺口。

---

## 2. 已经完成了什么（真实落到仓库 / 已推送 GitHub）

### A. 质量基础设施（Phase 1，已推送）
- 质量门禁：`pyproject.toml`（ruff + pytest/覆盖率 + `integration` marker）、`.github/workflows/ci.yml`、`bandit.yaml`、`docs/PR_REVIEW_CHECKLIST.md`、`docs/CODE_STYLE.md`
- 确定性测试范式：`src/agent/fake_llm.py`、`src/agent/agent.py`（`llm_client` 注入）、`tests/test_agent/test_agent_deterministic.py`
- 异常与可观测性：`src/core/exceptions.py`、`src/core/logging.py`
- 并发修复：`src/agent/tools.py`（`retry_async` + 修 `parallel_tool_call` 漏 `await`）
- CI 实际跑 **GitHub Actions**（`.github/workflows/ci.yml`）。

### B. 第二阶段六个开发阶段（2026-08-03，全部本地提交并推送）
| 阶段 | 做了什么 |
|------|----------|
| 阶段一·持久化地基 | Postgres/SQLite 双后端；PG 不可达自动 fallback SQLite；仓储层 + `Conversation/Message` 表 |
| 阶段二·知识库隔离+多源 | kb_id 过滤隔离；多知识源（URL / 纯文本）摄取；**修根因 bug**：`retriever.py` 缺 `add_documents()` |
| 阶段三·对话持久化+历史API | WebSocket 聊天落库；跨重启恢复历史；`GET /api/v1/conversations` + `/{session_id}/messages`；监控接真实指标 |
| 阶段四·风险监控真计数 | `tracker.py` 加 `record_safety_event(kind)`；注入拦截 / 转人工真实计数 |
| 阶段五·会话删除 | `conversation_delete` 级联删；`DELETE /api/v1/conversations/{session_id}` |
| 阶段六·管理端会话合并DB | 历史会话面板显示持久化数据：四个端点改"内存优先 + DB 回退合并" |

**补完轮（2026-08-03，已本地提交）**：统一会话 API（`src/api/sessions_service.py` 共享 service 层）、接上 `resume_session` 握手、接入 hallucination 真实计数、测试底座污染根治（conftest 改 `sqlite:///:memory:` + `StaticPool`）。

### C. 前端核查（2026-08-02，部分已提交）
- **纠正过时判断**：`改动方案.md`（2026-07-20）说"前端还有 3 个 ⏳ 未完成页面"。实际前端早已远超该描述——`App.tsx`（首页 + 登录 + 个人中心 + 浮动聊天）、`components/AdminDashboard.tsx`（9 Tab 管理后台含 SessionsTab）。**别再据那份文档找缺口**。
- 前端浮动聊天组件**使用 WebSocket** `/ws/chat`（`App.tsx` `WS_URL='/ws/chat'`）；续接（`resume_session` / localStorage `session_id`）用户早已写好。后端 `/ws/chat` 在 `src/websocket/routes.py`。

### D. 第三阶段·前端 Design System v2（2026-08-06，已提交 `f2f6ab0` 并推送）
- `src/index.css`：深色优先 CSS 变量 token 层（`--bg-deep` / `--brand-teal` / `--brand-purple` / `--brand-blue` / `--gradient-brand` / `--glass-bg` / `--glass-blur` 等）。
- `src/App.css`：全套新皮肤（`.nav` 玻璃悬浮导航、`.hero` 左右分栏、`.capability-card`、`.metric-value` 渐变数字、`.chat-widget`、`.modal`、`.dashboard` 等）。
- `src/App.tsx`：Hero 左右分栏（左文案 + 右聊天预览浮动）；`ThemeContext` 默认 `dark`；聊天/RBAC/登录逻辑 100% 保留。
- `src/components/GeometricBackground.tsx`：纯静态 SVG 暖橙几何色块，作 Hero 背景，零依赖零动画零 glow。

### D2. 本次会话新增（2026-08-07 · 引用气泡 + 隔离核查 + P0，已推送 GitHub）
- **引用气泡（citations）全链路打通**：
  - 后端：`src/websocket/protocol.py`（空列表也能挂 `citations` 字段）、`src/graph/nodes.py`（rag_node 补检 `retriever.search` 填结构化 `retrieved_docs`）、`src/websocket/routes.py`（`_build_citations` 规整 + score 兜底）。
  - 前端：`frontend/src/App.tsx`（`ChatCitation` 接口 + `details/summary` 气泡渲染 + `loadSession` 恢复）、`frontend/src/App.css`（玻璃风样式）、`frontend/src/components/AdminDashboard.tsx`（命中测试「采用/低于阈值」徽章 + 标题 + 折叠）。
  - 实测：`.workbuddy/tmp_ws_test.py` 登录→WS 发问，ECS 问题命中 1 条、价格问题 0 条。
- **多租户 + RBAC 隔离核查**：`docs/多租户-RBAC隔离核查.md`（SQL 级 + 向量级隔离代码已实现并通过走查；**P1 运行化已后续完成并推送，两真实租户互不可见已端到端验证**）。
- **P0 修复**：`src/rag/retriever.py` 空 tenant 文档默认归 default 堵后门；`src/graph/nodes.py` 两处 `tenant_id` 兜底 `or "default"` 修回归。

### 当前 CI 状态
- **315 passed / 1 skipped / 0 failed**（GitHub Actions 白名单：`tests/test_agent/ tests/test_mcp_tools/ tests/test_safety/ tests/test_ticket/ tests/test_evaluation/`，含新增两租户隔离测试）。
- 真实覆盖率约 **17%**（作品集无需硬刷 80%）。

---

## 3. 当前状态 / 卡在哪

### ✅ 已完成，不再卡
- 前端 Design System v2 已提交并推送（`f2f6ab0`，本地与 origin 同步：`0	0`）。
- 后端 6 阶段 + 补完轮已全部推送；核心链路已生产级（持久化、知识库隔离、真实监控、会话 CRUD、管理端历史可见）。

### ⏳ 当前真正待办（按"谁来做"分两类）

**需要用户（hai）自己动手的**：
1. **后端那批未提交改动要不要提交**：工作区有一批修改/新增的后端文件（见下方清单），疑似「真实云 API 接入」，本次会话刻意没动。**接手者不要擅自 add/commit**，等用户明确意图。
2. **本机 Postgres Docker 端到端验证**（更早会话遗留）：是否已完成未知，手把手步骤在 `POSTGRES_LOCAL_SETUP_GUIDE.md`。

**可继续自主推进（无阻塞性）**：
- 当前无强制性后端任务。可选低优：更多确定性测试、更多可观测指标、登录鉴权 UI（用户说过"先放一放"，归用户）。

**本次会话（2026-08-07）已自主完成、可继续的方向**：
- 引用气泡、命中测试精做、多租户/RBAC 隔离核查、P0 修复，均已完成并验证，且已推送 GitHub（见第 2 节 D2 与提交记录）。
- 多租户运行化 P1 已完成并推送（两真实租户互不可见端到端验证）；P2（RBAC 租户维度校验）仍待做。

### 🗂️ 本地未提交 / 勿提交清单（2026-08-07 晚间状态）

核心后端代码（引用气泡 + P0 修复 + 真实云 API 接入 + P1 多租户运行化）已全部推送 GitHub，工作区与 origin 同步。**以下仅剩个人/垃圾文件提醒，核心代码无需再处理。**

- **个人/垃圾文件（绝对不提交）**：`install.log`、`test_out.log`、`test_out.txt`、`docs/agent-project-roadmap.html`、`docs/需求文档-模仿阿里云AI助理智能体.md`、`改动方案.md`（这些是本会话/更早产生的个人或规划文档）
- **本交接文档自身**：`HANDOFF.md` 本次已更新（同步 P1 状态），修改态未提交；如需入仓，单独 `git add HANDOFF.md` 提交。
- **绝对禁止 `git add .`**：个人/规划文档不该进仓库。

---

## 4. 下一步计划（按优先级）

1. **多租户运行化 P1（已完成并推送，commit `d9e34ab`）**：Ticket API 动态取 tenant（`_get_tenant_id(current_user)` 替代 `tickets.py` 硬编码 `tenant_id="default"`）、加租户管理端点、注册/登录支持归属租户。两真实租户互不可见已端到端验证。
2. **多租户 P2**：RBAC 加租户维度校验；WS 匿名 `tenant_id` 独立化。
3. **收尾小 bug（低风险可自主）**：`routes.py` 的 `asyncio` 局部变量名 WARNING（WS 握手时打，非阻塞）；加速 milvus→chroma 冷启动 fallback。
4. **作品集文档（已完成并推送）**：`docs/resume-project.md` / README 已并入引用气泡 + 命中测试 + 隔离核查 + P0 + P1 多租户 + JWT，测试数 313→315。
5. **真实云 API 接入那批后端文件（已推送，commit `4620860`）**：`aliyun_client.py` / `cloud_provider.py` / `resource.py` 等无需再决策。
6. **【归用户】本机 Postgres 验证**：若还没跑，按 `POSTGRES_LOCAL_SETUP_GUIDE.md` 验证。
7. **【可选低优先】少量高价值测试**：补确定性单测涨覆盖率，不专门刷 80%。
8. **【归用户】登录鉴权 UI**：用户说过"先放一放"。

---

## 5. 踩过的坑（绝对不要再踩）

### 工程 / CI / Git 类（沿用第一阶段）
1. **bandit `# nosec` 必须和被标记代码「同行」**。放上一行注释里无效。
2. **B608（SQL 注入）误报**：用 `"".join([...])` 替代 `"..." + var`；或把 SQL 赋给 Name 变量传参。
3. **B324（md5/sha1）非密码学用途**：用 `hashlib.md5(..., usedforsecurity=False)`。
4. **⚠️ pytest 子目录 conftest 崩溃（最坑）**：CI 命令用**白名单**——`pytest tests/test_agent/ tests/test_mcp_tools/ tests/test_safety/ tests/test_ticket/ tests/test_evaluation/`。**绝不再写 `pytest tests/` + 排除**。
5. **ignore 目录名必须和实际一致**：实际是 `tests/test_graph`（带 `test_` 前缀）。
6. **Git 命令空格被中文输入法吃掉**：`git add.github/` 会失败。打命令前切英文输入法。
7. **网页复制命令带终端转义码**：如 `[200` 前缀。重要命令手打。
8. **绝不要 `git add .` / `git add -A`**：本地大量改动文件大多无关。只 add 指定路径。
9. **⚠️ GitHub 推送网络极不稳定 / 代理坑**：频繁 `Connection reset`；且本机 git 配了 `http.proxy=127.0.0.1:7890`，代理没开时 push 必失败但直连通。解法见坑 36。涉及 push 优先让用户本机做；沙箱无代理出口时更必须用户本机。
10. **覆盖率 17% 是真实数字，别误读**：作品集无需刷 80%。
11. **仓库在 GitHub，不是 GitLab**：`.gitlab-ci.yml` 在 GitHub 不生效；CI 靠 `.github/workflows/ci.yml`。
12. **API Key 缺失会让旧测试全军覆没**：要 Key 的测试必须 `@pytest.mark.integration` + CI 用 `-m "not integration"`，或用 FakeLLM 注入。
13. **⚠️ `改动方案.md` 的"3 个未完成页面 ⏳"已过时**：前端实际已有落地页+浮动聊天+9 Tab 后台。**别再据此判断前端缺口**。
14. **前端 `npm run build` 在 WorkBuddy 沙箱会被 safe-delete 垫片卡住**（清 `dist/` 时报错），本地正常。沙箱验证用 `vite build --outDir=dist-test`（配合坑 35 的环境变量）。
15. **`dist/` / `static/` 不应进 git**：已用 `git rm --cached` 取消跟踪并 `.gitignore` 忽略。**不要重新 add。**
16. **`团队技术提升方案.md` 不适用本项目**：个人简历作品集，**不要把团队指标当 KPI**。
17. **`/api/v1/health` 会挂起**：它探测 localhost:9000-9003 这些没起的 agent，超 5s 返回 000。验证存活用 `GET /` 或 `/auth/register`，别被 health 误导。
18. **提交路径手滑写反斜杠会失败**：`git add C:\Users\...` 报错，改 `git add C:/Users/...`。

### 第二阶段新增坑（2026-08-03）
19. **`Document` 构造 `metadata` 必须是关键字参数**：`Document(text, metadata={...})`。
20. **`HybridRetriever._apply_filter` 是实例方法（非 static）**：需经实例调用。
21. **BM25 对混合中英文关键词召回不稳定**：隔离测试改对 `_apply_filter` 纯函数做确定性断言，别赌 BM25 召回率。
22. **⚠️ `DetachedInstanceError`**：在 `with db_session() as db:` 块**外**访问 ORM 对象属性会崩。标量提取必须在 `db_session()` 作用域内完成。
23. **共享 service 层设计**：`sessions_service.py` 所有函数同步、纯逻辑、不依赖 FastAPI；越权抛 `PermissionError`（路由层译 403），找不到返回 `None`（译 404）。
24. **测试放错目录不被 CI 收集**：`tests/test_api/` 和 `tests/test_rag/` 在 conftest `collect_ignore` 中。新 API 测试必须放进白名单内目录。
25. **`TestClient(app)` 不跑 lifespan 也能调路由**（DB 已由 conftest fixture 初始化）。
26. **`/auth/register` 默认建 `role=agent`**，满足 KB 端点 `require_roles(ADMIN, AGENT)`，**demo 无需 admin 账号**。端点实际是 `/api/v1/auth/register`。
27. **前端 WS 续接/历史面板是用户已完成的 WIP**：别再列为"待补 UI 缺口"。
28. **测试跨运行脏数据污染（最隐蔽的"假绿"）**：原 conftest 用固定文件 `test_agent.db`，Windows 上 SQLite 文件被连接池锁住时 `os.remove` 静默失败 → 旧库残留 → 单文件过/整套挂。根治：conftest 改 `sqlite:///:memory:` + `StaticPool`。**CI 与本地验收必须跑完整白名单**，不能只跑单文件子集冒充全绿。
29. **⚠️ Windows 中文系统 + Postgres 编码崩溃（代码层兜底 + 容器配置根治）**：报错 `UnicodeDecodeError: 'utf-8' can't decode byte 0xd6` 本质两层：① PG 在中文环境用 **GBK** 返回错误，psycopg2 按 UTF-8 解码崩；② 诱发：`.env` 中 `DATABASE_URL` 行尾有中文注释被当 URL 一部分、`seed.py` 有中文演示数据、控制台代码页非 UTF-8。
   **代码层兜底**（已提交）：`server.py` 顶部强制 `PGCLIENTENCODING=UTF8`+`PYTHONUTF8=1`+`load_dotenv(encoding="utf-8")`；`engine.py` 强制 `connect_args={'client_encoding':'utf8'}`+`_clean_url()` 去行内 `#`+`options=-c lc_messages=C`+`_decode_pg_error()`；`session.py` 在 `db_session()` 内先 `session.connection()` 触发连接转人话；seed 字符串改 ASCII。
   **最终根治**：PostgreSQL 容器配 `lc_messages=C`（见 `POSTGRES_LOCAL_SETUP_GUIDE.md`）。
30. **⚠️ 本机 PostgreSQL 服务抢占 5432**：用户 Windows 本机装了 PostgreSQL 服务（如 `postgresql-x64-18`）一直占 5432，Docker 容器映射也在 5432，但主机连 `localhost:5432` 先连本机服务（密码还不一样）→ 认证失败 + GBK 报错。排查第一件事永远 `netstat -ano | findstr ":5432"` 看哪个进程占端口。需要管理员停服务的操作必须用户本人做，别在沙箱绕。

### 第三阶段新增坑（2026-08-06 · 前端）
31. **Vite 代理端口**：前端 dev server 默认 `localhost:3000`（被占时顺延 3001）。后端在 `:8000`，`/api` 与 `/ws/chat` 由 Vite proxy 转 `ws://localhost:8000`。
32. **⚠️ AdminDashboard 类名是无前缀的（最致命）**：组件用 `stat-card` / `metrics-grid` / `badge` / `sessions-table` / `filter-bar` / `recent-list` / `notification-*` / `channel-*` / `profile-*` / `timeline-*` / `comment-*` / `detail-panel` / `back-btn` / `role-badge` / `customer-*` / `session-row` / `sessions-container` / `handoff-*` 等。**再重写 App.css 必须保留这些原类名并给样式**，否则整个后台掉光皮肤。本次就是只写 `.dash-*` 前缀导致后台变裸，修复是从 git 原版 `App.css` 提取全部 dashboard 样式做深色适配补回。
33. **用户明确拒绝 glow / 光感**：极光、径向光晕、网格纹理全不要。选定审美 = 扁平几何色块（暖橙活力）。不要再引回发光效果。
34. **React Bits 的 Aurora 基于 OGL/WebGL**：要引依赖 + shader 兼容性/移动端发热风险。用户要「工程稳健 + 包体克制」，改用零依赖静态 SVG。**不要再往项目塞 `ogl`**。
35. **Vite build 在沙箱被 safe-delete 垫片卡住**：验证用 `CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= npx vite build --outDir=dist-test`；本机正常 `npm run build`（输出 `static/`）没问题。
36. **git 代理 push 失败**：全局 `http.proxy=127.0.0.1:7890` 常没开 → push 报连不上 7890，但直连 GitHub 通。push 用：
    ```bash
    GIT_HTTP_PROXY= GIT_HTTPS_PROXY= git -c http.proxy= -c https.proxy= push origin master
    ```

### 本次会话新增坑（2026-08-07 凌晨 · 引用气泡 + 隔离）
37. **气泡根因**：`src/agent/tools.py:search_knowledge_base` 返回**格式化字符串**，但 `src/graph/nodes.py:_extract_retrieved_docs` 只认 `observation` 为 list → `retrieved_docs` 永远空 → 气泡断链。修复是在 rag_node 补检 `retriever.search()` 拿结构化 Document。
38. **RRF 分尺度 + 协议真值判断双重坑**：① chroma RRF 融合分仅 0.01~0.06 量级，被 chroma 尺度阈值 0.2 卡掉；② `protocol.py` 原 `if citations:` 把空列表 `[]` 真值判断吃成 `None`。两处都改（补检 + `is not None`）气泡才出得来。
39. **⚠️ 改隔离逻辑必看**：WS 匿名聊天 `tenant_id` 一路是空字符串。P0 把隔离变严后，`retriever` 的"空 tenant 文档默认归 default"规则让匿名查询看不到 default 库 → 引用气泡被打挂。兜底 `state.get("tenant_id") or "default"` 修好。**教训：收紧隔离前，先确认匿名/默认租户这条 demo 路径，否则会误伤。**
40. **内存 OOM**：两个 python 进程同时加载 chroma（uvicorn + 直测 retriever 脚本）会 OpenBLAS 内存分配失败。验证 retriever 时**先 `taskkill` 旧 uvicorn，单进程跑**。
41. **retriever 无工厂函数**：没有 `get_retriever()`，要 `from src.rag.retriever import HybridRetriever; r = HybridRetriever(backend="chroma")` 直接实例化。
42. **git bash 无 `seq`**：等后端起来用 `i=1; while [ $i -le 40 ]; do code=$(curl ...); ...; i=$((i+1)); done` POSIX 循环，别写 `seq 1 40`。
43. **chroma cold start 慢**：首次加载 ~60s（含 milvus→chroma fallback 探测）。health 轮询要等够，别在 10s 内判死；WS 第一次发问也会偏慢。

---

## 6. 关键文件清单（接手者必读）

| 文件 | 作用 | 状态 |
|------|------|------|
| `.github/workflows/ci.yml` | GitHub Actions 流水线（测试+覆盖率 + SAST） | ✅ 291 passed / 1 skipped，已推送 |
| `src/api/server.py` | FastAPI 装配（所有 router 含 WS 在此挂载） | ✅ 已推送 |
| `src/websocket/routes.py` | `/ws/chat` + `/ws/agent/{agent_id}`；聊天落库 + DB 历史恢复 | ✅ 已推送 |
| `src/db/repositories.py` | 仓储层：conversation/message CRUD | ✅ 已推送 |
| `src/api/sessions_service.py` | 会话 API 共享 service 层（补完轮新增） | ✅ 已推送 |
| `src/evaluation/tracker.py` | 评估指标 + `record_safety_event` 安全计数 | ✅ 已推送 |
| `src/mcp_tools/aliyun_client.py` `cloud_provider.py` `resource.py` | **真实云 API 接入（疑似）** | ⏳ 未提交，勿碰，等用户决策 |
| `frontend/src/index.css` | 设计系统 v2 的 CSS 变量 token 层 | ✅ 已推送（`f2f6ab0`） |
| `frontend/src/App.css` | 全套新皮肤（含找回的 dashboard 样式） | ✅ 已推送 |
| `frontend/src/App.tsx` | 官网首页 + 登录 + 个人中心 + 浮动聊天(WS)，Hero 左右分栏 | ✅ 已推送 |
| `frontend/src/components/GeometricBackground.tsx` | Hero 背景纯静态 SVG 暖橙几何色块 | ✅ 已推送（新文件） |
| `frontend/src/components/AdminDashboard.tsx` | 多 Tab 管理后台（无前缀类名，见坑 32） | ✅ 用户早已写好，本次只补样式 |
| `docs/多租户-RBAC隔离核查.md` | 多租户 + RBAC 隔离走查报告（含 P0 实施） | ✅ 本次新增，已推送 |
| `src/websocket/protocol.py` | WS 消息协议（citations 字段透传） | ✏️ 本次改（空列表挂字段） |
| `src/graph/nodes.py` | LangGraph 节点（rag_node 补检 + tenant 兜底） | ✏️ 本次改 |
| `src/rag/retriever.py` | 混合检索（租户隔离规则 1 堵后门） | ✏️ 本次改 |
| `src/websocket/routes.py` | `/ws/chat` 路由（`_build_citations` 规整） | ✏️ 本次改（score 兜底） |
| `.workbuddy/tmp_ws_test.py` | WS 引用气泡端到端实测脚本 | ✅ 本次新增（测试用，勿提交） |
| `POSTGRES_LOCAL_SETUP_GUIDE.md` | 本机 Postgres Docker 验证手把手指南 | ✅ 已推送 |
| `团队技术提升方案.md` `改动方案.md` `overview.md` | 规划文档（部分已过时） | 仅供参考，**勿当真** |

---

## 7. 账号 / 环境 / Git 操作备忘

- **代码仓库**：`https://github.com/addhai/enterprise-agent`（GitHub，master 分支）
- **看 CI 结果**：`https://github.com/addhai/enterprise-agent/actions`
- **Python**：CI 用 3.11；用户本机有 managed 3.13.12。`requirements.txt` 含 `psycopg2-binary`。
- **前端**：`frontend/` 是 React + Vite + TypeScript。`node_modules` 已存在，可 `npm run build` / `npm run dev`。
- **代理**：用户用代理工具访问 GitHub，push 不稳是常态（见坑 36）。**沙箱 Bash 无代理出口，push 必须由用户本机做。**

### 在沙箱里跑测试（CI 同款白名单）
```bash
cd /c/Users/hai/enterprise-agent
venv/Scripts/python.exe -m pytest tests/test_agent/ tests/test_mcp_tools/ tests/test_safety/ tests/test_ticket/ tests/test_evaluation/ -o addopts="" -q
```
> `-o addopts=""` 规避本地未装 pytest-cov 时报错。

### 在沙箱里验证前端构建
```bash
cd /c/Users/hai/enterprise-agent/frontend
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= npx tsc --noEmit
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= npx vite build --outDir=dist-test
```

---

## 8. 运行 demo（持续验证通过）

后端 `src/api/server.py` 在根路径用 `StaticFiles(directory="static", html=True)` 同时托管**前端静态页 + 后端 API + `/ws/chat`**，三者同源，一个进程即可。

### 路径 A：单进程极简 demo（最快）
```bash
# 1) 构建前端到 static/
cd frontend && npm install && npm run build && cd ..

# 2) 启动后端（chroma 替代 milvus，免外部向量库）
cd /c/Users/hai/enterprise-agent
VECTOR_STORE_BACKEND=chroma venv/Scripts/python.exe -m uvicorn src.api.server:app --host 0.0.0.0 --port 8000
```
打开 `http://localhost:8000/` → 首页右下角浮动聊天 → 发消息看 AI 流式回复（WebSocket）。聊天走 `/ws/chat`，需真实 LLM key（`.env` 的 DashScope qwen key）；无 key 报错属正常。

### 路径 B：Docker Compose（全栈）
```bash
docker compose up -d
# 或本地开发：docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```
> compose 的 `frontend` 服务挂载 `./static` 到 nginx，跑之前务必先 `npm run build` 生成 static/。

---

## 9. 给用户的话（接手者不必看 / 但本会话的接手者正是"下一个对话"，务必读）

你这个项目的真实身份：**个人简历作品集，对标阿里云 AI 助理的智能客服仿写，按生产级标准做**（详见第 0 节）。

### 本次会话（2026-08-07 晚间）做了什么（已验证，已推送 GitHub）
1. **引用气泡（citations）全链路打通**：AI 回复下方出现「引用知识片段 N」可展开气泡，对标阿里云智能客服坐席引用。改了 protocol / nodes(rag_node 补检) / routes(_build_citations) / 前端 App.tsx+App.css / AdminDashboard 命中测试徽章。
2. **知识库命中测试做精**：加「采用 / 低于阈值」徽章 + 文档标题 + 内容折叠。
3. **多租户 + RBAC 隔离核查**：产出 `docs/多租户-RBAC隔离核查.md`，实施了 P0（堵空 tenant 后门）；**P1 运行化后续完成并推送，两真实租户互不可见端到端验证**。
4. 修了一处回归：P0 把隔离变严后，WS 匿名聊天的空 tenant 看不到 default 库 → 气泡被打挂，用 `or "default"` 兜底修好（见坑 39）。

### 待你下一步
- **多租户运行化 P1 已完成**：两真实租户互不可见的端到端演示已实现并推送（含 `tests/test_ticket/test_multitenant.py` 验证）。剩余 P2（RBAC 租户维度校验、WS 匿名 tenant 独立化）待做。
- 引用气泡 / 隔离修复 / 真实云 API 接入 / P1 多租户均已推送 GitHub，工作区与 origin 同步。
- 之前遗留的「真实云 API 接入那批后端文件」（aliyun_client.py 等）已随全量推送入仓，无需再决策。

**铁律重申**：绝不要 `git add .` / `git add -A`。本会话全程只改了指定文件并已推送指定路径。

<details><summary>📜 历史：2026-08-06 前端 Design System v2 会话（已提交 f2f6ab0 推送）</summary>

1. 设计系统 v2：深色优先 + 玻璃拟态 + 渐变品牌色，Landing / 聊天挂件 / 管理后台统一换肤，聊天/RBAC/登录零破坏。
2. 三处 UI 修复：导航栏提亮、技术细节手风琴、管理后台样式找回（根因：AdminDashboard 用无前缀类名，重写 App.css 时只写 `.dash-*` 导致后台掉皮）。
3. Hero 背景定稿：纯静态 SVG 几何色块（暖橙活力），零依赖零动画零 glow。

遗留：工作区还有一批**未提交的后端改动**（`aliyun_client.py` / `cloud_provider.py` / `resource.py` 等，疑似真实云 API 接入），刻意没动、没提交，等用户决策。
更早会话遗留的「本机 Postgres Docker 端到端验证」是否完成未知，步骤在 `POSTGRES_LOCAL_SETUP_GUIDE.md`。

</details>

> 注：本交接文档（HANDOFF.md）本次被更新，当前是修改态未提交。如需入仓，单独 `git add HANDOFF.md` 提交即可。
