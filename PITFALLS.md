# PITFALLS.md — 踩坑清单

> 这份文件记录「已经踩过、不要再踩」的坑。属于第 1 层，长期有效。
> 每次开新会话时如涉及前端构建、Docker 操作、Agent 通信，建议一并提供给 AI。
> 新增坑时追加到对应分区，不要删除旧条目。

---

## 高危操作坑（本项目最需要注意）

### 1. compose 命令必须显式指定文件

- **现象**：不带 `-f` 参数执行 compose，操作到了项目根目录的旧编排/容器，导致改错东西
- **正确做法**：所有 compose 命令必须完整写

```powershell
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app
```

- **教训**：项目根目录存在旧编排文件，不带 `-f` 会被默认读取

### 2. 重建只重建 app

- **现象**：重建时误把 postgres / redis 一起重建，数据卷面临风险
- **正确做法**：只 `--force-recreate app`,pg 和 redis 不动
- **数据卷**：`prod-agent-chroma` / `prod-postgres-data` / `prod-redis-data` 绝不可丢

### 3. 前端构建输出到 `static/`,不是 `frontend/dist`

- **现象**：习惯性找 `frontend/dist`,实际由 `frontend/vite.config.ts` 的 `build.outDir: '../static'` 指定
- **正确路径**：构建产物落在项目根的 `static/`
- **教训**：验证静态托管前先确认 `static/index.html` 时间戳已更新

---

## 构建相关

### 4. `functionStatusLabel` 缺少空格导致构建失败

- **现象**：`tsc -b` 报错 `error TS1128: Declaration or statement expected`
- **原因**：`export functionStatusLabel(status: string)` 中 `function` 与函数名之间没有空格
- **教训**：改完代码必须跑构建，不要假设小改动不会出错

### 5. `noUnusedLocals` 导致未使用导入编译失败

- **现象**：`tsc -b` 报错未使用的导入
- **原因**：`tsconfig.app.json` 开启了 `noUnusedLocals: true`
- **教训**：只导入实际用到的组件

### 6. StaticFiles 挂载顺序会覆盖 API 路由

- **现象**：`app.mount("/", StaticFiles(...))` 放错位置后，`/api/v1/*` 返回 HTML 而非 JSON
- **正确做法**：挂载必须在所有 `include_router` 之后
- **强制验证**：`curl.exe -s http://localhost:8000/api/v1/health` 必须返回 JSON

---

## 浏览器验证相关

### 7. 浏览器缓存导致验证误判

- **现象**：代码已改并构建成功，浏览器仍显示旧版内容
- **解决**：`Ctrl+Shift+R` 强制刷新，或 URL 加 `?v=xxx`
- **教训**：验证前先清缓存，否则会浪费时间排查不存在的问题

### 8. agent-browser + WebSocket 不兼容

- **现象**：无头浏览器打开页面后跳转到 `about:blank`,HTML 变空
- **原因**：浮动聊天组件连接 `/ws/chat`,在无头环境中导致页面崩溃
- **解决**：页面加载后立即注入 WebSocket 拦截

```javascript
window.WebSocket = function(){ return { send:function(){}, close:function(){}, set onopen(v){}, set onmessage(v){}, set onclose(v){}, set onerror(v){}, get readyState(){return 1} } };
```

### 9. localStorage 在 about:blank 上不可用

- **现象**：`SecurityError: Failed to read the 'localStorage' property from 'Window'`
- **解决**：确保 WebSocket 拦截在页面跳转前注入

---

## 逻辑相关

### 10. 零值判断逻辑错误

- **现象**：AI 解决率与平均轮数显示 `0%` / `0`,而非 `--`
- **原因**：用 `kpi.sessions.total > 0` 判断有无数据，但该条件下 `ai_resolution_rate` 仍可能为 0
- **正确做法**：直接检查指标值本身
- **教训**：判断「无数据」要检查具体指标值，而非间接的总量指标

### 11. 并行编辑同一文件导致修改丢失

- **现象**：子代理 A 改完文件后，子代理 B 基于旧快照编辑，部分修改被覆盖
- **解决**：修改后用 Read 验证，发现丢失则重新应用
- **教训**：避免多个子代理同时编辑同一文件

---

## 环境坑（跨会话长期有效）

### 12. Windows 中文系统编码

- `psycopg2` 连 Postgres 可能 `UnicodeDecodeError`,必须设 `PYTHONUTF8=1` 与 `PGCLIENTENCODING=UTF8`
- PowerShell 可能误解析 `$` 符号，bcrypt hash 里的 `$` 会导致密码更新失败，已改用 SHA-256 + 固定 salt

### 13. Agent `/health` 端点必须存在

- HealthChecker 每 60 秒 HTTP GET 探活
- Agent 缺 `/health` 会导致前端显示离线
- 必须实现 `GET /health`,返回 `{"status": "ok", "agent": "<agent_id>"}`

### 14. Orchestrator 超时配置

- httpx 默认 30 秒超时对客服 Agent（要调 LLM）太短
- 必须配置 120 秒超时

### 15. 单次推理耗时远超常规预期

- **实测数据**：CPU 单题 5-12 分钟（Q1 725.7s / Q3 656.5s）
- rerank 单批 13.21s → 28.88s（L4 放宽候选池后）
- **教训**：验证时 `--max-time` 要给足，不要按常规 API 的超时预期判断失败

### 16. pytest 在 Windows 下的 torch_cpu.dll 并行崩溃

- **现象**：xdist worker errors
- **规避**：`--deselect tests/test_mcp_tools/test_kb_phase2.py` 后并行，该文件单独串行
- **冻结口径命令**：

```powershell
.\venv\Scripts\python.exe -m pytest -o addopts="" -q -n 4 --basetemp=".pytest_tmp" -p no:cacheprovider --deselect tests/test_mcp_tools/test_kb_phase2.py
```

### 17. 构建期需要联网，运行期必须离线

- 构建时 torch CPU 版从 pytorch.org 下载，可能较慢
- 运行时必须验证 `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`

---

## 健康检查相关

### 18. uvicon WS keepalive 导致长推理被强杀

- **现象**：CPU 长推理（>20s）被 1011 强杀
- **修复**：`--ws-ping-interval 300 --ws-ping-timeout 300`
- **验证**：`docker inspect prod-app-1 --format "{{.Config.Cmd}}"` 应含该参数

### 19. 多 agent 探针报错污染日志

- **现象**：`All connection attempts failed`
- **原因**：ai_chat 模式不依赖多 agent 子进程，probe 失败属预期
- **处理**：`AGENT_PROBE_ENABLED=false`（env + compose 第 62 行透传）
- **状态**：已就位，待容器级实测

---

## 关键文件索引

| 用途 | 文件路径 |
|---|---|
| 后端入口 | `src/api/server.py` |
| LangGraph 节点 | `src/graph/nodes.py` |
| kb_call_mode 判据（未接入） | `src/rag/call_policy.py` |
| 前端入口 | `frontend/src/App.tsx` |
| vite 配置 | `frontend/vite.config.ts` |
| 生产编排 | `deploy/prod/docker-compose.prod.yml` |
| 生产 env | `deploy/prod/.env.production` |
| 运维手册 | `deploy/prod/README-生产部署与运维手册.md` |
| 健康检查 | `src/protocols/health_checker.py` |
| PDF 页码注入 | `src/rag/loaders/pdf_loader.py` |
| WS 路由 | `src/websocket/routes.py` |

---

*来源：`HANDOFF.md` 第 6 节 + `Phase5-后续待完善任务清单.md`，2026-09-30 整合*
