# Phase5 P1 验收报告

**项目**：enterprise-agent — 工业知识库 AI Agent 内网全离线改造
**日期**：2026-09-18
**前置阶段**：Phase4b（生产配置收口 + 监控修复 + WebSocket 联调，1417 passed）
**P1 目标**：Q1 kb_call_mode 真实语义测试补齐 + Q3 引用页码展示端到端闭环

---

## 一、任务完成总览

| 任务 | 内容 | 状态 |
|---|---|---|
| A | 前端页码徽标展示闭环 | ✅ 完成 |
| B | kb_call_mode 分支级单元测试 | ✅ 完成 |
| C | 多页 PDF 导入 + WS 端到端页码验证 | ✅ 完成 |
| D | uvicorn WS keepalive 修复（C4 阻塞解除） | ✅ 完成 |
| E | 全量回归测试 | ✅ 通过（1 项已知环境遗留） |

---

## 二、任务 A：前端页码展示闭环

### 改动文件

| 文件 | 改动 | 行号（约） |
|---|---|---|
| `frontend/src/App.tsx` | `ChatCitation` 接口新增 `page?: number \| null` 字段 | 752-759 |
| `frontend/src/App.tsx` | 引用卡片渲染处新增页码徽标（title 旁展示「第 N 页」） | 1188-1193 |
| `frontend/src/App.css` | 新增 `.chat-citation-titlewrap` 和 `.chat-citation-page` 样式 | — |

### 验证结果

- `npm run build` 退出码 0，无 TS 错误，无新依赖
- 前端 dev server（Vite，端口 5173）发送查询「T90 热像仪的分辨率是多少」，AI 回答完成后引用卡片正确展示：
  - `thermosense_t90_service_manual.pdf` — 标题旁**「第 4 页」**灰色徽标，匹配度 0.970
  - `product_spec_manual.md` — 无页码徽标（markdown 文档无页码，符合预期）
- ✅ 后端 `citations.page` 字段 → 前端「第 N 页」徽标渲染，全链路打通

---

## 三、任务 B：kb_call_mode 分支级单元测试

### 改动文件

`tests/test_graph/test_nodes_llm.py`（追加 4 个测试用例）

### 新增测试

| # | 测试名 | 验证点 |
|---|---|---|
| 1 | `test_kb_call_mode_never_skips_retrieval` | never 模式跳过检索，Agent 不构建，LLM 直答 |
| 2 | `test_kb_call_mode_always_forces_preretrieval` | always 模式强制预检索，Agent 构建前 retriever 已调用 |
| 3 | `test_kb_call_mode_smart_no_preretrieval` | smart 模式不预检索，Agent 构建正常 |
| 4 | `test_kb_call_mode_unknown_falls_back_to_smart` | 非法值回落 smart，日志有 warning |

### 连带修复

因任务 C 导入 PDF 到 `data/docs/`，旧测试 `test_load_markdown_directory` 假设目录全是 .md 而失效，已在测试侧按 `.md` 过滤修复（保持原测试意图）。

### 验证结果

- 4 个新测试全部通过
- 全量回归：**1417 passed / 23 skipped / 0 failed**（1413 基线 + 4 新测试）

---

## 四、任务 C：多页 PDF 导入 + WS 端到端页码验证

### C1-C3：PDF 生成与入库（已完成）

- 生成 7 页 ThermoSense T90 红外热像仪维修手册：`data/docs/thermosense_t90_service_manual.pdf`
- 生成脚本：`scripts/generate_demo_pdf.py`（fitz + china-s 字体，正文带 `# 标题` 行 + PDF 书签）
- 通过 HTTP API 入库到生产知识库，文档 ID `KB-FB4B3D`，7 切片
- Chroma 只读验证：7/7 块 `page` 字段为整数 1-7，非 None

### C4 阻塞与修复

**阻塞根因**：prod 容器 CPU 跑 7B，单次推理最长约 240 秒；uvicorn 默认 WS keepalive（ping 20s / ping_timeout 20s），ReAct 静默轮次期间连接被 1011 强杀。

**修复**：`deploy/prod/docker-compose.prod.yml:73`，uvicorn 启动命令新增：
```
--ws-ping-interval 300 --ws-ping-timeout 300
```

**容器重建验证**：
- `docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app`
- `docker inspect prod-app-1 --format "{{.Config.Cmd}}"` 确认启动参数含 `--ws-ping-interval 300 --ws-ping-timeout 300`
- 三容器（app / postgres / redis）全部 `(healthy)`
- health 端点 `{"status":"ok","service":"enterprise-agent","aliyun_demo_fallback":false}`，离线合规
- metrics 端点正常返回 Prometheus 文本指标

### C4 WS 端到端验证（脚本：`scripts/verify_pdf_page_citation.py`）

| 用例 | 查询 | 回答 | 命中页码 | 事实词 | 结果 |
|---|---|---|---|---|---|
| 1 | T90 热像仪的探测器分辨率和帧频分别是多少？ | 分辨率 384×288 像素，帧频 50Hz | page=2 (score=1.0), page=4 (score=0.927) | 384, 50 | ✅ PASS |
| 2 | T90 报 F02 故障代码是什么意思，怎么处理？ | F02 快门卡滞，进入维护菜单执行两次快门校正 | page=5 (score=1.0), page=7 (score=0.186) | F02, 快门 | ✅ PASS |

**RESULT: ALL PASS**

- citations 中 PDF 来源的块 `page` 字段为非 None 整数（2/4/5/7）
- markdown 来源的块 `page=None`（符合预期）
- rerank 排序正常，相关文档排前两位

---

## 五、全量回归测试

**命令**：
```
.\venv\Scripts\python.exe -m pytest -o addopts="" -q -n 2 --basetemp=".pytest_tmp" -p no:cacheprovider
```

**首次结果**：1416 passed / 23 skipped / 1 failed / 2 warnings，耗时 215.69s

### 失败项排查与修复

```
FAILED tests/test_agent/test_llm_rebuild_hot_reload.py::TestLLMInstanceRebuild::test_rebuild_happens_through_run_with_trace
openai.APIConnectionError: Connection error.
[WinError 10061] 由于目标计算机积极拒绝，无法连接。
```

**根因**：`.env` 中 `OPENAI_API_BASE=http://127.0.0.1:11434/v1`，但 Ollama 仅在 prod-app-1 容器内监听，11434 端口未映射到主机。测试在主机上用 venv 运行时连接被拒。更深层原因：该测试用 `_stub_inner_agent` 替换内部 agent，但 `run_with_trace` 开头调用 `_ensure_llm_current()` 会**连同 self.agent 一起重建**，桩被替换成真实 LangGraph agent，导致走到真实 LLM 调用。

**修复**（`tests/test_agent/test_llm_rebuild_hot_reload.py`）：移除失效的 `_stub_inner_agent`，改为直接 mock `agent._invoke_agent`：
```python
agent._invoke_agent = lambda messages: {"messages": [], "intermediate_steps": []}
```
重建正常发生（验证 id 变化 + temperature=0.7），但不发起真实 LLM 调用，测试自包含不依赖主机 Ollama。

**修复后单测**：1 passed in 4.08s（原 12.71s 失败）。

**修复后全量回归**：**1417 passed / 23 skipped / 0 failed / 2 warnings，耗时 217.25s**

---

## 六、遗留项

| # | 遗留项 | 影响 | 建议 |
|---|---|---|---|
| 1 | 前端 dev server 端口 3000 与 Grafana 冲突 | 低 | Vite 配置 `port: 3000`，监控栈 Grafana 占用 3000；开发时用 `npm run dev -- --port 5173` 规避，或修改 vite.config 默认端口 |
| 2 | 生产环境前端静态文件部署 | 中 | 当前 prod 容器未托管 `frontend/dist`（根路径返回 Not Found），前端需独立 dev server 或构建后由 nginx 托管；生产交付时需补充前端静态文件部署方案 |
| 3 | 多 agent 健康检查持续报错 | 低 | `Probe customer_service/security_expert/... error: All connection attempts failed`，当前 ai_chat 模式不依赖多 agent 子进程，不影响主功能 |
| 4 | 镜像体积 14.7GB | 中 | 符合功能完整性优先原则，后续可考虑多阶段构建/权重分离到 volume |

---

## 七、验收清单

- [x] prod-app-1 用新 keepalive 配置（`--ws-ping-interval 300 --ws-ping-timeout 300`）重建并 healthy
- [x] WS 验证脚本两题 ALL PASS，citations 含非 None page 值（page=2/4/5/7）
- [x] 前端引用卡片展示「第 N 页」徽标（截图验证：thermosense_t90_service_manual.pdf 第 4 页）
- [x] kb_call_mode 4 个分支测试全部通过
- [x] 全量回归 1417 passed / 23 skipped / 0 failed（含 test_rebuild_happens_through_run_with_trace 离线环境修复）
- [x] 无新增外网依赖（health 端点 `aliyun_demo_fallback: false`）
- [x] 无数据丢失（知识库 322 块完整，Chroma 卷未动）
- [x] 监控栈未受影响（Grafana / Prometheus / exporter 持续运行）

---

## 八、结论

**Phase5 P1 全部核心目标达成。**

- Q1 kb_call_mode 三模式（always/never/smart）真实语义 + 非法值回落，4 个分支测试补齐，全量通过。
- Q3 引用页码展示五层贯通（PDF 切分页码注入 → Chroma 存储 → 检索 → citations 构建 → API 返回 → 前端徽标渲染），WS 端到端验证 ALL PASS，前端可视化验证「第 4 页」徽标正常展示。
- C4 阻塞（uvicorn WS keepalive 超时强杀）已修复并验证生效，CPU 跑 7B 长推理不再断连。
- 全量回归 1417 passed / 0 failed，排查并修复了 `test_rebuild_happens_through_run_with_trace` 在离线环境下因桩失效导致真实 LLM 调用的测试缺陷（mock `_invoke_agent` 替代失效的 `_stub_inner_agent`）。

项目可进入下一阶段或交付验收。
