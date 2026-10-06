# 性能优化与部署指南

## 性能优化

### SDK 连接池

```python
from cloudsync import CloudSyncClient

# 使用连接池（推荐）
client = CloudSyncClient(
    api_key="cs_live_xxx",
    connection_pool_size=10,     # 最大连接数
    connection_pool_timeout=30,  # 连接超时（秒）
    max_retries=3,               # 自动重试次数
    retry_delay=1.0,             # 重试间隔（秒）
)
```

### 批量操作

**避免逐个请求：**

```python
# 慢：逐个创建（100 个文件需要 100 次 HTTP 请求）
for file in files:
    client.files.create(file.name, file.content)

# 快：批量创建（100 个文件只需 1 次 HTTP 请求）
client.files.batch_create([
    {"name": f.name, "content": f.content}
    for f in files
])
```

**批量操作限制：**

| 操作 | 最大批量大小 | 超时 |
|------|-------------|------|
| 文件创建 | 50 个/次 | 30 秒 |
| 文件更新 | 100 个/次 | 60 秒 |
| 文件删除 | 50 个/次 | 30 秒 |
| 同步任务创建 | 10 个/次 | 60 秒 |

### 选择性同步

减少同步数据量以提升性能：

```python
client.sync.create_job(
    source="Dropbox",
    target="OneDrive",
    folder="/Documents",
    # 只同步特定文件类型
    filters={
        "file_types": [".pdf", ".docx", ".xlsx"],
        "min_size": "1MB",
        "max_age_days": 365,
    },
    # 排除特定目录
    exclude_folders=["/Temp", "/Cache"],
)
```

### 缓存策略

```python
from cloudsync import CloudSyncClient
from functools import lru_cache

client = CloudSyncClient(api_key="cs_live_xxx")

@lru_cache(maxsize=100)
def get_user_profile(user_id: str):
    """缓存用户配置，避免重复 API 调用"""
    return client.accounts.get_profile(user_id)
```

## Docker 部署

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动服务
CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml

```yaml
version: '3.8'
services:
  agent:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
      - chroma

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  chroma:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - chroma_data:/chroma/chroma

volumes:
  chroma_data:
```

### 健康检查

```yaml
services:
  agent:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## Kubernetes 部署

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cloudsync-agent
spec:
  replicas: 3
  selector:
    matchLabels:
      app: cloudsync-agent
  template:
    metadata:
      labels:
        app: cloudsync-agent
    spec:
      containers:
      - name: agent
        image: cloudsync/agent:latest
        ports:
        - containerPort: 8000
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: cloudsync-secrets
              key: api-key
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "1000m"
            memory: "1Gi"
        readinessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
```

### HPA（水平自动扩缩容）

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agent-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: cloudsync-agent
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

## 监控与告警

### Prometheus 指标

| 指标 | 说明 | 类型 |
|------|------|------|
| `agent_requests_total` | 总请求数 | Counter |
| `agent_request_duration_seconds` | 请求延迟 | Histogram |
| `agent_active_sessions` | 活跃会话数 | Gauge |
| `agent_errors_total` | 错误总数 | Counter |
| `rag_retrieval_latency_seconds` | RAG 检索延迟 | Histogram |
| `memory_cache_hits_total` | 缓存命中次数 | Counter |
| `memory_cache_misses_total` | 缓存未命中次数 | Counter |

### Grafana 仪表盘

关键面板：
1. **QPS 趋势** — 实时监控请求量
2. **P99 延迟** — 尾部延迟监控
3. **错误率** — 5xx 错误比例
4. **缓存命中率** — RAG 缓存效率
5. **Token 消耗** — LLM 调用成本

### 告警规则

| 告警 | 条件 | 严重等级 |
|------|------|---------|
| 高错误率 | 5xx > 5% 持续 5 分钟 | Critical |
| 高延迟 | P99 > 5s 持续 10 分钟 | Warning |
| 缓存命中率低 | 缓存命中率 < 50% 持续 30 分钟 | Warning |
| Token 消耗异常 | 单日 > 预算的 80% | Warning |
| 服务不可用 | 健康检查失败 3 次 | Critical |
