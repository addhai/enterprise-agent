# API 分页与版本管理

## API 分页

### 分页方式

CloudSync API 使用游标分页（Cursor-based Pagination），适用于所有列表端点：

```
GET /api/v1/sync/jobs?cursor=abc123&limit=20
```

| 参数 | 说明 | 默认值 | 最大值 |
|------|------|--------|--------|
| `limit` | 每页返回数量 | 20 | 100 |
| `cursor` | 上一页返回的 `next_cursor` | 无 | 无 |
| `sort` | 排序字段 | `created_at` | `created_at`, `status`, `name` |
| `order` | 排序方向 | `desc` | `asc`, `desc` |

### 响应格式

```json
{
  "data": [
    {
      "id": "job_123",
      "name": "Dropbox to OneDrive",
      "status": "completed",
      "created_at": "2026-07-01T10:30:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6ImpvYl8xMjMiLCJjcmVhdGVkX2F0IjoiMjAyNi0wNy0wMSJ9",
    "prev_cursor": "eyJpZCI6ImpvYl8xMDAiLCJjcmVhdGVkX2F0IjoiMjAyNi0wNi0zMCJ9",
    "has_more": true,
    "total_count": 150
  }
}
```

### 分页最佳实践

```python
from cloudsync import CloudSyncClient

client = CloudSyncClient(api_key="cs_live_xxx")

# 方式 1: 手动分页
cursor = None
all_jobs = []

while True:
    response = client.sync.list_jobs(cursor=cursor, limit=50)
    all_jobs.extend(response["data"])
    
    if not response["pagination"]["has_more"]:
        break
    cursor = response["pagination"]["next_cursor"]

# 方式 2: 使用分页迭代器
for job in client.sync.list_jobs_paginated(limit=50):
    print(job["name"])
```

### 注意事项

- **游标不可重复使用** — 游标只在短时间内有效（约 1 小时）
- **不要依赖分页顺序** — 排序可能随时间变化
- **避免全量拉取** — 使用 `limit=100` 减少请求次数
- **处理空结果** — 返回 `{"data": [], "pagination": {"has_more": false}}`

## API 版本管理

### 版本策略

CloudSync 采用 URI 版本控制，所有 API 请求必须指定版本：

```
https://api.cloudsync.io/v3/sync/jobs    # v3 API
https://api.cloudsync.io/v2/sync/jobs    # v2 API（已废弃）
```

### 当前版本

| 版本 | 状态 | 发布日期 | 废弃日期 | 说明 |
|------|------|---------|---------|------|
| v3 | **当前** | 2025-01-01 | — | 当前推荐版本 |
| v2 | 已废弃 | 2023-06-01 | 2025-12-31 | 已停止维护 |
| v1 | 已废弃 | 2021-01-01 | 2024-06-30 | 已下线 |

### v3 变更摘要

与 v2 相比的主要变更：

| 变更 | v2 | v3 | 影响 |
|------|----|----|------|
| 认证方式 | `X-API-Key` header | `Authorization: Bearer <key>` | 需修改所有请求 |
| 错误码格式 | `{ "error": "message" }` | `{ "error": { "code": 403, "message": "..." } }` | 需适配错误处理 |
| 分页方式 | Offset-based | Cursor-based | 需修改分页逻辑 |
| 速率限制 | 全局 100 req/min | 按端点 50-1000 req/min | 需调整限流策略 |
| 响应头 | 无速率限制头 | `X-RateLimit-Remaining` | 可添加自适应退避 |

### 迁移指南（v2 → v3）

#### 1. 更新认证方式

```python
# v2（旧）
headers = {"X-API-Key": "cs_live_xxx"}

# v3（新）
headers = {"Authorization": "Bearer cs_live_xxx"}
```

#### 2. 更新分页逻辑

```python
# v2（旧）
response = client.get("/sync/jobs?offset=0&limit=20")
next_offset = offset + 20

# v3（新）
response = client.get("/sync/jobs?limit=20&cursor=abc123")
next_cursor = response["pagination"]["next_cursor"]
```

#### 3. 更新错误处理

```python
# v2（旧）
if response.status_code == 403:
    error_msg = response.json()["error"]

# v3（新）
if response.status_code == 403:
    error_data = response.json()["error"]
    error_code = error_data["code"]
    error_msg = error_data["message"]
```

### 版本兼容性

- **向前兼容** — v3 API 保证向后兼容至少 12 个月
- **弃用通知** — 废弃 API 前至少提前 6 个月通知
- **废弃端点** — 废弃端点会继续返回数据，但不再接收 bug 修复
- **迁移工具** — 提供 `cloudsync-migrate` CLI 工具自动转换 v2 → v3

```bash
pip install cloudsync-migrate
cloudsync-migrate --from v2 --to v3 --input my_script.py --output my_script_v3.py
```

### 版本回退

如果 v3 出现严重问题，可以临时回退到 v2：

```bash
# 设置环境变量
export CLOUDSYNC_API_VERSION=v2
```

回退通道仅在重大故障时开放，通常不超过 48 小时。

## 常见问题

**Q: 如何确定当前使用的 API 版本？**
A: 查看请求 URL 中的版本号，或检查响应头 `X-API-Version`。

**Q: v2 API 何时完全下线？**
A: v2 API 将于 2025-12-31 完全下线，届时所有 v2 请求将返回 410 Gone。

**Q: 如何获取 API 变更日志？**
A: 访问 https://developers.cloudsync.io/changelog 查看完整变更记录。

**Q: 新版本发布后多久支持？**
A: 新 API 版本发布后 30 天内，旧版本将继续可用。
