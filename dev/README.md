# dev/ — 调试探针与临时产物归档

这个目录收纳**开发过程中的探针脚本与一次性产物**，它们不参与线上运行，
不进主流程，也**不被任何测试或生产代码引用**。

## 为什么保留而不删

这些脚本记录了实际排查过程，是理解「某个问题当时怎么定位的」的一手材料。
删掉等于丢失上下文。集中放在这里，与 `src/`（生产代码）和 `scripts/`（可复用
运维脚本）明确区分，避免有人误以为是产品的一部分。

## 目录内容

### `scripts/` — 探针与复现脚本

一次性排查用的小脚本，通常是「打印几行日志看看哪一步卡住」或「构造一个最小
复现场景」：

- `probe2.py` ~ `probe5.py`：多轮检索/召回问题的逐层探针
- `probe_agent_raw.py`、`probe_candidates.py`：Agent 原始输出与候选召回观察
- `probe_rescue_effect.py`：兜底逻辑触发效果验证
- `probe_tool_docs.py`：工具文档拼装结果检查
- `retriever_probe.py`：检索器内部状态探针
- `_probe_pdf_chroma.py`、`_probe_pdf_parse.py`：PDF 解析与向量库写入探针
- `repro_agent.py`、`repro_search.py`、`repro_tool.py`：三个链路的最小复现
- `verify_q2.py`、`verify_q2_http.py`、`verify_q2_v2.py`：Q2 验收的不同尝试版本
  （v2 是最终版，前两版保留是为了看排查演进）
- `test_f02.py`：F02 问题的临时验证

**这些脚本大概率跑不通了**：它们硬编码了当时的端口、路径、临时知识库 id，
依赖本地环境状态。只作参考，不保证可执行。

### `artifacts/` — 一次性产物

- `evil_traversal_test.md`：4 字节，内容就是 `evil`。**这是路径穿越漏洞的证据**。
  2026-10-01 测试上传接口时，原始实现直接执行
  `os.path.join(upload_dir, file.filename)`，导致这个文件被写到仓库根目录。
  该漏洞已修复（见 `src/api/knowledge.py` 的 `_safe_filename` 与
  `_resolve_upload_path`），文件保留在此作为修复前的现场记录。
  **不要删** —— 它是「为什么现在要加归属校验」的直接证据。
- `sessions.png` / `tickets.png`：2026-08-14 排查会话与工单接口时的界面截图
- `tool_test.json`：工具调用测试的输出快照
- `acceptance_report_2026-09.md`：早期手工粘贴的功能验收问答输出。**内容残缺**
  （多处回答被截断，如「1. 95）、目标充满视场」这种断句），且测试6 的
  「引用片段截断」当时是写死的常量而非真实检测结果（该脚本已修正）。
  仅作为历史记录保留，**不要当作有效的验收结论引用**。要重新验收请跑
  `python scripts/acceptance_test.py`。
- `screenshots/`：2026-08-14 前端联调时抓的界面截图（dashboard / knowledge /
  customers / health / homepage）。**当前仓库内没有任何文档引用这些图**，
  所以一并归档而不是留在 `docs/screenshots/`——留着只会让人误以为
  文档里配了图而实际找不到。原 `login_page.png` 与 `homepage_full.png`
  内容完全相同（md5 一致），只保留一份并改名为 `homepage.png`。

### 根目录 — 方案快照与损坏留证

- `compose_main.Phase1-microservices.yml`：**已废弃的微服务部署方案**（2026-07-15
  Phase1「云原生架构」时期，100 行）。包含 apisix 网关 + apisix-dashboard +
  api-service / ws-service / agent-worker / rag-service / frontend 六层业务拆分，
  数据层用 milvus + minio + rabbitmq 而非当前的 chroma + redis。
  **当前路线已改为单体 + 内嵌 Ollama**（见 `deploy/prod/docker-compose.prod.yml`），
  这份只作架构演进的对照参考。**不要用它部署** —— 里面的 `docker/api/Dockerfile`、
  `deploy/apisix/` 等配套文件大多已不存在，且 `APISIX_ADMIN_KEY` 有硬编码默认值。
  另注意它标了 `--scale` 水平扩展，但数据层与网关仍是单实例，不能真水平扩展。
  ⚠️ **这份文件本身是截断的**：只有 100 行，YAML 解析出 3 个服务
  （`apisix` / `apisix-dashboard` / `api-service`）就在 `api-service` 的
  `environment` 中途断掉了，`ws-service` / `agent-worker` / `rag-service` /
  `frontend` / 数据层 / volumes / networks 全部缺失。所以它连「完整的旧方案」
  都不算，只是**方案片段**——当历史思路看可以，当配置看会误导。

- `docker-compose.prod.yml.CORRUPTED-714KB`：**已损坏文件的留证**（2026-10-04 发现）。
  原 `deploy/prod/docker-compose.prod.yml` 在 09-22 提交（`9fb9f6e`）时就已损坏：
  文件 714675 字节 / 184 行，其中第 12~16 行是 1.6~2.2 万字符的乱码块
  （正常注释行只该 50 字符内），文件头注释与全部中文注释都是 mojibake。
  症状是 `docker compose config` 无法解析、或解析出空的 environment。
  损坏版本在 git 里只有一个提交，**没有干净版本可回滚**。
  已用桌面留存的正确版本重建（714KB → 9.2KB，YAML 校验通过，关键配置逐项对齐）。
  **这份备份留着是为了对照「重建时有没有漏配置」**，重建已完成，确认无遗漏后可删。
  如果将来再遇到「文件莫名膨胀 + 中文变乱码」，先怀疑同类问题：
  某些编辑器/工具以错误编码反复读写 UTF-8 文件会把内容撑成乱码堆。

## 使用约定

- 新写的探针脚本放这里，**不要放 `scripts/`**（那个目录是可复用的运维工具，
  会被别人当作正式脚本使用）
- 探针脚本顶部应写明「用途 + 一次性 / 依赖某环境状态」
- 归档前先确认文件里没有真实密钥或生产数据
