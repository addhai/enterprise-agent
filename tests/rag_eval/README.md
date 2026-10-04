# RAG 评估体系使用说明

## 目录结构

```
tests/rag_eval/
  eval_dataset.jsonl    评估问答对（35 条，5 种类型）
  eval_recall.py        召回率评估脚本
  eval_answer.py        回答质量评估脚本
  __init__.py
  README.md             本文件
```

## 评估集格式

每条 JSONL 记录包含：

```json
{
  "id": "f01",
  "type": "fact",
  "question": "测温仪的测温范围是多少？",
  "expected_doc": "product_spec_manual.md",
  "expected_keywords": ["-20", "550"]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 唯一 ID |
| `type` | string | fact / fault / operation / parameter / unknown |
| `question` | string | 用户真实问法 |
| `expected_doc` | string? | 应命中的源文档文件名（unknown 类为 null） |
| `expected_keywords` | string[] | 答案必须包含的关键事实/数值 |

## 新增评估项

1. 在 `eval_dataset.jsonl` 追加一行 JSON
2. 从 7 篇文档中确认 `expected_doc` 和 `expected_keywords` 真实存在
3. 覆盖新的问题类型时在 `type` 字段标注

## 运行评估

### 召回率（BM25 直接模式，无需服务）

```bash
python tests/rag_eval/eval_recall.py --direct --top-k 5
```

输出示例：
```
        类型 |   总数 |  Hit@1 |  Hit@3 |  Hit@5 |    MRR
--------------------------------------------------------
      fact |   12 |  50.0% |  91.7% | 100.0% |  0.711
     fault |    7 |  28.6% |  42.9% |  57.1% |  0.362
 operation |    7 |  42.9% |  85.7% |  85.7% |  0.643
 parameter |    7 |  14.3% |  85.7% | 100.0% |  0.512
--------------------------------------------------------
       ALL |   33 |  36.4% |  78.8% |  87.9% |   0.58
```

### 召回率（进程内模式，需初始化）

```bash
python tests/rag_eval/eval_recall.py --in-process --top-k 5
```

### 召回率（HTTP 模式，需运行中的服务）

```bash
# 先启动服务
bash deploy/p2/scripts/start.sh

# 评估
python tests/rag_eval/eval_recall.py --base-url http://localhost:8000 --top-k 5
```

### 回答质量（mock 模式）

```bash
python tests/rag_eval/eval_answer.py --in-process
```

## 指标说明

| 指标 | 计算方式 | 理想值 |
|---|---|---|
| Hit@1 | 期望文档排第 1 的比例 | > 50% |
| Hit@3 | 期望文档排前 3 的比例 | > 80% |
| Hit@5 | 期望文档排前 5 的比例 | > 90% |
| MRR | 平均倒数排名 (1/rank) | > 0.7 |
| 关键词命中率 | expected_keywords 在上下文中的出现率 | > 90% |
| 引用准确率 | 检索结果包含期望文档的比例 | > 90% |
| 幻觉率 | 100% - 关键词命中率 | < 10% |
| 未收录准确率 | 未收录类正确返回零命中的比例 | > 90% |

## 当前评估结果

见 `docs/RAG_QUALITY_REPORT.md`。
