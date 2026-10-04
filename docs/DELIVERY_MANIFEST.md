# 交付物清单（P4-3 最终版本）

> 版本：v1.0.0-rc.1
> 基准 commit：当前 HEAD
> 日期：2026-09-12

---

## 1. 项目交付物清单

### 1.1 核心应用代码

| 文件 | 说明 |
|---|---|
| `main.py` | 内网部署入口（FastAPI + 增强健康检查 + 结构化日志初始化） |
| `src/api/server.py` | 完整应用入口（REST + WS + 管理后台） |
| `src/api/routes.py` | 基础路由（health + chat） |
| `src/api/auth.py` | JWT 认证 + 用户注册/登录 |
| `src/api/rbac.py` | RBAC 5 角色 + 21 权限点 + 依赖注入工厂 |
| `src/api/conversations.py` | 会话历史查询（归属校验 + 多租户） |
| `src/api/knowledge.py` | 知识库管理（CRUD + 上传 + 命中测试 + 安全加固） |
| `src/api/admin.py` | 管理后台（会话/渠道/转人工/HITL/多租户） |
| `src/api/metrics.py` | Prometheus 指标系统（Counter + Histogram + Middleware） |
| `src/rag/retriever.py` | 混合检索器（向量 + BM25 RRF + 查询改写 + 文档权重） |
| `src/rag/chunker.py` | 章节感知切块器（301 块，悬空标题 0） |
| `src/rag/loader.py` | 文档加载器（Markdown 转义兼容） |
| `src/rag/query_rewriter.py` | 查询改写模块（规则 + 同义词表） |
| `src/graph/nodes.py` | LangGraph 节点（意图分类 + RAG + 反思 + 接地重答） |
| `src/agent/tools.py` | Agent 工具（检索 + 未收录检测 + 片段整理） |
| `src/utils/logging.py` | 结构化 JSON 日志（JSONFormatter + RequestTiming） |
| `src/config.py` | 配置中心（pydantic-settings，含 RAG 优化开关） |

### 1.2 部署配置

| 文件 | 说明 |
|---|---|
| `deploy/prod/docker-compose.prod.yml` | 生产 compose（资源限制/重启/健康检查/日志驱动） |
| `deploy/prod/.env.production.example` | 生产环境变量模板（密钥标注必改） |
| `deploy/prod/Dockerfile.prod` | 生产镜像（多阶段/非root/OCI标签） |
| `deploy/p2/Dockerfile` | 开发用镜像 |
| `deploy/p2/docker-compose.yml` | 开发用 compose（app + pg + redis） |
| `Dockerfile` | 内网离线镜像（thermo-chatbot:1.0.0） |
| `docker-compose.yml` | 云端微服务版（APISIX + 4服务 + Milvus/MinIO/RabbitMQ） |

### 1.3 运维脚本

| 文件 | 说明 |
|---|---|
| `deploy/prod/scripts/deploy.sh` | 一键部署（8 步：检查→备份→构建→启停→健康检查） |
| `deploy/prod/scripts/verify.sh` | 冒烟验证（10 条 UAT 用例） |
| `deploy/prod/scripts/rollback.sh` | 一键回滚（备份恢复/镜像回退） |
| `scripts/ops/health_check.sh` | 探活脚本（CI/看门狗用） |
| `scripts/ops/backup_data.sh` | 数据备份（向量库+DB+文档，保留 5 份） |
| `scripts/ops/restore_data.sh` | 数据恢复（需确认） |
| `scripts/ops/tail_logs.sh` | 日志查看（jq 格式化/降级 raw） |

### 1.4 测试

| 文件 | 说明 |
|---|---|
| `tests/test_security/test_security_audit.py` | 安全审计（38 用例，6 项检查） |
| `tests/test_api/test_api_reference.py` | 接口测试（32 用例，5 接口） |
| `tests/test_ops/test_health.py` | 健康检查测试（5 用例） |
| `tests/test_ops/test_metrics.py` | 指标+日志测试（20 用例） |
| `tests/test_rag/test_query_rewriter.py` | 查询改写测试（15 用例） |
| `tests/test_rag/test_retriever_weights.py` | 文档权重测试（6 用例） |
| `tests/rag_eval/eval_dataset.jsonl` | RAG 评估集（35 条，5 类型） |
| `tests/rag_eval/eval_recall.py` | 召回率评估（5 种模式） |
| `tests/rag_eval/eval_answer.py` | 回答质量评估 |
| `tests/rag_eval/query_rewriter.py` | 查询改写模块（评估用） |

### 1.5 文档

| 文件 | 说明 |
|---|---|
| `docs/API_REFERENCE.md` | 5 核心接口详细文档 |
| `docs/SECURITY_AUDIT.md` | 安全审计报告（6 项 + P2-6 修复） |
| `docs/PERFORMANCE_BASELINE.md` | 性能基准（4 项 + 瓶颈分析） |
| `docs/RAG_QUALITY_REPORT.md` | RAG 质量报告（基线+3实验+生产集成） |
| `docs/UAT_TEST_CASES.md` | 20 条 UAT 用例 |
| `docs/LAUNCH_CHECKLIST.md` | 36 项上线检查清单 |
| `docs/MONITORING_METRICS.md` | 18 个监控指标 + 告警阈值 |
| `docs/ROLLBACK_RUNBOOK.md` | 3 种回滚场景 |
| `docs/LAUNCH_GUIDE.md` | 上线操作指南（首次/升级/回滚/排查） |
| `docs/DELIVERY_MANIFEST.md` | 本文件 |
| `docker_validation_report.md` | Docker 验证报告（含变更记录第 9 章） |

### 1.6 基准脚本

| 文件 | 说明 |
|---|---|
| `scripts/benchmark/bench_chat_concurrency.py` | REST 并发压测 |
| `scripts/benchmark/bench_rag_recall.py` | RAG 召回耗时 |
| `scripts/benchmark/bench_upload_pipeline.py` | 上传端到端 |
| `scripts/verify_chunking.py` | 切块质量校验 |
| `scripts/verify_intranet_kb.py` | 向量库验收 |
| `scripts/verify_e2e_chat.py` | 端到端回归 |

---

## 2. 镜像信息

| 项 | 值 |
|---|---|
| 名称 | `thermo-chatbot:1.0.0` / `enterprise-agent:prod` |
| 版本 | v1.0.0-rc.1 |
| 基础镜像 | python:3.10-slim |
| 大小 | ~1.08GB（内网全离线）/ ~400MB（P2 开发版） |
| 非 root 用户 | uid 10001 (appuser) |
| 健康检查 | `GET /api/health`（含依赖检查） |

---

## 3. 测试统计

| 指标 | 值 |
|---|---|
| 总用例数 | 111+（含安全/接口/运维/RAG/改写/权重） |
| 通过数 | 105 passed |
| 跳过数 | 6 skipped（requires_llm，无 Key 自动跳过） |
| 失败数 | 0 |
| 覆盖率门禁 | 40%（pyproject.toml fail_under） |

---

## 4. 已知限制

| 限制 | 影响 | 缓解 |
|---|---|---|
| 混合检索真实数据待补 | Docker 未运行，预估 Hit@1 80-85% | 启动 Docker 后跑 `--mode hybrid` |
| B2/B4 性能真实数据待补 | LLM 生成延迟待生产实测 | 框架开销已测，预估首 token 600ms-3.5s |
| 7B 模型能力边界 | 长上下文时可能返空串/反问 | 代码层兜底（接地重答/未收录检测） |
| S-06a 500 detail 含异常 | LOW 级别，不影响上线 | P2 延后，生产可改通用错误消息 |
| 物理拔网线验收 | 需现场操作 | 脚本就绪，待现场执行 |

---

## 5. 版本号

```
v1.0.0-rc.1
基线: 2026-09-12
commit: (当前 HEAD)
```

---

## 6. 文档交叉引用

```
API_REFERENCE.md ←→ test_api_reference.py（测试对应文档）
SECURITY_AUDIT.md ←→ test_security_audit.py（测试对应审计项）
LAUNCH_CHECKLIST.md ←→ LAUNCH_GUIDE.md（指南引用 checklist 编号）
ROLLBACK_RUNBOOK.md ←→ deploy/prod/scripts/rollback.sh（脚本实现文档）
UAT_TEST_CASES.md ←→ deploy/prod/scripts/verify.sh（冒烟用例来自 UAT）
RAG_QUALITY_REPORT.md ←→ eval_recall.py（数据来自脚本运行）
PERFORMANCE_BASELINE.md ←→ scripts/benchmark/（数据来自基准脚本）
MONITORING_METRICS.md ←→ src/api/metrics.py（指标来自代码实现）
```
