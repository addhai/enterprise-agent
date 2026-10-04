# 上线前检查清单（P4-1）

> 上线前逐项检查，每项含检查方法、预期结果、负责人（留空）、完成状态（留空）。
> 安全项与 P2-5 审计报告和 P2-6 修复结果对应。

---

## 1. 基础设施

| # | 检查项 | 检查方法 | 预期结果 | 负责人 | 状态 |
|---|---|---|---|---|---|
| 1.1 | Docker 镜像版本 | `docker images \| grep thermo-chatbot` | `thermo-chatbot:1.0.0` 存在，ID 与容器一致 | | |
| 1.2 | 容器资源限制 | `docker inspect thermo-intranet \| grep Memory` | `--memory=1g --cpus=1.0` 生效 | | |
| 1.3 | 端口映射 | `docker ps --format "{{.Ports}}" thermo-intranet` | `0.0.0.0:8000->8000/tcp` | | |
| 1.4 | 网络隔离 | `docker network ls \| grep thermo` | `thermo-net` 存在，业务容器在同一网络 | | |
| 1.5 | ollama 容器运行 | `docker ps \| grep ollama` | ollama 容器 Up，qwen2.5:7b + bge-m3 模型已拉取 | | |
| 1.6 | 健康检查通过 | `curl http://localhost:8000/api/health` | `{"status":"ok","service":"thermo-chatbot-backend"}` | | |

## 2. 配置项

| # | 检查项 | 检查方法 | 预期结果 | 负责人 | 状态 |
|---|---|---|---|---|---|
| 2.1 | .env.intranet 不含真实密钥 | `grep -i key .env.intranet` | 无 sk-xxx / AK 密钥明文（Key 在运行环境注入） | | |
| 2.2 | LLM_MODEL 配置 | 检查 .env.intranet | `LLM_MODEL=qwen2.5:7b`（内网）或 `qwen-plus`（云端） | | |
| 2.3 | 向量库路径 | 检查 CHROMA_PERSIST_DIR | 指向 `/app/chroma_data`，目录存在且有数据 | | |
| 2.4 | REWRITE_ENABLED | 检查 .env.intranet 或默认值 | `true`（查询改写已开启） | | |
| 2.5 | DOC_WEIGHTS | 检查 .env.intranet 或默认值 | 含 `fault_troubleshooting_manual.md:1.5` 等 5 个权重 | | |
| 2.6 | RETRIEVAL_SOURCE_CAP | 检查 .env.intranet | `2`（来源配额） | | |
| 2.7 | HOST/PORT | 检查 .env.intranet | `HOST=0.0.0.0 PORT=8000` | | |

## 3. 数据

| # | 检查项 | 检查方法 | 预期结果 | 负责人 | 状态 |
|---|---|---|---|---|---|
| 3.1 | 向量库标准块 | 容器内 `python -c "import chromadb; ..."` | knowledge_base collection count = 301 | | |
| 3.2 | 向量库句子块 | 同上 | knowledge_base_sentences collection count = 956 | | |
| 3.3 | 向量库维度 | 同上 | 1024 维（bge-m3） | | |
| 3.4 | 7 篇文档 md5 | `docker exec thermo-intranet md5sum /app/data/docs/*.md` | 7 个文件，md5 与镜像内一致 | | |
| 3.5 | 数据库初始化 | `docker exec thermo-intranet python -c "import sqlite3; ..."` | agent.db 含 10 张表（users, tenants, tickets, ...） | | |
| 3.6 | 切块质量 | `python scripts/verify_chunking.py` | 301 块，悬空标题结尾 0 个 | | |

## 4. 安全

| # | 检查项 | 检查方法 | 预期结果 | 负责人 | 状态 |
|---|---|---|---|---|---|
| 4.1 | S-03a 路径穿越已修复 | `pytest tests/test_security/::TestFileUploadValidation -v` | 14 个测试全部 PASS | | |
| 4.2 | S-05a 匿名删除已修复 | `pytest tests/test_security/::TestInfoLeak::test_anonymous_cannot_delete -v` | PASS（返回 403） | | |
| 4.3 | JWT_SECRET 非默认 | 检查 `.jwt_secret` 或环境变量 | 非仓库内写死的默认值，32 字节以上 | | |
| 4.4 | CORS 配置 | 检查 server.py CORS 中间件 | `allow_origins` 不含 `*`（生产环境限制来源） | | |
| 4.5 | 文件上传限制 | 上传 .py / 11MB / `../../../etc` 文件 | 分别返回 400 / 413 / 400 | | |
| 4.6 | .env 不含中文注释 | `grep -P "[^\x00-\x7F]" .env.intranet` | 无非 ASCII 字符（防止编码问题） | | |
| 4.7 | 密钥扫描 | `gitleaks detect --source .` | EXIT=0（无密钥泄露） | | |

## 5. 验证

| # | 检查项 | 检查方法 | 预期结果 | 负责人 | 状态 |
|---|---|---|---|---|---|
| 5.1 | 健康检查 | `curl http://localhost:8000/api/v1/health` | HTTP 200，status=ok | | |
| 5.2 | 核心问答 1 | 发送"测温范围是多少？" | 回答含 -20 和 550 | | |
| 5.3 | 核心问答 2 | 发送"保修期是多久？" | 回答含 12个月 | | |
| 5.4 | 核心问答 3 | 发送"E03故障码怎么处理？" | 回答含"未收录" | | |
| 5.5 | 全量测试 | `pytest tests/ -o addopts="" -q` | passed >= 100, failed = 0 | | |
| 5.6 | 向量库验收 | `docker exec thermo-intranet python scripts/verify_intranet_kb.py` | 9/9 ALL PASS | | |
| 5.7 | 端到端回归 | `python scripts/verify_e2e_chat.py` | 36 项检查全 PASS | | |
| 5.8 | 回退方案 | 确认 REWRITE_ENABLED 可一键关闭 | `REWRITE_ENABLED=false` 后检索用原始查询 | | |
| 5.9 | 文档权重回退 | 确认 DOC_WEIGHTS 可清空 | `DOC_WEIGHTS=""` 后所有文档权重 1.0 | | |
| 5.10 | 物理拔网线验收 | 断网后访问服务 | 零网络可读 1257 分片，问答正常 | | |

---

## 检查统计

| 类别 | 项数 |
|---|---|
| 基础设施 | 6 |
| 配置项 | 7 |
| 数据 | 6 |
| 安全 | 7 |
| 验证 | 10 |
| **合计** | **36** |
