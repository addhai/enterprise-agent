# 上线操作指南（P4-3）

> 面向运维人员，一步一步操作。每个步骤有具体命令和预期输出。
> 与 `docs/LAUNCH_CHECKLIST.md` 36 项对应，指南中引用 checklist 编号。

---

## 1. 前置条件

### 硬件

| 项 | 最低 | 推荐 |
|---|---|---|
| CPU | 2 核 | 4 核 |
| 内存 | 4GB | 8GB |
| 磁盘 | 20GB | 50GB SSD |
| GPU | 无（CPU 可跑，LLM 慢 10x） | NVIDIA 8GB+ 显存 |

### 软件

```bash
# Docker + Compose
docker --version          # Docker version 24+
docker compose version    # Docker Compose version v2.20+

# GPU 驱动（可选）
nvidia-smi               # 显示 GPU 信息则驱动已安装
```

预期输出：版本号正常显示，无 error。

### 网络

- 端口 8000 可用（`netstat -tlnp | grep 8000` 应为空）
- 内网部署无需公网访问
- 云端部署需能访问 `dashscope.aliyuncs.com`

---

## 2. 首次部署

### 2.1 拷贝代码

```bash
git clone https://github.com/addhai/enterprise-agent.git
cd enterprise-agent
```

### 2.2 配置环境变量

```bash
cp deploy/prod/.env.production.example deploy/prod/.env.production
```

编辑 `.env.production`，必须修改以下项（对应 checklist 2.1-2.7）：

```bash
# 生成 JWT_SECRET（32 字节以上）
python -c "import secrets; print(secrets.token_urlsafe(32))"
# 将输出填入 JWT_SECRET=

# 设置 PostgreSQL 密码
POSTGRES_PASSWORD=your-strong-password-here

# 选择部署模式：
# 内网（Ollama 本地）:
LLM_MODEL=qwen2.5:7b
OPENAI_API_BASE=http://ollama:11434/v1
OPENAI_API_KEY=

# 云端（阿里云百炼）:
LLM_MODEL=qwen-plus
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=sk-your-key
```

### 2.3 拉取模型（内网部署）

```bash
# 启动 ollama 容器
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d ollama

# 等待 ollama 就绪
sleep 10

# 拉取模型
docker exec deploy-prod-ollama-1 ollama pull qwen2.5:7b
docker exec deploy-prod-ollama-1 ollama pull bge-m3

# 验证
curl http://localhost:11434/api/tags
# 预期：{"models":[{"name":"qwen2.5:7b",...},{"name":"bge-m3",...}]}
```

### 2.4 一键部署

```bash
bash deploy/prod/scripts/deploy.sh
```

脚本执行 8 个步骤（对应 checklist 1.1-1.6, 2.1-2.7）：
1. 环境检查（docker/端口/GPU）
2. 配置检查（JWT_SECRET/PG 密码非默认值）
3. 备份当前数据
4. 构建镜像
5. 停止旧容器
6. 启动新容器
7. 等待健康检查（60s 超时）
8. 输出部署结果

预期输出：
```
[OK] Health check: OK (attempt 3)
==========================================
  Deploy Summary
  Image: enterprise-agent:prod
  Containers: app/ollama/postgres/redis 全部 Up
==========================================
```

### 2.5 验证

```bash
# 冒烟测试
bash deploy/prod/scripts/verify.sh
# 预期：10/10 passed
```

---

## 3. 日常升级

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 一键部署（含备份）
bash deploy/prod/scripts/deploy.sh

# 3. 验证
bash deploy/prod/scripts/verify.sh
```

deploy.sh 会自动备份当前数据（步骤 3），失败时自动停止并提示回滚。

---

## 4. 回滚

### 场景 1：RAG 优化导致回答质量下降（30 秒）

```bash
# 关闭查询改写 + 清除文档权重
docker exec deploy-prod-app-1 sh -c 'export REWRITE_ENABLED=false DOC_WEIGHTS=""'
docker restart deploy-prod-app-1

# 验证（对应 checklist 5.8）
bash deploy/prod/scripts/verify.sh
```

### 场景 2：新版本代码有 bug（2-3 分钟）

```bash
# 查看可用镜像
docker images | grep enterprise-agent

# 回退到上一版本
bash deploy/prod/scripts/rollback.sh enterprise-agent:<旧版本tag>

# 验证
bash deploy/prod/scripts/verify.sh
```

### 场景 3：向量库损坏（5-10 分钟）

```bash
# 查看可用备份
ls -1 backup/

# 从备份恢复
bash deploy/prod/scripts/rollback.sh backup/20260912_180000

# 验证
bash deploy/prod/scripts/verify.sh
```

---

## 5. 上线后 24 小时观察

### 5.1 健康检查（每 30 分钟）

```bash
curl -s http://localhost:8000/api/health | python -m json.tool
```

关注 `checks` 字段：
- `database: ok` → 正常
- `vector_store: ok` → 正常
- `ollama: unreachable` → 检查 ollama 容器是否存活
- `models: none` → 检查模型是否加载

### 5.2 监控指标（每小时）

```bash
# 指标端点
curl -s http://localhost:8000/api/v1/metrics/prometheus | grep http_request
```

对照 `docs/MONITORING_METRICS.md` 18 个指标，关注：
- API P95 > 3s → 告警
- 转人工率 > 30% → AI 答不好
- 幻觉率 > 10% → 知识库覆盖不足

### 5.3 容器资源

```bash
docker stats --no-stream
```

关注：
- app 内存 > 800MB → 接近 1GB 限制
- ollama 显存 > 7GB → 接近 8GB 限制
- postgres 内存 > 400MB → 接近 512MB 限制

### 5.4 日志

```bash
# 实时日志
bash scripts/ops/tail_logs.sh

# 错误日志过滤
docker logs deploy-prod-app-1 2>&1 | grep '"level":"ERROR"'
```

---

## 6. 常见问题排查

### 容器起不来

```bash
# 查看启动日志
docker logs deploy-prod-app-1 2>&1 | tail -30

# 常见原因：
# 1. 端口被占用 → netstat -tlnp | grep 8000
# 2. 数据库密码错误 → 检查 .env.production
# 3. 向量库路径不存在 → docker exec app ls /app/chroma_data
```

### 健康检查 degraded

```bash
# 查看哪个依赖 down
curl -s http://localhost:8000/api/health | python -m json.tool

# 常见原因：
# ollama: unreachable → docker restart deploy-prod-ollama-1
# vector_store: empty → 向量库未初始化，需重建
# database: down → docker restart deploy-prod-postgres-1
```

### 回答为空

```bash
# 检查 LLM 是否可用
curl -s http://localhost:11434/api/tags | python -m json.tool

# 检查向量库条数
docker exec deploy-prod-app-1 python -c "
import chromadb; c=chromadb.PersistentClient(path='/app/chroma_data')
for col in c.list_collections():
    n = col if isinstance(col, str) else col.name
    print(n, c.get_collection(n).count())
"
# 预期：knowledge_base 301, knowledge_base_sentences 956
```

### 显存不足

```bash
# 查看 GPU 使用
nvidia-smi

# 如果显存不足：
# 1. 关闭其他 GPU 进程
# 2. 换用更小模型（如 qwen2.5:3b）
# 3. 降低 ollama 并发
docker exec deploy-prod-ollama-1 ollama stop qwen2.5:7b
docker exec deploy-prod-ollama-1 ollama run qwen2.5:3b
```

---

## Checklist 交叉引用

| 指南章节 | Checklist 编号 |
|---|---|
| 首次部署 2.4 | 1.1-1.6, 2.1-2.7 |
| 验证 2.5 | 5.1-5.7 |
| 回滚场景 1 | 5.8-5.9 |
| 回滚场景 2 | 1.1, 5.1 |
| 回滚场景 3 | 3.1-3.6 |
| 观察 5.1 | 4.1-4.7 |
| 观察 5.2 | 2.4-2.5 |
