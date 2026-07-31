# 团队技术提升方案 — 落地进度总览

> 基于 `团队技术提升方案.md` 路线图，四阶段已全部落地真实代码/配置（2026-07-31）。
> 下一步：本地 `make test-cov` 校准覆盖率基线，把 `pyproject.toml` 的 `fail_under` 随测试补全逐步上调至 80%。

## 已交付（按阶段）

### Phase 1 · 质量门禁 ✅
- `pyproject.toml`：ruff 规则收紧（E/F/I/B/C4/UP/SIM/ASYNC/PERF）+ pytest 覆盖率配置（含 `fail_under` 门禁、asyncio 自动模式）
- `.gitlab-ci.yml`：python-test 显式注入 `--cov-fail-under`，门禁不可被静默跳过
- `docs/PR_REVIEW_CHECKLIST.md`：7 大类评审清单（设计/异常/并发/安全/可观测/测试/文档）
- `docs/CODE_STYLE.md`：规范速查卡

### Phase 2 · 测试重构 ✅
- `src/agent/fake_llm.py`：`LLMClient` 协议 + `FakeLLMClient` + `OpenAILLMClient`（生产/测试可替换）
- `src/agent/agent.py`：`__init__` 新增 `llm_client` 注入参数（向后兼容，默认生产实现）
- `tests/conftest.py`：共享 fixture（`fake_llm_client` / `make_agent`）
- `tests/test_agent/test_agent_deterministic.py`：5 个确定性单测，不依赖 API Key / 网络

### Phase 3 · 异常与可观测性 ✅
- `src/core/exceptions.py`：异常层次（`EnterpriseAgentError` / `SafeError` / `ToolError` / `AgentRuntimeError` / `PermissionDeniedError` / `InvalidArgumentError`）+ `safe_message`
- `src/core/logging.py`：`get_logger` + `new_request_id` + `RequestContextFilter`（结构化日志带 request_id/tenant_id）
- `src/agent/agent.py`：异常路径改写为"日志留痕 + 安全消息 + request_id"，**不再回显内部错误**、`_report_token_usage` 的静默 `pass` 改为 warning 日志

### Phase 4 · 并发性能 + 内部分享 ✅
- `src/agent/tools.py`：新增 `retry_async`（async 重试，用 `asyncio.sleep`，`inspect` 自动识别协程）；`parallel_tool_call` 修复漏 `await` 协程的 bug
- `docs/TECH_SHARING_2026.md`：5 期内部分享大纲

## 关键改动文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `pyproject.toml` | 新增 | 工程单一真相（lint/test/coverage） |
| `.gitlab-ci.yml` | 修改 | 覆盖率门禁加固 |
| `src/core/exceptions.py` | 新增 | 异常层次 |
| `src/core/logging.py` | 新增 | 结构化日志 |
| `src/agent/fake_llm.py` | 新增 | 可注入 LLM 抽象 |
| `src/agent/agent.py` | 修改 | 依赖注入 + 异常安全 |
| `src/agent/tools.py` | 修改 | async 重试 + 并行修复 |
| `tests/conftest.py` | 新增 | 测试 fixtures |
| `tests/test_agent/test_agent_deterministic.py` | 新增 | 确定性单测样板 |
| `docs/PR_REVIEW_CHECKLIST.md` / `CODE_STYLE.md` / `TECH_SHARING_2026.md` | 新增 | 规范与分享 |

## 待办（需团队配合）
1. 本地 `make test-cov` 测基线，校准 `fail_under`（当前 35 为保守起步值，目标 80）
2. 将旧的 `tests/test_agent/test_agent.py`（直连真实 LLM）逐步迁移到注入式范式
3. SAST 阶段（`python-security`）在 triage 后由 `allow_failure` 改为阻断
4. 按 `docs/TECH_SHARING_2026.md` 排期首期内部分享

## 验证状态
- ✅ 所有新增/修改 Python 文件通过 `py_compile` 语法校验
- ⏳ 运行时测试需 `pip install -r requirements.txt` 后在 `make test-cov` 中跑（当前环境未装 langchain 等依赖，未实跑）
