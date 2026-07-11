# SDK 安装与配置指南

## 支持的 SDK

| 语言 | 包名 | 最新版本 | 安装命令 |
|------|------|---------|---------|
| Python | `cloudsync` | 3.2.1 | `pip install cloudsync` |
| JavaScript | `@cloudsync/sdk` | 3.2.0 | `npm install @cloudsync/sdk` |
| Java | `io.cloudsync:cloudsync-sdk` | 3.2.1 | Maven/Gradle |
| Go | `github.com/cloudsync/go-sdk` | 3.1.0 | `go get github.com/cloudsync/go-sdk` |

## Python SDK 快速开始

### 1. 安装

```bash
pip install cloudsync
```

### 2. 初始化客户端

```python
from cloudsync import CloudSyncClient

# 方式 1: 使用 API Key
client = CloudSyncClient(api_key="cs_live_xxxxxxxxxxxxxxxx")

# 方式 2: 使用 OAuth Token
client = CloudSyncClient(access_token="eyJhbGciOiJSUzI1NiIs...")
```

### 3. 基本操作

```python
# 列出所有同步任务
jobs = client.sync.list_jobs()

# 创建新的同步任务
job = client.sync.create_job(
    source="Dropbox",
    target="OneDrive",
    folder="/Documents",
    schedule="daily"
)

# 获取同步状态
status = client.sync.get_status(job.id)
print(f"Progress: {status.progress}%")

# 取消同步任务
client.sync.cancel(job.id)
```

### 4. 错误处理

```python
from cloudsync.exceptions import (
    CloudSyncError,
    AuthenticationError,
    RateLimitError,
    NotFoundError,
)

try:
    client.sync.create_job(source="Dropbox", target="OneDrive")
except AuthenticationError as e:
    print(f"认证失败: {e}")
except RateLimitError as e:
    print(f"请求过于频繁，请稍后重试")
except NotFoundError as e:
    print(f"资源不存在: {e}")
except CloudSyncError as e:
    print(f"未知错误: {e}")
```

## JavaScript SDK 快速开始

### 1. 安装

```bash
npm install @cloudsync/sdk
```

### 2. 初始化

```javascript
import { CloudSyncClient } from '@cloudsync/sdk';

const client = new CloudSyncClient({
    apiKey: 'cs_live_xxxxxxxxxxxxxxxx',
    timeout: 30000,
});
```

### 3. 基本操作

```javascript
// 列出同步任务
const jobs = await client.sync.listJobs();

// 创建同步任务
const job = await client.sync.createJob({
    source: 'Dropbox',
    target: 'OneDrive',
    folder: '/Documents',
});

// 监听事件
client.on('sync.completed', (data) => {
    console.log(`同步完成: ${data.jobId}`);
});

client.on('sync.failed', (data) => {
    console.error(`同步失败: ${data.error}`);
});
```

## Java SDK 快速开始

### 1. Maven 依赖

```xml
<dependency>
    <groupId>io.cloudsync</groupId>
    <artifactId>cloudsync-sdk</artifactId>
    <version>3.2.1</version>
</dependency>
```

### 2. 初始化

```java
import io.cloudsync.CloudSyncClient;

CloudSyncClient client = new CloudSyncClient.Builder()
    .apiKey("cs_live_xxxxxxxxxxxxxxxx")
    .timeout(30000)
    .build();
```

## Go SDK 快速开始

### 1. 安装

```bash
go get github.com/cloudsync/go-sdk
```

### 2. 初始化

```go
import "github.com/cloudsync/go-sdk"

client := cloudsync.NewClient(cloudsync.Config{
    APIKey: "cs_live_xxxxxxxxxxxxxxxx",
    Timeout: 30 * time.Second,
})
```

## 版本兼容性

| SDK 版本 | 最低 API 版本 | 支持的平台 | 废弃日期 |
|---------|-------------|-----------|---------|
| 3.x | v3.0 | Python 3.8+, Node 16+, Java 11+, Go 1.20+ | 无 |
| 2.x | v2.0 | Python 3.6+, Node 14+ | 2025-12-31 |
| 1.x | v1.0 | Python 3.5+ | 2024-06-30 |

**注意：** v2.0 及以下版本的 SDK 已废弃，升级到 v3.x 可以避免 403 错误。

## 常见问题

**Q: SDK 初始化返回 403 错误？**
A: 检查以下几点：
1. API Key 是否有效且未过期
2. SDK 版本是否 >= 2.0（旧版本会返回 403）
3. 域名是否在白名单中
4. CORS 配置是否正确（浏览器环境）

**Q: 如何查看当前 SDK 版本？**
A: 
- Python: `pip show cloudsync`
- Node.js: `npm list @cloudsync/sdk`
- Java: 查看 pom.xml 中的版本号
- Go: `go list -m github.com/cloudsync/go-sdk`

**Q: SDK 支持异步调用吗？**
A: Python SDK 支持 `asyncio`，JavaScript SDK 原生支持 Promise。Java SDK 提供 CompletableFuture。
