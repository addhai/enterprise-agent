# Enterprise Agent — 高效 QA 流程设计文档

> 目标：在不牺牲"生产级"标准的前提下，把 QA 从「慢、靠人、不可信」改造成「快、左移、自动化、可度量」。
> 适用范围：enterprise-agent（FastAPI + React 全栈 + 4 个 A2A Agent）。
> 设计日期：2026-08-25

---

## 0. 先看结论（一分钟版）

| 维度 | 现状 | 目标 |
|------|------|------|
| 反馈回路 | 问题要等 push 后 CI 才暴露 | 本地 30 秒内拦截 80% |
| 测试并行 | 单进程跑 ~950 用例 | `pytest-xdist` 并行，3~4 倍提速 |
| 覆盖率门禁 | 40%，且核心 `src/protocols/*` 被 `omit` 整体豁免 | ≥60%，核心 Agent 层不豁免 |
| 前端质量 | 无单测，CI 不阻断 | Vitest 单测 + 构建双阻断 |
| 手动 QA | 手测清缓存 / 注入 WS stub / 碰 localStorage 坑 | Playwright E2E 自动化替代 |
| CI 真相源 | GitHub(40%) 与 GitLab(35%) 双配置漂移 | 仅保留 GitHub Actions 单一真相 |
| 评审 | 仅靠人工勾选清单 | 分支保护 + 1 评审 + 自动化为主 |

核心思路：**Shift-Left（左移）+ 分层门禁（Tiered Gates）+ 把脆弱的手动步骤自动化**。

---

## 1. 现状诊断（基于仓库真实代码）

### 瓶颈 1：双 CI 漂移，维护双倍且行为不可信
- `.github/workflows/ci.yml`：覆盖率 `fail-under=40`，只跑 `pytest -m "not integration"`。
- `.gitlab-ci.yml`：`--cov-fail-under=35`，且 `python-lint` 才跑 ruff，GitHub 侧不跑 ruff。
- 同一仓库两套互相打架的配置 → 开发者不知道哪套是真相，改一处要同步两处。
- **决策**：仓库托管在 GitHub（`github.com/addhai/enterprise-agent`），以 GitHub Actions 为单一真相源，GitLab CI 应停用/删除。

### 瓶颈 2：覆盖率门禁形同虚设
- `pyproject.toml` 中 `omit` 把整个 `src/protocols/*` 排除在覆盖率统计之外。
- 而这正是 4 个 A2A Agent（Orchestrator / 客服 / 性能专家 / 安全专家）——系统的核心大脑。
- 结果：**核心层零度量**，覆盖率数字再高也不代表质量。门禁 40% 也太低，几乎不拦人。

### 瓶颈 3：无并行、浪费的服务、反馈慢
- 无 `pytest-xdist`（`requirements.txt` 未装），~950 用例单进程串行跑，CI 反馈以分钟计。
- GitLab 启动 postgres/redis 服务，却被 `conftest.py` 的内存库架空，纯耗时。

### 瓶颈 4：前端测试不阻断 + 无本地钩子
- `frontend-build` 只做 `oxlint + tsc + vite build`，**没有前端单测**。
- 无 `pre-commit` → 门禁只在 CI 生效，开发者本地无拦截，必须等 push 后才知道红。
- UI 回归只能靠 `HANDOFF.md §6` 的手测：浏览器视觉审计、`Ctrl+Shift+R` 清缓存、注入 WebSocket stub、`about:blank` 下 localStorage 报错等极易出错的步骤。

### 瓶颈 5：质量门只挂在 CI，评审靠人肉
- 无 PR 模板、无 CODEOWNERS、无分支保护、无 commitlint。
- 「该不该合」靠 `docs/PR_REVIEW_CHECKLIST.md` 人工 0~8 项勾选。
- `requires_llm` / `integration` 用例默认跳过 → 真实云路径在 CI 完全不测（合理，但需有本地/受保护环境跑的出口）。

---

## 2. 设计原则

1. **左移（Shift-Left）**：越早发现越便宜。把 lint/快测推到开发者机器本地（pre-commit），把慢/贵的测试留在 CI 深层。
2. **分层门禁（Tiered Gates）**：按"快→慢、便宜→贵、必过→可选"分层，每层只做自己该做的，互不阻塞。
3. **单一真相源（Single Source of Truth）**：只保留一套 CI、一份覆盖率配置，杜绝漂移。
4. **自动化脆弱的手动步骤**：凡是"每次都要人做、容易忘、容易错"的（清缓存、WS stub、E2E 点击），用 Playwright 固化成可重复脚本。
5. **核心层不可豁免**：覆盖率统计必须包含 `src/protocols/*`，否则门禁无意义。
6. **密钥红线不变**：真实 LLM / 云 AK 测试只在本机或受保护环境跑，绝不进公网 CI。

---

## 3. 目标 QA 流程（四层门禁模型）

### Tier 0 — 本地 Pre-commit（开发者机器，目标 <30s）
- 工具：`pre-commit` 框架 + `ruff`（lint + 格式化）。
- 快测：跑标记为非集成、非 LLM 的单元测试子集（`pytest -m "not integration and not requires_llm"` 的子集或专属快测目录）。
- 价值：把 80% 的"低级错"（格式、未用导入、明显逻辑）挡在 push 之前，CI 不再红在 lint 上。

### Tier 1 — PR 快速门禁（GitHub Actions，目标 <5min）
- `pytest -n auto`（xdist 并行）跑全部非集成单测。
- 覆盖率门禁 **≥60%** 且**移除 `src/protocols/*` 的 omit**（核心层纳入统计）。
- 前端：`vitest` 组件单测 **阻断** + 现有 `tsc -b && vite build` 阻断。
- 类型安全：Python 加 `mypy --strict` 基础门禁（渐进开启，先不阻断，稳定后转阻断）。
- 触发：每次 PR / push 到分支。

### Tier 2 — 深度 CI / 夜间（GitHub Actions scheduled，目标可控）
- 集成测试：用 `docker-compose` 起 postgres + redis（**这次是真的用**，不再被内存库架空），跑 `integration` 标记用例。
- SAST：`bandit`（中危阻断）+ `semgrep`（ERROR 阻断，去掉 `|| true`）。
- 容器扫描：`trivy` 扫镜像。
- **E2E 冒烟**：`Playwright` 覆盖管理后台关键链路（登录 → 看板 → 工单 → 知识库），**替代 HANDOFF §6 的手测三步**。
- 真实云路径（`requires_llm`）：仅在设置了密钥的受保护环境手动触发，**不进公网 CI**。

### Tier 3 — 发布门禁（合并/打 tag 时）
- 分支保护：Tier 1 全绿 + 至少 1 个评审通过才允许合并。
- PR 模板 + CODEOWNERS，明确 reviewer 与责任边界。
- 人工验收清单降级为"轻量 review 指南"，不再是唯一闸门。
- 仅 `vX.Y.Z` tag + 手动审批才触发生产部署（沿用现有规则）。

---

## 4. 关键改造点（落到你们仓库的具体改法）

### 4.1 统一 CI（消除漂移）
- 保留 `.github/workflows/ci.yml`；停用/删除 `.gitlab-ci.yml`。
- 单一覆盖率配置写在 `pyproject.toml`，GitHub Actions 引用，**不再出现 40 vs 35 的第二个数字**。
- 建议把"覆盖率 / ruff / bandit"等阈值抽到一处文档注释或 `Makefile`，避免再漂移。

### 4.2 加 pre-commit（本地秒级拦截）
`.pre-commit-config.yaml`：
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: local
    hooks:
      - id: fast-tests
        name: fast unit tests
        entry: pytest -q -m "not integration and not requires_llm"
        language: system
        pass_filenames: false
        stages: [push]   # 仅在 push 前跑，不拖慢每次 commit
```
> 提示：快测挂 `stages: [push]`，避免每次 `git commit` 都等测试；用 `git commit --no-verify` 仅在你确信时跳过。

### 4.3 并行 + 收紧覆盖率（Tier 1）
`pyproject.toml` 调整：
```toml
[tool.pytest.ini_options]
addopts = "-n auto -q"          # 开 xdist 并行
markers = ["integration: ...", "requires_llm: ..."]

[tool.coverage.report]
fail_under = 60                  # 从 40 提到 60
# 删除或大幅缩减 omit，至少不再整体豁免 src/protocols/*
omit = ["tests/*", "*/migrations/*"]
```
CI 命令改为 `pytest -m "not integration and not requires_llm"`（保留用标记跳过昂贵/需密钥用例）。

### 4.4 前端单测（Tier 1 阻断）
- `frontend/` 引入 `vitest` + `@testing-library/react`，先给 10 个 AdminTab 组件补关键渲染/交互单测。
- `package.json` 加 `"test": "vitest run"`，在 `frontend-build` job 增加一步 `npm test`，失败即阻断。

### 4.5 Playwright E2E（替代手测，Tier 2）
- 把 HANDOFF §6 的"清缓存 / 注入 WS stub / 点后台"固化成 `tests/e2e/admin.spec.ts`：
  - 启动预构建 `static/`，用 `page.route` 拦截 `/ws/chat`（等价于手测里的 WS stub 注入）。
  - 断言登录、看板数字、工单列表、知识库空状态等。
- 价值：一次写好，永久可跑，不再依赖人工记忆和 `Ctrl+Shift+R`。

### 4.6 分支保护 + PR 模板（Tier 3）
- 在 GitHub 开启 branch protection：`main` 需 Tier 1 CI 通过 + 1 评审。
- 新增 `.github/PULL_REQUEST_TEMPLATE.md`（变更说明 / 测试证据 / 风险）。
- 新增 `.github/CODEOWNERS` 指定核心模块 reviewer。

---

## 5. 实施路线图

| 阶段 | 内容 | 周期 | 复杂度 | 收益 |
|------|------|------|--------|------|
| **Phase 1 快赢** | pre-commit(ruff+快测)、停用 GitLab CI、覆盖率提到 60% 并去掉核心层 omit、装 xdist 并行 | ~1 周 | 低 | 反馈从"分钟级 CI"→"秒级本地"；核心层开始被度量 |
| **Phase 2 流程优化** | 前端 Vitest 单测阻断、mypy 渐进门禁、Playwright E2E 冒烟、分支保护+PR 模板 | ~2~3 周 | 中 | UI 回归自动化；评审有章可循；手动 QA 时间大幅下降 |
| **Phase 3 战略自动化** | 集成测试套件(docker 真服务)、夜间 SAST+容器扫描、覆盖率趋势看板、AI 辅助生成测试 | ~1~2 月 | 高 | 真实云路径本地可验；质量可度量、可追踪；趋近生产级 |

---

## 6. 度量指标（上线前后对比）

| KPI | 现在（估） | 目标 |
|-----|-----------|------|
| PR 提交到拿到测试结果 | 单进程 ~数分钟 + 等 CI 排队 | 本地 <30s + CI <5min |
| 核心 Agent 层覆盖率 | 0%（被 omit） | ≥60% |
| 因 lint/格式导致的 CI 红 | 频繁 | 趋零（pre-commit 拦下） |
| 手动浏览器验收耗时 | 每次发版数小时级手测 | 被 Playwright 替代，人只审异常 |
| 双 CI 维护成本 | 2 套同步 | 1 套 |
| 缺陷逃逸率（进手动/生产才发现的 bug） | 高（核心层无度量） | 显著下降 |

---

## 7. 风险与注意

- **密钥红线**：`requires_llm` / 真实云 AK 用例永不进公网 CI；只在本机或受保护环境跑。
- **Flaky 测试**：Windows SQLite 文件锁导致的顺序相关失败，统一改用内存库 + 隔离 fixture，并在 CI 用 Linux runner 避免该问题。
- **覆盖率通胀**：提高 `fail_under` 同时必须去掉 `src/protocols/*` 的 omit，否则数字虚高。
- **不要一步到位**：mypy / 集成测试先"只报不阻断"，稳定后再转阻断，避免一上线就大面积红。

---

*文档由 WorkflowOptimizer 基于仓库真实 CI/测试配置设计。下一步可基于此文档直接落地 Phase 1。*
