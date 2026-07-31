# 代码规范速查卡（Code Style Cheat Sheet）

> 团队统一约定，配合 `pyproject.toml` 中的 ruff 配置自动校验。
> 目标：让 review 聚焦"该不该这样写"，而非"格式对不对"。

## 工具链（单一真相在 `pyproject.toml`）
| 命令 | 作用 |
|------|------|
| `make lint` | ruff 检查（`E/F/I/B/C4/UP/SIM/ASYNC/PERF`） |
| `make format` | ruff 格式化（行宽 88，双引号） |
| `make test-cov` | 测试 + 覆盖率（门禁阈值见 `fail_under`） |

## 类型
- 所有函数/方法**必须**有返回类型注解（本项目已 100% 覆盖，勿回退）
- 可变容器用 `list` / `dict` / `tuple`，不用 `List`/`Dict` 旧写法（`UP` 规则）
- 可为空用 `Optional[X]`，不用裸 `X = None`

## 命名
- 常量 `UPPER_SNAKE`，类 `PascalCase`，函数/变量 `snake_case`
- 异常以 `Error` 结尾（`AgentError` / `ToolError`）

## 异常处理（重点）
```python
# ✅ 抛具体异常 + 日志，对外只给安全消息
try:
    result = call_external()
except ToolCallTimeout as e:
    logger.warning("tool=%s timeout req=%s", name, request_id, exc_info=e)
    raise ToolError("外部服务暂时不可用，请稍后重试") from e

# ❌ 禁止：回显内部错误给用户
except Exception as e:
    return f"出错了：{str(e)[:100]}"          # 泄露实现细节

# ❌ 禁止：静默吞错导致线上不可观测
except Exception:
    pass                                       # 至少记一条 warning
```

## 测试（重点）
```python
# ✅ 确定性：外部依赖可注入 / mock，不依赖真实 API Key
def test_agent_answers(mock_llm_client):
    agent = CustomerServiceAgent(llm_client=mock_llm_client)
    assert "密码" in agent.run("如何重置密码？")

# ❌ 避免：直连真实 LLM 且 `if not API_KEY: skip` → CI 假绿
```

## 异步
- async 函数内禁止 `time.sleep` / 阻塞 IO；用 `await asyncio.sleep()`
- 重试用 `src/agent/tools.py:retry_tool`（已支持 sync/async）

## 提交
- 一个 PR 一个关注点；commit message 用祈使句（`fix:`, `feat:`, `refactor:`）
- 合并前对照 `docs/PR_REVIEW_CHECKLIST.md` 逐项勾选
