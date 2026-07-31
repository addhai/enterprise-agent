# 内部技术分享大纲（团队技术提升 · Phase 4）

> 目标：把"资深开发带练"过程中的隐性经验沉淀为可复用的团队知识。
> 建议每两周一次 30–45 分钟分享，结合当下 PR 做现场 code review。

## 第 1 期：为什么测试会"假绿"，以及如何写出确定性单测
- 病症：直连真实 LLM、`if not API_KEY: skip` → CI 永远绿、覆盖率失真
- 药方：依赖注入 + FakeLLMClient + conftest fixtures（已落地 `tests/test_agent/test_agent_deterministic.py`）
- 现场：把一个旧测试改成确定性版本，跑给所有人看

## 第 2 期：异常处理的"安全红线"
- 病症：回显内部错误给用户、静默 `except: pass` 导致线上盲区
- 药方：自定义异常层次（`src/core/exceptions.py`）+ `safe_message` + 结构化日志
- 现场：模拟一次 503，对比旧/新回复，看日志如何关联 `request_id`

## 第 3 期：async 正确性——事件循环不是装饰品
- 病症：`time.sleep` 阻塞事件循环、并行调用漏 `await` 协程
- 药方：`retry_async` + `inspect.isawaitable` 自动识别（已落地 `src/agent/tools.py`）
- 现场：用 `asyncio` 计时演示阻塞 vs 非阻塞的吞吐差异

## 第 4 期：可观测性从"能跑"到"可控"
- 结构化日志（request_id / tenant_id）、指标上报、错误分级告警
- 结合 Grafana 看板讲"一个线上问题如何 5 分钟定位"

## 第 5 期：代码评审文化与门禁
- 门禁（ruff / coverage / SAST）只拦"能不能跑"，清单（`docs/PR_REVIEW_CHECKLIST.md`）拦"该不该合"
- 现场：随机抽一个本周 PR 按清单走查

---
**配套资产（均已入库）：**
- `pyproject.toml` — ruff + pytest + coverage 单一真相
- `docs/PR_REVIEW_CHECKLIST.md` — 评审清单
- `docs/CODE_STYLE.md` — 规范速查卡
- `src/core/exceptions.py` / `src/core/logging.py` — 异常与日志基础设施
- `src/agent/fake_llm.py` + `tests/conftest.py` — 可测试范式样板
