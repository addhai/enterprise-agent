# P2-3 接口测试 README

## 测试文件

`tests/test_api/test_api_reference.py` — 覆盖 5 个核心接口的 32 个测试用例。

## 执行命令

```bash
# 全量运行（含 requires_llm 用例自动跳过）
python -m pytest tests/test_api/test_api_reference.py -v

# 只看通过/失败摘要
python -m pytest tests/test_api/test_api_reference.py -o addopts="" -q

# 运行真实 LLM 路径（需配置 API Key）
RUN_LLM_TESTS=1 python -m pytest tests/test_api/test_api_reference.py -v

# 跳过整个文件
python -m pytest tests/ --ignore=tests/test_api/test_api_reference.py
```

预期输出（无 LLM Key 环境）：
```
26 passed, 6 skipped in ~20s
```

6 个 skipped 是 `requires_llm` 标记的用例（对话发起、文档向量化、对话后读取消息），需要真实 LLM/Embedding 凭据。设置 `RUN_LLM_TESTS=1` 后恢复运行。

## 查看测试覆盖率

```bash
# 单文件覆盖率
python -m pytest tests/test_api/test_api_reference.py \
  --cov=src/api/routes \
  --cov=src/api/conversations \
  --cov=src/api/knowledge \
  --cov=src/api/admin \
  --cov-report=term-missing

# 全量覆盖率（与 CI 一致）
python -m pytest tests/ --cov=src --cov-report=term-missing --cov-report=xml
```

覆盖率报告产出 `coverage.xml`，终端表格展示每行命中情况。

## 测试矩阵

| 接口 | 正常调用 | 参数缺失 | 非法参数 | 边界 case | 权限控制 |
|---|---|---|---|---|---|
| POST /chat | 2 (LLM) | 1 | 3 | 0 | 0 |
| GET /conversations/{id}/messages | 1 (LLM) | 0 | 2 | 2 | 1 |
| POST /knowledge/{id}/documents/upload | 2 (LLM) | 1 | 0 | 0 | 2 |
| POST /knowledge/{id}/hit_test | 1 | 1 | 3 | 3 | 2 |
| DELETE /sessions/{id} | 1 (LLM) | 0 | 0 | 0 | 3 |

## Fixtures

| fixture | scope | 说明 |
|---|---|---|
| `client` | function | FastAPI TestClient，内存 SQLite |
| `admin_token` | function | admin 角色 JWT（seed 预置 admin/admin123） |
| `viewer_token` | function | viewer 角色 JWT（权限不足断言用） |
| `agent_token` | function | agent 角色 JWT（可能不存在则 skip） |
| `temp_kb` | function | 临时知识库，yield kb_id，测试后自动删除 |
