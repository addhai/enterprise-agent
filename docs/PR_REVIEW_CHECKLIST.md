# PR 评审清单（Code Review Checklist）

> 每一次合并前，Author 与 Reviewer 逐条核对。门禁（CI）只拦"能不能跑"，
> 这份清单拦"该不该合"——资深开发带练时以此为准做现场 review。

## 0. 合并前自检（Author 必做）
- [ ] 本地已跑 `make lint` 且 0 error（ruff 规则见 `pyproject.toml`）
- [ ] 本地已跑 `make test-cov`，覆盖率**不低于** `pyproject.toml` 中 `fail_under`
      ⚠️ 若新增代码未被测试覆盖，先补测试，不要靠调低阈值蒙混
- [ ] SAST 通过：`python-security` 门禁（bandit + semgrep）无新增 Medium+ / ERROR 告警；
      任何 `# nosec` 必须带理由，禁止无理由静默抑制（见 §8）
- [ ] 无新增 `except Exception: pass` / 宽捕获后直接 `return` 原始错误信息（见下方"异常处理"）
- [ ] 不存在把内部异常原文回显给最终用户（安全红线）
- [ ] 新增/修改的公开接口有类型注解与 docstring

## 1. 设计
- [ ] 单一职责：这个函数/类只做一件事
- [ ] 依赖可注入：外部依赖（LLM、DB、Redis、HTTP）通过参数/接口传入，便于测试 mock
- [ ] 没有重复代码（DRY）；复用了既有 `PermissionChecker` / `PermissionCache` 等基础设施
- [ ] 配置走 `src/config.py`，**不**在代码里硬编码密钥/URL

## 2. 异常处理（本项目重点短板）
- [ ] 抛出的都是具体异常（自定义 `AgentError` / `ToolError`），而非裸 `Exception`
- [ ] 对外错误信息是"安全消息 + request_id"，原始 traceback 只进日志不进响应
- [ ] 资源清理用 `try/finally` 或上下文管理器，异常路径不泄漏连接/文件句柄
- [ ] 重试仅针对**可重试**错误（超时/5xx），其余错误快速失败（fail fast）

## 3. 并发与性能
- [ ] async 函数内**不**调用阻塞式 `time.sleep` / 同步重 IO（用 `asyncio.sleep`）
- [ ] 共享状态有保护（锁 / 不可变），无数据竞争
- [ ] DB/外部调用走连接池，无每请求新建连接
- [ ] 热点路径有缓存（如 `PermissionCache`），且缓存有 TTL 与失效策略

## 4. 安全
- [ ] 多租户：`tenant_id` 由后端强制注入，LLM 无法跨租户（复用现有模型）
- [ ] 权限：敏感操作经 `PermissionChecker`，参数越权经 `validate_params`
- [ ] 无 SQL 字符串拼接 / 命令注入；用户输入经校验
- [ ] 密钥/PII 不出现在日志与错误信息

## 5. 可观测性
- [ ] 关键路径有结构化日志（含 `request_id` / `tenant_id`），非 `print`
- [ ] 对外错误返回带 `request_id`，便于线上按 ID 查日志
- [ ] 新增指标有 `record_*` 上报（参考 `src/api/metrics.py`）

## 6. 测试（确定性优先）
- [ ] 新逻辑有**确定性单测**（不依赖真实 API Key / 外部网络）
- [ ] 外部依赖用 `unittest.mock` / `pytest-mock` / respx 隔离（参考 `tests/conftest.py`）
- [ ] 集成测试（真实 LLM/外部依赖）必须 gated：默认 skip，仅 `RUN_INTEGRATION_TESTS=1` + API Key 才跑；
      **不得**用 `pytest.skip` 掩盖"CI 假绿"（参考 `tests/test_agent/test_agent.py` 的 `live_agent` fixture）
- [ ] Agent/外部服务测试走注入式 `FakeLLMClient` 等假实现，而非直连真实模型
- [ ] 异步测试用 `asyncio_mode=auto`（已在 `pyproject.toml` 配置，无需手标）
- [ ] 边界条件覆盖：空输入、超时、权限拒绝、降级路径

## 7. 文档
- [ ] 公开函数/类有 docstring（参数、返回、异常）
- [ ] 行为变更同步了 `改动方案.md` 或接口文档

## 8. SAST 安全门禁（CI 强制阻断）
- [ ] `bandit -c bandit.yaml -r src/ --severity-level medium` 无新增 Medium+ 告警（B104 已在配置 skip）
- [ ] `semgrep --severity ERROR` 无新增 ERROR 级告警
- [ ] 若有 bandit/semgrep 误报，按以下规范处理并留痕：
  - 容器/微服务绑定 `0.0.0.0`（B104）→ 在 `bandit.yaml` 的 `skips` 加理由，不逐处 `nosec`
  - 非密码学哈希（抽样/去重用 md5/sha1）→ 改用 `hashlib.xxx(..., usedforsecurity=False)`（正解），
    或带理由 `# nosec B3xx`
  - 参数化 SQL 被 B608 误判 → 用 `"".join([...])` 组装查询（避免 `+` 拼接被静态分析误判），
    **不要**删除参数化去拼字符串
  - `urlopen` 指向受信任配置端点（B310）→ 在调用**同行**加 `# nosec B310`（note: 必须同行才生效）
  - 任何 `# nosec` 必须与被标记代码**同行**且带理由，禁止无理由静默抑制

---
**Reviewer 签字前确认**：以上 0–7 全部勾选，或每条未勾选项有显式说明（如"本期不覆盖，见 issue #xxx"）。
