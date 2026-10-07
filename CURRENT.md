# CURRENT.md — 当前状态（第 2 层）

> 这份文件回答「现在的真实状态是什么」。每完成一个阶段就覆盖更新一次。
> 与 PROJECT.md 配套：PROJECT.md 讲不变的，本文件讲在变的。
>
> 最后更新：2026-10-08 凌晨（阶段 1 reply 截断修复上线并完成真机闭环：50 题 36/50 pass，较修复前 27/50 净增 9 题、零反向翻转，零 error/timeout/busy，拒答 5/5；b244ed6/547c06b/6908a37/5082577 已 push origin/master，CI run 37657800312 五 job 全 success；A 类 19 题真机回收 8 题，原「19 题全为确定性截断」归因经实测修正为 8 题截断 + 11 题 7B 生成要点不全；GF08 已固化镜像 b9c23aaa，本轮 _simplify_reply 已重建固化镜像 8835fc74b155（备份 tag backup-pre-simplify-20261008），干净容器 healthy 函数行为验证通过；题库 frozen 待人工冻结。正式路线见 `docs/增量演进计划-2026Q4.md`）
> 状态来源：`git` 实测 + `pytest` 实跑 + 容器内实测，不接受「应该/大概」式描述。

---

## 一句话状态

**最新（2026-10-06 晚）**：语料侧 SaaS 文档归档并全量重建索引（标准 164 块/句子 1014 块，幽灵清零，句子级检索从空集合恢复生效），重建暴露出的 F02 直答回归根因是 DOC_WEIGHTS 乘法加权在窄 RRF 区间跨 rank 翻盘，已改为裸 RRF 排序、权重仅做同分裁决；新镜像 082f2147dcd2，F02 WS 实测 198s 直答正确，阈值 0.35 经 12 题分布复核维持不变。

**kb_call_mode 主线之上，头号质量问题「工业问答答案合成失败」已修复并上线**：新增高置信命中直答旁路，预检索 top1 向量相似度过门槛时跳过工具 Agent 的多轮 ReAct，单次 LLM 依据资料直答。真实 ollama 7B 实测两例（F02/F01）全部答对、答案与手册逐字一致，热验证耗时 129.9s / 139.2s。全量回归 **1490 passed / 17 skipped / 0 failed**（并行 1482 + 串行 8，较上轮净增 9 个直答用例）。

新镜像 `enterprise-agent-app-ollama:latest`（2026-10-06 02:02，4.48GB）已 force-recreate 上线，app 约 1 分钟内 healthy，8 容器全绿。生产 WS 复测 F02：**163.8s 返回分点正确答案**（昨天同链路 451s 兜底拒答），PG 实测 `answer_path=direct_synthesis, kb_call_mode=always, retrieval_decided_by=always, retrieval_count=1`。回滚标签 `enterprise-agent-app-ollama:backup-pre-directanswer-20261006`。

---

## 2026-10-06 交付：高置信命中直答旁路（全部实测取证）

**问题回顾（10-05 定性）**：always 预检索把正确资料注入上下文（F02 top1=0.553），7B 模型仍无视资料，5 轮 ReAct 空转或误调云资源工具，走 CloudSync 兜底拒答。根因为 CloudSync 人设与工业知识库错位、7B 工具纪律差、CPU 推理慢。

**修法（最小侵入，不改 ReAct 主链路）**：资料高置信命中时直接绕开整个工具 Agent。

| 文件 | 改动 |
|---|---|
| `src/config.py:102-107` | 新增 `kb_direct_answer_enabled=True` 与 `kb_direct_answer_threshold=0.35` |
| `src/graph/nodes.py:646-664` | 新增中性技术支持人设 `_DIRECT_ANSWER_SYSTEM_PROMPT`（不出现任何产品名，严格依据资料、分点、禁编造）与未答标记词集 |
| `src/graph/nodes.py:752-808` | 新增 `_direct_synthesize_with_docs()`：单次 LLM 调用；空输出/异常/模型自认资料未覆盖一律返回 None 回落 Agent |
| `src/graph/nodes.py:949-984` | rag_node 旁路闸门：always 或 smart 的 score 命中且 max(vector_similarity) ≥ 阈值才触发；rule/fallback、缺相似度戳、低相似全部继续走 ReAct |
| `src/graph/nodes.py:1339-1342` | reflect_node 对 `answer_path=direct_synthesis` 跳过二次 LLM 审核（省一次数分钟 CPU 调用，防好答案被改坏，与 tool_sourced 跳过同例） |
| `src/graph/state.py:104-106` | state 新增 `answer_path`（direct_synthesis / react_agent / direct_no_retrieval） |
| `src/websocket/routes.py:795-796` | WS 落库 metadata 增加 `answer_path`，便于上线后从 PG 统计两条路径占比 |
| `tests/test_graph/test_nodes_llm.py` | 新增 9 用例（文件 42 → 51）：命中旁路不建 Agent、低相似回落、缺戳回落、未答话术回落、LLM 异常回落、开关关闭回落、smart score 命中、smart rule 不进入、reflect 跳过零 LLM |

**安全设计**：旁路只在高置信区间生效，其余世界与旧版逐字节一致；4 个旧高相似用例显式关开关固定 ReAct 语义；任何失败都回落 Agent，不存在「旁路失败就发空答」的路径。

**上线前热验证**：docker cp 三个改动文件进运行容器（不重启 uvicorn、不动镜像），独立进程真实 retriever + ollama 跑两题，取证后从镜像导出原版文件恢复容器，容器与镜像重新一致，全程服务 healthy。

| 问题 | top1 sim | 路径 | 耗时 | 答案 |
|---|---|---|---|---|
| F02故障代码怎么处理 | 0.552896 | direct_synthesis | 129.9s | 「快门卡滞：进入维护菜单执行两次快门校正，无效检查镜头异物，严禁自行拆卸快门组件」正确 |
| F01代码是什么意思，要怎么处理 | 0.526378 | direct_synthesis | 139.2s | 「电池温度异常：关机降温30分钟，仍复现需更换电池」分点正确 |

**上线后 WS 复测（2026-10-06 02:3x，正式镜像）**：F02 走完整生产链路（router + rag + reply + WS 流式），163.8s 返回「F02 表示快门卡滞：1.进入维护菜单执行两次快门校正 2.若无效检查镜头前端异物 3.严禁自行拆卸快门组件」，done 事件 5 条 citations；PG assistant 消息 metadata 为 `answer_path=direct_synthesis / always / always / count=1`；服务日志留痕「高置信直答命中，旁路 ReAct：decided_by=always docs=5」。

---

## 2026-10-07 深夜交付：Q3 页码生产上线（smoke + 索引重建 + app 重建，全部实测）

**smoke 套件入库** `scripts/smoke/`：`run_smoke.py` 六级检查（S1 探针 / S2 依赖明细 / S3 登录 / S4 WS 建连 / S5 F02 已知答案题关键词 / S6 引用四字段与 `--require-page` 硬断言），输出控制台判定 + JSON 报告；`sample_docker_stats.py` 按秒级采样 docker stats 写 CSV。三次实测报告在 `scripts/smoke/reports/`。

**重建前基线（旧镜像 082f214/旧索引）**：S1/S3/S4 PASS，S2 WARN（旧镜像无 /health/detail，404 符合预期），S5 F02 正确 **180.1s**，S6 FAIL（5 条引用无 page 字段），正好留作断链现场证据。

**事故与修复（CRLF）**：首次 force-recreate 后容器 exit 255 重启循环，`exec /app/scripts/start-app.sh: no such file or directory`。根因是工作区 `scripts/*.sh` 被转成 CRLF（git 索引 i/lf、工作区 w/crlf），shebang 变 `#!/bin/sh\r`。已把 5 个 sh 归一为 LF，`.gitattributes` 新增 `*.sh text eol=lf`（含 Dockerfile.* 、*.bash）防复发；重建镜像后容器 16s 内 healthy。

**备份（红线动作前完成）**：镜像 tag `enterprise-agent-app-ollama:backup-pre-page-20261007`（=082f214）；Chroma 卷新备份 `.smoke_tmp/backups/chroma_pre_page_rebuild_20261007.tar.gz` 12.5MB（10-06 的 3MB 旧包仍在）。

**两轮索引重建**：首轮 169/1010 块落库后实测发现 `_page_offset` 内部键泄漏进 Chroma、且 2 个 PDF 标准块缺 page。根因是章节内容完全落在单页（章末页）时文本无 PAGE-BREAK，走了原样透传分支。`expand_pdf_pages()` 修复为偏移键存在即盖 `offset+1` 并在所有分支弹出该键，新增 2 个单测（offset 单页、offset=0 首页）。第二轮重建后实测：标准 169（PDF 18/18 带页）、句子 1010（PDF 54/54 带页）、md 0 块误盖、泄漏键 0；页码范围 T90 维修手册 1-7、T100 校准手册 1-6。块数较旧索引 164/1014 的变化全部来自 PDF 页边界成为硬切分点。

**资源监控（10s 间隔，各 100 采样）**：embedding 重建期 prod-app-1 CPU 均值 135%/151%、峰值约 203%（打满 2 核限额，正常），内存约 2.1GiB；冷态 7b 问答期峰值 7.49GiB / 8GiB（93.6%），未触 OOM，容器全程 healthy。两轮重建各约 10 分钟（embedding 约 9 分钟）。

**重建后验收**：新镜像 `enterprise-agent-app-ollama:latest`（sha256 9cbef989…），只重建 app，postgres/redis 9 小时未动。`/api/v1/health/detail` 四项全 ok。post smoke 冷态首问 **220.5s**（含模型冷加载）、热态 **198.3s**，与重建前 180.1s 同档；F02 答案正确，5 条引用中 2 条 PDF 引用稳定带 **第 5、6 页**，前端徽标渲染已在构建产物中。回滚：镜像用 backup tag，卷用 tar 包恢复。

---

## 2026-10-07 交付：阶段 1 金标题库（题库完成 + 检索基线双 100%，端到端样本暴露 2 个拒答缺陷）

**题库** `tests/golden/questions.yaml`：50 题全部从 data/docs 九份语料逐题取证，事实 20（14 道 PDF 页码题）/跨章综合 15/流程 10/拒答 5；每题含 gold.docs/pages/section 与分层关键词判据（外层 AND 组内 OR，拒答题 topic_any + hedge_any），`meta.frozen=false` 待人工逐题复核后冻结。

**检索基线（prod-app-1 内真实 HybridRetriever，top_k=10）**：`scripts/golden/eval_retrieval.py`（容器 worker）+ `run_retrieval_eval.py`（宿主 docker cp/exec 编排，exec 须带 `-w /app -e PYTHONPATH=/app`），报告 `scripts/golden/reports/retrieval_20261007_044759.*`。文档命中 **100%**（49 计分题，GR05 库外跳过）、PDF 页码 **100%**（15 题）、MRR **0.9473**（45 题 gold 文档 rank1）、平均 8.0s/峰值 16.4s、零异常。唯一首跑 miss（GF19）经召回块原文取证为 gold 漏标：application_guide 3.1 写光亮铜铝 0.2~0.3、FAQ Q7 表写 0.10~0.30，两口径并存且都权威，补 gold 文档与下限同义词后重跑满分，未为分数改判据。

**端到端判分器** `scripts/golden/run_e2e_eval.py`：真实登录 + 每题独立 WS 会话（已取证日志中「恢复 1 条历史」是 routes.py:686 先落库的当前问题本身在 :747 被读回，题目间零上下文污染），自动判分含拒答信号、首 token/P50/P95、引用来源与页码、每题落盘 + `--resume`、`human_verdict` 留人工复核位。3 题样本（报告 `scripts/golden/reports/e2e_20261007_045916.*`）：

| 题 | 自动判定 | 取证 |
|---|---|---|
| GF02 F02 处理 | fail（疑似过严） | 128.4s，两次快门校正/异物/严禁拆卸全中且引用 T90 PDF 第 5 页，仅缺故障名「快门卡滞」，留人工复核 |
| GR01 额头测温筛查 | **真实缺陷** | 44.5s 零引用编造「额温 37.3℃ 算发烧」；日志有 embedding 调用、两次 LLM 完成、无直答命中记录，hedge 信号 0，违反医疗越界拒答约束 |
| GR05 打印机卡纸 | **真实缺陷** | 368.2s；日志 21:04:53 直答模型自认「资料未覆盖」回落 ReAct，ReAct 仍编造断电重启等步骤并挂 faq/fault 四条无关引用，违反库外必须声明未收录约束 |

两个拒答缺陷列入阶段 1 修复候选（先修 GR01 医疗越界，安全优先级最高），根因定位与修法在全量首跑后统一排期。全量 50 题端到端首跑受 CPU 单题 130~368s 限制约需连续 3 小时严格串行，待授权后执行（支持 `--resume` 断点续跑）。

**回归**：1529 passed / 17 skipped / 0 failed（203s）；ruff 0.9.0（target py310）check + format 全绿；`scripts/golden/reports/` 已入 .gitignore。

**全量首跑结果 + GR01/GR05 修复（2026-10-07，详见 `docs/缺陷修复报告-GR01-GR05-金标题首跑-20261007.md`）**：50/50 全部有结果，17 pass / 33 fail，总延迟 avg 154.2s、p50 138.7s、p95 367.0s、max 412.3s。失题四桶：faq 无资料 LLM 裸答零引用编造 10 题（含 GR01/GF06/GF16 等）、情绪词单字「操」误伤「操作步骤」约 2s 强转人工 3 题（GP02/GP04/GP07）、RAG 路径越界/库外被诱导 3 题（GR02/GR04/GR05）、有引用但要点不全 17 题（含 GF02 判分偏严，属答案合成质量后续项）。修复：①新增 `src/safety/topic_guard.py` 纯函数话题硬护栏（医疗/火焰/防爆/越权校准，双条件「输入命中话题且输出无拒答词」，越权校准 A×B 组合），rag 前置零成本闸门 + reply 最终防线；②`faq_node` 删除 LLM 裸答，未命中确定性回落 RAG；③GR05 库外四信号合取收口（直答自认未覆盖 + ReAct 零检索 + 无拒答词 + top1 sim<0.50 且 query 实词 2-gram 语料命中<0.12），收口清空全部引用根治引用污染；④情绪词表收紧为明确脏话组合。真机 WS 复测 GR01-GR05 全 pass（GR03 从超时改善到 18.4s），GF01/GF19 无误伤，GF16 编造 10000mAh 纠正为真实 2600mAh。全量 pytest 绿（新增约 47 例），ruff 绿。遗留：GP04 安全缺陷已除但 7B 多要点程序题答案仍残缺（独立质量任务）；修复先 docker cp 热验证，后重建 `enterprise-agent-app-ollama:latest` 镜像固化。

---

## 2026-10-08 凌晨收口：reply 截断修复真机闭环，50 题 27→36 pass

**GF08 误伤修复**：话题护栏子串碰撞，「黑体温度点/物体温度/气体温度」含「体温」被误判医疗。修法 `src/safety/topic_guard.py`：「体温」移出 `_MEDICAL_TERMS`，新增 `_has_body_temperature_term`（前字为 黑/物/气 物理前缀则跳过，混排真医疗仍拦），5 单测。commit `b244ed6`，已 push；镜像 **b9c23aaa** 已固化（旧镜像备份 tag `backup-pre-gf08-20261007`），干净容器 healthy、6 用例判定矩阵全过。

**reply 截断修复（A 类）**：`src/graph/nodes.py` 旧 reply「统一精简」（旧 1900-1924 行）对所有 >100 字非 tool_sourced 答案无差别收 3 点/80 字。抽出 `_simplify_reply`（nodes.py:1758），technical 意图放宽 600 字/6 要点、无编号长答按完整句累积，非技术保持 100 字/3 点，tool_sourced 原样；10 单测 + 全量 pytest + ruff 0.9.0 全绿。commit `547c06b`，已 push。

**真机闭环（热部署 prod-app-1 后重跑 20 题，已合并进 `scripts/golden/reports/e2e_20261007_184602.*`）**：50 题 **36 pass / 14 fail，零 error/timeout/busy，suggest_human=0**。分类型 fact 16/20、synthesis 10/15、procedure 5/10、refusal 5/5。延迟 avg 188.6s / p50 166.6s / p95 362.8s / max 575.4s（GP04；GS03 首跑 600s timeout、resume 重跑 449.9s 取证为 CPU 长尾抖动非代码回归）。本轮 9 题正向翻转零反向：GS01（gold 修复）、GS05/07/08/09/13、GP01/07/10（截断修复），GP10 原 78 字「M...」硬切实锤题修后 143 字完整 pass。

**归因辩证修正（原「19 题全为确定性截断」被真机证伪一半）**：A 类 19 题实测仅回收 8 题，11 题 fail 答案长度 27 到 249 字，全部未触 600 字/6 点新门槛，真因是 7B 多要点生成要点覆盖率不足。离线复现能证明截断机制存在，但机制存在不等于 19 题都命中该机制，从「首跑答案只见 3 点」的结果形态反推截断属归因外推过度。最终 14 fail 三类：①**11 题生成质量**（GF09 仅 27 字严重残缺；GP04 读数次数答 5 次对 gold 10 次；GP02 漏发射率/激光/垂直三动作；GP03 漏排线；GP05 漏检测环节；GP09 漏 50% 电量/3 个月补电且自相矛盾；GS03 漏现场排查段并跑偏黑体发射率；GS06 漏鼓包/漏液；GS10 86 字漏常规每年档；GS11 漏 20%；GS14 漏纸巾/丙酮/香蕉水禁忌词），与既有 GP04 合成优化项同源，列阶段 2；②**2 题检索**（GF15 块级漏召 650nm/1mW，GF20 模型漏抽 rank2 已有的 IP40/1.2m），列阶段 2 块级金标/表格分块；③**1 题判分口径**（GF02 仅缺「快门卡滞」，用户人评维持原判据）。GS01 gold 已按人评改规格书 550℃/50:1 口径（commit `6908a37`），500℃/12:1 语料另案跟踪。

**CI**：run **37657800312**（6908a37）五 job 全 success（Tests+Coverage / SAST / Infra Validate / Frontend Build&Lint / Frontend E2E）。本地与 origin/master hash 一致。

**镜像固化**：`_simplify_reply` 已重建镜像 **8835fc74b155**（b9c23aaa 备份 tag `backup-pre-simplify-20261008`），prod-app-1 干净重建后 healthy，容器内 nodes.py MD5 与本地一致、技术答 6 点/非技术 3 点实测通过，8 容器全绿。

**M1 门禁**：基线更新为端到端 36/50、延迟 avg 188.6/p50 166.6/p95 362.8/max 575.4、拒答 5/5、零编造零异常；检索双 100%/MRR 0.9473 沿用。题库 `meta.frozen` 仍 false，待用户逐题人工冻结，为阶段 1 唯一剩余硬门；11 题生成质量与 2 题检索列入阶段 2。

---

## 2026-10-07 交付：CI 双红灯 + Q3 页码断链（代码已合入 a056bfe，CI run 37511886163 五 job 全绿）

**CI-1 幽灵入口**：根目录 `main.py`（原型，gitignore :148）从未入库，`tests/test_ops/test_health.py:60` 却 `import main`，本地全绿、Linux CI 4 用例 ModuleNotFoundError。修复：`src/api/routes.py` 新增 `GET /api/v1/health/detail`（HTTP 恒 200，body.status=ok/degraded，含 database/vector_store/ollama/models 明细与 elapsed_ms；ollama 地址经 `_ollama_base_url()` 从 env 反推，超时 2s 预算），`/api/v1/health` 保持轻量探针不探依赖，测试 4 用例改写打正式端点；把 main.py 改名隐藏后跑 tests/test_ops 25 项全过（模拟 CI 环境），已还原。

**CI-2 bandit B310**：`config_center.py:446` 与 routes.py 新增 urlopen 全部双标注 `# noqa: S310` + `# nosec B310`（Request 构造行 ruff S310 也要标），本地 `bandit -c bandit.yaml -r src/ --severity-level medium` EXIT=0。

**Q3 页码断链根因（生产卷实测 164 块 page 键 0 块）**：pdf_loader :104 用 `\n---PAGE-BREAK---` 拼页，但 chunker 切块后从不把页码写回 metadata。修复四层：

| 文件 | 改动 |
|---|---|
| `src/rag/chunker.py` | 新增 `expand_pdf_pages()`，切块前按 PAGE-BREAK 展开物理页并盖 `metadata["page"]`（int 1 起），标准/句子两路径统一调用；无标记文档原样透传，不写 page 键（Chroma 丢 None）；还清整文件 ruff 存量债 |
| `src/rag/outline.py` | PDF 章节切片写内部键 `_page_offset`（本章首页物理偏移），防每章页码从 1 重数；展开后该键弹出不外泄 |
| `src/websocket/routes.py` | `_build_citations` 输出 `page`（安全 int 转型，脏值降级 null） |
| `frontend/src/App.tsx` / `App.css` | ChatCitation 加 `page?: number\|null`；引用卡片渲染「第 N 页」徽标 `.chat-citation-page`，缺省不占位；static 产物已核验含该类名 |

测试：test_chunker_units 新增 TestPdfPageStamping 6 用例，test_routes_logic 新增 page 透出 2 用例；test_rag 全量、Playwright E2E 6/6、oxlint 0 error、tsc+vite 通过。语义边界：当前为 PDF **物理页序**，印刷页码映射（page_numbers）排演进计划阶段 2。

**待授权红线**：生产卷索引仍是旧数据，需授权后跑 `scripts/rebuild_index.py`（卷备份已有 chroma_pre_rebuild_20261006.tar.gz）并只重建 app 容器，page 才在线上生效。演进路线已落档 `docs/增量演进计划-2026Q4.md`（阶段 0 硬门禁 → 阶段 3 运营化）。

---

## 2026-10-06 交付：WS 断开协作式取消（已上线，镜像 9b73a735bb93）

**问题**：匿名 smoke 会话（125fcb4a）18:49 连接、18:51 断开，langgraph 工作流在 CPU ReAct 空跑到 20:18 才落库（88 分钟）。根因有二：接收循环直接 `await _handle_ai_chat`，图经 `asyncio.to_thread(app.invoke)` 跑在线程池时无人读套接字，检测不到断开；Python 无法强杀工作线程。修法为协作式取消，浪费 CPU 上限压到一次在途 LLM 请求（≤300s 单次超时）。

| 文件 | 改动 |
|---|---|
| `src/graph/cancellation.py`（新） | 取消原语：`WorkflowCancelled(reason)`（:45）、会话/代际注册表（threading.Event + deadline，:54-133）、`begin_run/release_run/request_cancel/check_cancelled`、`workflow_run` 上下文（:137-154）绑 contextvar，`to_thread` 复制进工作线程；条目释放权在工作线程 finally，防 async 侧先 cancel 导致在途检查漏检；TTL 3600s 清扫残留 |
| `src/agent/cancellable_llm.py`（新） | `CancellableChatOpenAI._generate`（:30-47）在 super 调用前后各 `check_cancelled()`，覆盖 bind_tools 回调路径；`make_chat_model`（:50-57）默认补 `timeout=llm_request_timeout` |
| `src/config.py:36-41` | 新增 `llm_request_timeout=300`、`ws_workflow_hard_timeout=600` |
| `src/websocket/routes.py` | 聊天处理改为后台 task，接收循环持续读套接字（:435-449）；忙时第二条回 `BUSY`；断开/异常/finally 三处 `_cancel_active_handler`（:549-563）；`_invoke_graph`（:520-546）工作线程捕获取消写 `outcome`、打日志并释放条目（断线路径 async 任务已 cancel，日志必须在线程侧）；硬超时连接仍在则发 `WORKFLOW_TIMEOUT`，client_disconnect 静默收卷 |
| 取消信号透传 | `agent.py:210-214` 兜底 except、`nodes.py` intent（:575）/FAQ（:626）/never 直答（:754）/带资料直答（:787）/reflect（:1401）五处 broad except 全部 re-raise `WorkflowCancelled`；评测 Judge 用离线模型，进入前显式 `check_cancelled()`（:1597）；short_term 降级链同样单独 re-raise |
| 构造点替换 | `agent.py`、`graph/nodes.py`（intent/clarify/reflect 4 处）、`fake_llm.py`、`memory/short_term.py` 全部走 `make_chat_model` |
| 测试 | `tests/test_graph/test_cancellation.py` 8 用例（信号/硬超时/代际隔离/to_thread 透传/模型请求前取消/直答不吞取消）；`tests/test_websocket/test_cancel_on_disconnect.py` 3 用例（断开即停且注册表清理、硬超时错误帧、BUSY 并发保护）；test_nodes_llm 3 处打桩从 `ChatOpenAI` 改为 `make_chat_model` |

**上线实测（2026-10-06 15:16 本地，容器 UTC 07:16）**：
1. 断开取消：登录态发 F02 后 20s 关闭 WS（会话 be5f95ca），日志 07:16:23 检测断开、07:16:42 记录「工作流已取消 reason=client_disconnect 耗时=38.8s」（在途直答 LLM 返回后即收卷），容器 CPU 从 203% 回落到 0.11%；PG 该会话只有 user 消息、无 assistant 落库。
2. 正常路径不回归：保持连接的 F02（会话 e7e935c6）124.9s 返回正确分点答案（快门卡滞两次校正/查异物/禁拆卸），3 条 citations；PG 落库 `answer_path=direct_synthesis, kb_call_mode=always, retrieval_count=1`。

**边界**：离线评测 `evaluation/metrics.py`、`pipeline.py` 的 ChatOpenAI 未替换；取消只能在 LLM 调用边界生效，极端卡死在非 LLM 长循环（如检索）由 600s 硬超时兜底。回归 **1517 passed / 17 skipped / 0 failed**（并行 1509 + 串行 kb_phase2 8，净增 11 用例）。回滚标签 `enterprise-agent-app-ollama:backup-pre-ws-cancel-20261006`（旧镜像 113a3526b60e）。实测脚本在 `.smoke_tmp/`（smoke_disconnect.py / smoke_f02.py，勿放 .pytest_tmp，会被 pytest basetemp 清空）。

---

## 2026-10-06 交付：DOC_WEIGHTS 修复 + 技术问答人设收口（已上线）

**上线与复测**：新镜像 `enterprise-agent-app-ollama:latest`（ID 2d7acc147385）已 build + force-recreate，8 容器全绿，回滚标签 `backup-pre-docweights-persona-20261006`（旧镜像 3e1644b182d0）。启动至今日志中 `Invalid doc_weights config` 计数为 0；容器内实测生产 env 五条逗号权重全部解析成功。登录态（smoke_kbmode）WS 复测 F02：**140.7s 返回正确分点答案**，PG metadata `answer_path=direct_synthesis, kb_call_mode=always, retrieval_count=1`，citations 为 T90 维修手册与故障手册，云资源工具零调用（会话 98a62e80-7883-4bc3-877c-9e297aaa9919）。复测脚本 `.pytest_tmp/smoke_ws.py`（登录后 token 走 query 参数）。

**DOC_WEIGHTS 兼容解析**：`.env.production` 长期发逗号简写（`a.md:1.5,b.md:0.8`），旧解析器只认 JSON，权重静默失效、日志反复 `Invalid doc_weights config, ignored`。`src/rag/retriever.py:147-197` 新增 `_parse_doc_weights`，先试 JSON dict 失败回落逗号解析（`rpartition(":")`、容忍空白/尾逗号、权重 clamp 0.5~2.0）；任一非空条目非法整份返回 None 原子失效，防半份配置静默生效；`:199` 起 `_get_doc_weights_map` 调用新解析，缓存逻辑不变。`src/config.py:89-100` 与 `deploy/prod/.env.production.example:40-43` 注释补双格式与整份失效语义，默认值未动。`tests/test_rag/test_retriever_weights.py` 共 15 用例。

**人设收口（只改 src/ 内用户可见文案）**：

| 文件 | 改动 |
|---|---|
| `src/agent/prompt.py:12-39` | ReAct 人设重写为工业设备技术支持；规则 1 故障/代码/参数必须先检索且保留数字与安全警示；规则 5（:33）云资源工具仅在用户明确查自己云资源时使用，设备问题禁止调用（F02 误路由根因） |
| `src/agent/tools.py:13-34` | `_FAQ_STORE` 从 14 条收到 4 条（问候/感谢/再见/重置密码，重置密码为既有测试依赖）；删除套餐、退订、API Key、403、SSO、加密、2FA、同步失败、定价、千问模型共 10 条 SaaS canned 答案 |
| `src/agent/tools.py:813-821,893-901` | search_knowledge_base / search_faq 工具描述去 SaaS 化，给 7B 正确路由锚点 |
| `src/graph/nodes.py` | faq 兜底 prompt（:608）、clarify 示例（:219-226）、配置类产品词表与追问标签（:374-383）、四处兜底文案（:1468-1551）、直答提示词规则 5（:663）全部去 CloudSync |
| `tests/test_agent/test_persona.py` | 新增 6 用例：人设中性化、云资源工具边界、直答无品牌、FAQ 保留/删除边界 |

**明确不改的边界**：A2A 协议 agents（`src/protocols/`，独立协议服务）、`src/safety/sanitizer.py` URL 白名单、`data/docs/*.md` 旧语料、helm/chatwoot/`src/mcp_tools/cloud_provider.py` 域名账号、云资源工具本身（`agent.py:49-50` 仍绑定，靠提示词规则 5 约束路由）。`tests/test_graph_nodes_helpers.py:77` 追问标签断言随设计变更同步更新；拒答正则用例里的 CloudSync 字样与正则匹配逻辑无关，未动。

**回归**：全量 **1506 passed / 17 skipped / 0 failed**（并行 1498 + 串行 kb_phase2 8）。

**顺带修复（同日二次上线）**：`src/api/config_center.py:23`、`src/config_center/service.py:26`、`src/config_center/audit.py:17` 使用 Python 3.11 才有的 `from datetime import UTC`，容器运行时 3.10，config_center 路由每次启动 ImportError 被 try/except 吞掉、36 个接口静默 404（本地 3.14 测试全绿，版本盲区）。三处统一改 `timezone.utc`；`tests/test_api/test_app_wiring.py` 新增 `test_no_py311_only_stdlib_imports` 静态扫描守卫（禁 `datetime.UTC` / `tomllib`，容忍 BOM 文件）。修复后镜像 `113a3526b60e`，启动日志 `Registered config_center router`，`GET /api/v1/config/hot-categories` 实测 401（修复前 404）。回滚标签 `backup-pre-utc-fix-20261006`。

---

## 2026-10-06 交付：语料归档 + 索引重建 + RRF 权重排序修复（镜像 082f2147dcd2）

**背景**：DOC_WEIGHTS 解析与人设收口上线后，全量重建索引导致 F02 直答闸门失效（top_sim 0.345 < 0.35 退回 ReAct，WS 400s 超时）。逐段埋点定位到根因在 RRF 融合，与阈值标定无关。

**语料与索引**：

| 项 | 实测 |
|---|---|
| 归档 | 13 个英文 SaaS 文档（共 117 处 CloudSync）移至 `data/legacy_saas_docs/`，`data/docs/` 现为 9 个工业文件（7 md + 2 pdf，T90/T100 PDF 归位） |
| PDF loader | `src/rag/loaders/pdf_loader.py` 修复 close 先于书签提取导致全部 PDF「document closed」静默失败的真 bug，书签提取移到 close 前，回归测试 `tests/test_rag/test_pdf_loader.py` |
| 重建入口 | `scripts/rebuild_index.py`（幂等，`--yes/--persist-dir/--docs-dir`，先加载切块保护旧索引，drop 标准+句子两集合后重灌并对账，仅 Chroma） |
| 卷重建结果 | 标准集合 328→164（4 个幽灵 kb_md/txt/docx/pdf 全清），句子集合 0→1014（旧生产句子集合一直为空，句子级检索此前从未生效） |
| 备份与种子 | 卷冷备份 `.smoke_tmp/backups/chroma_pre_rebuild_20261006.tar.gz`（2.9MB），干净种子导出覆盖仓库 `chroma_data/`；语料清理回滚标签 `backup-pre-corpus-cleanup-20261006`（9b73a735bb93） |

**RRF 权重排序真 bug（本次核心）**：`_rrf_fusion` 原实现把 doc/kb 权重直接乘进 RRF 分（retriever.py:683-694 旧逻辑）。RRF 相邻 rank 分差极窄（rank0=1/61 与 rank5=1/66 仅差 8%），fault_manual 的 1.5x 权重等价于把单个 chunk 提前约 20 个 rank 位。F02 实测向量通道 T90 PDF 0.553 排第一，被 5 个 1.5x 的 fault 低相关 chunk（0.31x）集体反超挤出 top5，rerank 无正确候选，来源配额 cap=2 再砍成 2 条，top_sim 掉到 0.338。修法对齐函数 docstring「相同 RRF 分数时权重高者优先」的原始意图：裸 RRF 累积分为唯一排序主键，权重仅在裸分完全相同时做平局裁决（retriever.py:701-706，key=(scores[x], weights[x])）；多通道命中累积的语义保持不变。测试改为 `test_bare_rank_beats_weight_in_rrf`（rank0 低权重必须压过 rank1 高权重）与 `test_weight_tiebreak_on_equal_rrf`（同分高权重胜），`tests/test_rag/test_retriever_weights.py` 现 16 用例。

**修复后实测分布（容器内真实 HybridRetriever，12 题）**：强相关 7 题区间 0.467~0.687（F02 0.553、F01 0.526、快门卡滞 0.467），弱相关 5 题区间 0.000~0.300（天气 0.300 为最高噪声，API key 0.226、SSO 0.273）。强弱间隔 0.167，**直答阈值维持 0.35 不变**，降阈值反而会放进天气类噪声。F02 逐段追踪：T90 PDF rerank 分 0.987 排第一，5 条候选全部保留到最终结果。

**上线验证**：镜像 `enterprise-agent-app-ollama:082f2147dcd2` build + 带 `--env-file` force-recreate（漏传 env-file 曾重建出无环境变量容器，已立即纠正），healthy 后卷计数 164/1014 不变。WS smoke（会话 bf9ca8b5）**198.0s** 返回「F02 表示快门卡滞：维护菜单两次快门校正/查异物/严禁拆卸」，5 条 citations；PG `answer_path=direct_synthesis, retrieval_count=1`。本地串行全量回归 0 failed（并行 xdist 有 metrics 懒注册/多模态等顺序抖动，与本次改动无关，隔离或串行均通过）。回滚路径：镜像用 `backup-pre-corpus-cleanup-20261006`（9b73a735bb93），RRF 单点可直接回退 retriever.py，卷用 tar 冷备份恢复。重建容器后 /tmp 临时文件与 /app 诊断脚本已随旧容器清除，rebuild_index.py 已烤入镜像。

---

## 2026-10-05 交付回顾：kb_call_mode 语义收口（已上线）

三模式（always/smart/never）接入 rag_node；检索侧 `src/rag/retriever.py` 在阈值过滤前盖 `vector_similarity` 绝对信号；三要素 `kb_call_mode / retrieval_decided_by / retrieval_count` 沿 WS 落库 PG（会话 `305c9f48-5097-4f70-aa5c-4aa4845823cd` 实测）。回归 1481 passed。新镜像 4.48GB（2026-10-05 19:05），回滚标签 `enterprise-agent-app-ollama:backup-pre-kb-callmode-20261005`。

### 10-05 排掉的 5 个部署雷（重建时必读）

1. GPU `devices` 必须在 `deploy.resources.reservations.devices`，放 resources 下 Compose v5.5.1 拒收整个文件。
2. app 启动逻辑在 `scripts/start-app.sh`（WSL 驱动挂接 + ollama + 就绪探针 + exec uvicorn），compose 只写 `command: ["/app/scripts/start-app.sh"]`；v5.5.1 下 `$$` 不还原为 `$`，内联 shell 变量不可靠。
3. 根 Dockerfile 是四阶段，ollama 从 `FROM enterprise-agent-app-ollama:latest AS ollama-src` 提取；legacy 文件可取回 `git show a07d7d2:Dockerfile`。
4. `.dockerignore` 不得排除 `static`、`chroma_data`（都是必烤资产）。
5. redis `command: >` 折叠块内禁止 `#` 注释（会折进命令行变 redis-server 参数导致 FATAL），注释放块外。

---

## 待办与遗留观察

| # | 项 | 性质 |
|---|---|---|
| 1 | 直答阈值 0.35 经索引重建后 12 题分布重新验证（强 ≥0.467 / 弱 ≤0.300），维持不变；上线后按 PG 中 direct/react 占比与人工抽检继续观察；复杂多步排查题仍可能走 ReAct | 观察项 |
| 2 | 匿名 WS 会话被租户隔离过滤成预检索 0 条（日志 `Permission filter: 5 → 0 tenant=anon-*`），直答旁路无资料可用必然回落，7B 易误调 query_resources 后兜底拒答；登录态正常。产品需决策匿名会话可见的文档范围，或前端强制登录 | 待决策（复测中发现，既有行为） |
| 3 | config_center UTC 兼容已修复并上线（镜像 113a3526b60e，含静态守卫防复发）；其余 3.11+ 语法排查暂无 | 已完成 |
| 4 | WS 断开后工作流空跑：协作式取消已上线（镜像 9b73a735bb93），实测断开 38.8s 收卷、CPU 203%→0.11%、PG 不脏落库；F02 正常路径 124.9s 不回归 | 已完成 |
| 5 | `data/docs/` 语料侧 13 个 SaaS 文档已归档并重建索引（镜像 082f2147dcd2）；A2A agents、sanitizer 白名单、helm/chatwoot 域名账号仍有 CloudSync 字样，维持边界不动 | 语料已完成，协议侧划边界 |
| 6 | ollama 为 CPU-only 构建（无 CUDA 后端，`total_vram="0 B"`）；直答已把单题压到 2 分钟级，进一步提速需换 CUDA 构建；`static/` 仍是 09-17 产物；A2A 探针 connection failed 仅告警 | 成本/低优 |
| 7 | 金标题库 reply 截断修复真机闭环：50 题 36/50 pass（详见 10-08 凌晨收口节），拒答 5/5、零安全失败，commit 已 push、CI 37657800312 五 job 全绿，修复已固化镜像 8835fc74b155、8 容器全绿。剩余：①14 fail = 11 题 7B 生成要点不全 + 2 题检索（GF15/GF20）+ 1 题判分维持（GF02），质量项列阶段 2；②题库 meta.frozen 待用户逐题冻结（阶段 1 唯一硬门） | 阶段 1 收尾中 |

---

## 上线命令与索引

```powershell
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production build app
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app
```

技术方案见 `docs/Phase5-kb_call_mode语义收口-拆解方案.md`；完整任务清单见 `docs/Phase5-后续待完善任务清单.md`。
热验证脚本在本机 `.pytest_tmp/verify_direct.py`（容器内副本已清理）。

## 更新规则

- 完成一个阶段 → 覆盖对应区块
- 阻塞解除 → 记入对应日志区块
- 行号引用必须实测复核，代码一改行号就漂移
- 本文件控制在 240 行以内，详细证据链放 docs/ 与阶段验收报告
