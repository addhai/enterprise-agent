# 性能基准报告（P2-5）

> 4 项基准测试，含环境说明、数据表、瓶颈分析。无 LLM Key 的项用 mock/框架开销替代，标注清楚。
>
> 测试环境：Windows 11, Python 3.10, FastAPI TestClient（进程内调用，无网络开销）
> 生产环境数据需用 `scripts/benchmark/` 脚本对运行中的服务实测后填入。
>
> 测试日期：2026-09-12

---

## 测试环境

| 项 | 值 |
|---|---|
| 操作系统 | Windows 11 (win32) |
| Python | 3.10 (venv) |
| 测试方式 | FastAPI TestClient（进程内，零网络开销） |
| 数据库 | SQLite :memory:（conftest.py 自动初始化） |
| 向量库 | Chroma（本地持久化） |
| LLM | 未配置（无 API Key） |
| CPU | (未采集) |
| 内存 | (未采集) |

> **重要**：TestClient 是进程内调用，延迟不含 TCP/序列化开销。生产环境实际延迟
> 会更高（典型 + 2-5ms 网络开销）。以下数据是**框架开销下限**，用于回归对比。

---

## B1：REST /chat 并发

### 方法

用 TestClient 发送超长 message（5001 字符）触发 422 路径，测纯框架开销（路由→Pydantic 校验→错误返回）。
真实 LLM 路径需用 `scripts/benchmark/bench_chat_concurrency.py` 对运行中的服务实测。

### 数据

| 并发数 | 请求数 | P50(ms) | P95(ms) | P99(ms) | QPS | 成功率 |
|---|---|---|---|---|---|---|
| 1 | 50 | 2.6 | 3.2 | 4.1 | ~380 | 100% |
| 10 | 50 | 2.7 | 3.3 | 4.5 | ~370 | 100% |
| 50 | 50 | 2.8 | 3.5 | 5.0 | ~360 | 100% |

> 注：422 路径不触发 LangGraph / LLM，只反映 FastAPI 路由 + Pydantic 校验开销。
> 200 路径（真实对话）的延迟由 LLM 推理时间主导（典型 2-10s），框架开销可忽略。

### 真实 LLM 路径预估

| 并发数 | 预估 P50 | 预估 P95 | 瓶颈 |
|---|---|---|---|
| 10 | 2-5s | 5-8s | LLM 推理（单 worker 串行） |
| 50 | 5-15s | 15-30s | LLM 速率限制 + 连接队列 |
| 100 | 10-30s | 30-60s | LLM 速率限制 + 内存 |

**瓶颈分析**：当前 `uvicorn --workers 1`，单 worker 串行处理请求。并发请求会排队。
生产环境应 `--workers N`（N = CPU 核数）或用 docker-compose replicas 水平扩展。

### 生产环境复现

```bash
# 启动服务后
python scripts/benchmark/bench_chat_concurrency.py --levels 10,50,100 --total 100
```

---

## B2：WebSocket 首 token 延迟 + 流式断连率

### 方法

需 WebSocket 客户端（`websockets` 库）。当前环境未安装该库，此项为**待实测**。
源码分析：`src/websocket/routes.py` 的 `websocket_chat` 端点在接收 `chat_message` 后
触发 LangGraph，通过 `build_streaming_chunk` 逐段推送。

### 预估数据（基于源码分析）

| 指标 | 预估值 | 说明 |
|---|---|---|
| 首 token 延迟 | 500ms-3s | 取决于 LangGraph 第一个节点（意图分类）执行时间 |
| 流式断连率 | < 0.1% | 基于 WebSocket 心跳保活机制（15s 间隔） |
| 单轮完整延迟 | 2-10s | 取决于 LLM 响应 + RAG 检索 |

**瓶颈分析**：首 token 延迟由「LangGraph 入口节点 + RAG 检索 + LLM 首次调用」串联决定。
可优化点：RAG 检索可预热（启动时加载索引到内存），LLM 调用可流式（已有 `streaming_chunk`）。

### 待实测

```bash
# 需安装 websockets 库
pip install websockets

# 运行后填入实际数据
python -c "
import asyncio, json, websockets, time
async def bench():
    async with websockets.connect('ws://localhost:8000/ws/chat') as ws:
        await ws.recv()  # session_ready
        t0 = time.perf_counter()
        await ws.send(json.dumps({'type': 'chat_message', 'message': '你好'}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get('type') == 'streaming_chunk' and msg.get('text'):
                print(f'First token: {(time.perf_counter()-t0)*1000:.0f}ms')
                break
asyncio.run(bench())
"
```

### P4-1 补充数据（TestClient 框架开销，模拟模式）

> Docker 未运行，以下为 TestClient 进程内测量，标注"模拟数据，LLM 生成延迟待生产实测"。

| 指标 | P50(ms) | P95(ms) | 说明 |
|---|---|---|---|
| WebSocket 框架开销（chat 422 代理） | 2.7 | 8.8 | 无 LLM 调用，纯框架开销 |
| 上传框架开销（不含向量化） | 220.8 | 337.3 | 文件保存 + 入库元数据写入 |
| hit_test 框架开销 | 234.0 | 2260.1 | 冷启动 2.3s，稳态 234ms |
| 上传+hit_test 合计 | 469.7 | N/A | 端到端框架开销（不含向量化） |

**B2 首 token 延迟预估**：
- 框架开销 2.7ms + LangGraph 入口节点 50-200ms + RAG 检索 7-234ms + LLM 首 token 500-3000ms
- 预估首 token 延迟：600ms - 3.5s
- LLM 生成延迟待生产环境实测

**B4 端到端预估**：
- 框架开销 469.7ms + 向量化 500-2000ms（Embedding API 调用）
- 预估端到端：1-3s（1KB 文档，~5 chunks）

---

## B3：RAG hit_test 召回耗时

### 方法

用 TestClient 对空知识库执行 hit_test，测检索框架开销（不含真实向量化）。
20 次请求取统计值。

### 数据

| 档位 | 平均(ms) | P50(ms) | P95(ms) | 说明 |
|---|---|---|---|---|
| 空库 | 66.5 | 7.2 | 1187.8 | 首次调用初始化检索器（冷启动），后续稳定 7ms |
| 10 文档 | 待实测 | 待实测 | 待实测 | 需上传文档并等待向量化 |
| 100 文档 | 待实测 | 待实测 | 待实测 | 需上传文档并等待向量化 |

> P95=1187.8ms 是首次调用的冷启动（检索器初始化 + Chroma 加载）。
> 排除首次后，P50=7.2ms 是稳态检索延迟。

### 辅助基准

| 接口 | P50(ms) | P95(ms) | avg(ms) | 说明 |
|---|---|---|---|---|
| GET /api/v1/health | 2.411 | 3.039 | 2.456 | 纯路由开销 |
| POST /api/v1/auth/login | 209.6 | 214.1 | 209.9 | bcrypt 哈希（CPU 密集） |
| POST /api/v1/chat (422) | 2.6 | 3.2 | 2.7 | Pydantic 校验开销 |

**瓶颈分析**：
- `auth/login` 的 210ms 来自 bcrypt 密码哈希（设计如此，防暴力破解）。可缓存 token 避免重复登录。
- `hit_test` 空库的冷启动 1188ms 来自 Chroma 首次加载。生产环境建议启动时预热检索器。
- `health` 和 `chat_422` 在 3ms 以内，框架开销可忽略。

### 生产环境复现

```bash
# 空库（mock 模式）
python scripts/benchmark/bench_rag_recall.py --mock

# 真实库（需先上传文档）
python scripts/benchmark/bench_rag_recall.py --rounds 50
```

---

## B4：文件上传→向量化→可检索 端到端

### 方法

需运行中的服务 + Embedding API Key。当前环境无 Key，此项为**待实测**。
源码分析：上传→保存文件→_ingest_document_internal（加载→切块→向量化→入库）→hit_test 可检索。

### 预估数据（基于源码分析）

| 步骤 | 预估耗时 | 瓶颈 |
|---|---|---|
| 创建知识库 | 5-15ms | SQLite 写入 |
| 上传文档（1KB .md） | 50-200ms | 文件保存 + 文档加载 |
| 向量化（1KB → ~5 chunks） | 500-2000ms | Embedding API 调用（网络 + 模型推理） |
| hit_test 可检索 | 10-30ms | Chroma 检索 |
| **端到端总计** | **600-2200ms** | 向量化是主要瓶颈 |

**瓶颈分析**：向量化步骤占端到端耗时的 70%+，受 Embedding API 响应时间主导。
优化方向：批量向量化（减少 API 调用次数）、本地 Embedding 模型（消除网络延迟）、异步入库。

### 待实测

```bash
# 需运行中的服务 + API Key
python scripts/benchmark/bench_upload_pipeline.py --base-url http://localhost:8000
```

---

## 总结与瓶颈优先级

| 优先级 | 瓶颈 | 影响 | 优化方向 |
|---|---|---|---|
| P0 | uvicorn 单 worker 串行 | 高并发时请求排队 | `--workers N` 或 replicas 扩展 |
| P0 | hit_test 冷启动 1.2s | 首次检索体验差 | 启动时预热检索器 |
| P1 | 向量化占端到端 70%+ | 上传→可检索延迟高 | 批量向量化 / 本地模型 |
| P1 | bcrypt 登录 210ms | 频繁登录体验差 | token 缓存 + 前端记住登录态 |
| P2 | 500 detail 含异常信息 | 安全风险 | 生产环境通用错误消息 |

---

## 脚本清单

| 脚本 | 覆盖项 | 用法 |
|---|---|---|
| `scripts/benchmark/bench_chat_concurrency.py` | B1 | `python scripts/benchmark/bench_chat_concurrency.py --mock` |
| `scripts/benchmark/bench_rag_recall.py` | B3 | `python scripts/benchmark/bench_rag_recall.py --mock` |
| `scripts/benchmark/bench_upload_pipeline.py` | B4 | `python scripts/benchmark/bench_upload_pipeline.py` |
| `scripts/benchmark/README.md` | 全部 | 使用说明 |
