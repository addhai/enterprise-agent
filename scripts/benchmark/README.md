# P2-5 性能基准脚本

## 文件清单

| 文件 | 覆盖项 | 说明 |
|---|---|---|
| `bench_chat_concurrency.py` | B1 | REST /chat 并发压测（10/50/100 并发，P50/P95/P99 + QPS） |
| `bench_rag_recall.py` | B3 | RAG hit_test 召回耗时（空库/10文档/100文档三档） |
| `bench_upload_pipeline.py` | B4 | 文件上传→向量化→可检索 端到端耗时 |

> B2（WebSocket 首 token 延迟 + 流式断连率）需 WebSocket 客户端，
> 用 `websockets` 库编写，需 `pip install websockets`，此处不预装。

## 前置条件

```bash
# 启动服务（P2-4 部署）
bash deploy/p2/scripts/start.sh

# 确认健康
curl http://localhost:8000/api/v1/health
# {"status":"ok"}
```

## 执行

```bash
# B1: REST /chat 并发（mock 模式，不触 LLM）
python scripts/benchmark/bench_chat_concurrency.py --mock

# B1: REST /chat 并发（真实 LLM，需 API Key）
python scripts/benchmark/bench_chat_concurrency.py --levels 10,50,100

# B3: RAG hit_test 召回（mock 模式，空库）
python scripts/benchmark/bench_rag_recall.py --mock

# B4: 上传→向量化→检索 端到端
python scripts/benchmark/bench_upload_pipeline.py
```

## 输出格式

每个脚本输出：
1. 标准表格（终端可读）
2. JSON 原始数据（可复制到 `docs/PERFORMANCE_BASELINE.md` 填表）

## 无 LLM Key 环境说明

- `--mock` 模式只测框架开销（请求接收→路由→参数校验→错误返回），不触发 LLM 调用
- 上传基准（B4）在无 Embedding API Key 时，上传步骤会失败（向量化阶段），
  脚本会输出失败行并退出，不等同于脚本崩溃
- 真实基准数据需在有 API Key 的环境中运行后填入 `PERFORMANCE_BASELINE.md`
