# 回滚预案（P4-2）

> 三种回滚场景，每种含触发条件、操作步骤、验证方法、预计恢复时间。
> 版本号管理：镜像 tag 用 git commit short hash，上线前记录当前版本。

---

## 场景 1：RAG 优化导致回答质量下降

### 触发条件
- 用户反馈回答质量明显下降
- 幻觉率人工抽检 > 15%
- 评估集 Hit@1 从 75.8% 降至 < 50%

### 操作步骤

```bash
# 1. 关闭查询改写
docker exec thermo-intranet sh -c 'export REWRITE_ENABLED=false'

# 2. 清除文档权重
docker exec thermo-intranet sh -c 'export DOC_WEIGHTS=""'

# 3. 重启容器使环境变量生效
docker restart thermo-intranet

# 4. 等待健康检查通过（约 90 秒）
for i in $(seq 1 30); do
    status=$(curl -s http://localhost:8000/api/health | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    [ "$status" = "ok" ] && echo "healthy" && break
    sleep 3
done
```

### 验证方法
```bash
# 确认改写已关闭
curl -s http://localhost:8000/api/v1/health | python -c "import sys; print(sys.stdin.read())"

# 跑评估确认回到基线
python tests/rag_eval/eval_recall.py --mode direct --top-k 5
# 预期：Hit@1 回到 ~36.4%（BM25 基线）
```

### 预计恢复时间
**30 秒**（重启容器 + 健康检查等待）

---

## 场景 2：新版本代码有 bug

### 触发条件
- 上线后出现 500 错误率 > 5%
- 核心功能不可用（对话/检索/登录）
- 全量测试失败

### 操作步骤

```bash
# 1. 查看当前版本
docker images --format "{{.ID}} {{.Repository}}:{{.Tag}} {{.CreatedAt}}" | grep thermo-chatbot
# 记录当前镜像 ID

# 2. 查看历史镜像版本
docker images -a | grep thermo-chatbot

# 3. 回退到上一版本（假设上一版本 tag 为 thermo-chatbot:1.0.0-prev）
docker tag thermo-chatbot:1.0.0-prev thermo-chatbot:1.0.0

# 4. 重建容器
docker rm -f thermo-intranet
docker run -d --name thermo-intranet --network thermo-net \
    -p 8000:8000 --memory=1g --cpus=1.0 \
    --env-file .env.intranet \
    thermo-chatbot:1.0.0

# 5. 等待健康检查
for i in $(seq 1 40); do
    s=$(docker inspect thermo-intranet --format "{{.State.Health.Status}}")
    [ "$s" = "healthy" ] && echo "healthy" && break
    sleep 3
done
```

### 验证方法
```bash
# 健康检查
curl http://localhost:8000/api/health

# 核心问答
curl -X POST http://localhost:8000/api/chat \
    -H "Content-Type: application/json" \
    -d '{"question":"测温范围是多少？"}'

# 向量库验收
docker exec thermo-intranet python scripts/verify_intranet_kb.py
# 预期：9/9 ALL PASS
```

### 预计恢复时间
**2-3 分钟**（镜像 tag 切换 + 容器重建 + 健康检查）

---

## 场景 3：向量库损坏

### 触发条件
- 检索结果恒为空（所有查询 total_hits=0）
- Chroma sqlite 文件损坏或丢失
- 检索接口返回 503"检索器初始化失败"

### 操作步骤

```bash
# 1. 停止容器（必须先停，避免热拷贝损坏）
docker stop thermo-intranet

# 2. 从备份恢复向量库
bash scripts/ops/restore_data.sh backup/<最近的备份目录>

# 3. 重建镜像（将恢复的 chroma_data 烘入镜像）
docker build -t thermo-chatbot:1.0.0 .

# 4. 重建容器
docker rm -f thermo-intranet
docker run -d --name thermo-intranet --network thermo-net \
    -p 8000:8000 --memory=1g --cpus=1.0 \
    --env-file .env.intranet \
    thermo-chatbot:1.0.0

# 5. 等待健康检查
for i in $(seq 1 40); do
    s=$(docker inspect thermo-intranet --format "{{.State.Health.Status}}")
    [ "$s" = "healthy" ] && echo "healthy" && break
    sleep 3
done
```

### 验证方法
```bash
# 向量库条数
docker exec thermo-intranet python -c "
import chromadb; c=chromadb.PersistentClient(path='./chroma_data')
for col in c.list_collections():
    n = col if isinstance(col, str) else col.name
    print(n, c.get_collection(n).count())
"
# 预期：knowledge_base 301, knowledge_base_sentences 956

# 向量库验收
docker exec thermo-intranet python scripts/verify_intranet_kb.py
# 预期：9/9 ALL PASS

# 检索测试
curl -X POST http://localhost:8000/api/v1/admin/knowledge/<kb_id>/hit_test \
    -H "Authorization: Bearer <token>" \
    -H "Content-Type: application/json" \
    -d '{"query":"校准","top_k":5}'
# 预期：total_hits > 0
```

### 预计恢复时间
**5-10 分钟**（停容器 + 恢复数据 + 重建镜像 + 健康检查）

---

## 版本号管理规范

| 项 | 规范 |
|---|---|
| 镜像 tag | `thermo-chatbot:<git-short-hash>` 或 `thermo-chatbot:1.0.0-<date>` |
| 上线前 | `git rev-parse --short HEAD` 记录当前 commit hash |
| 镜像保留 | 至少保留最近 2 个版本，回退时有镜像可用 |
| 变更记录 | 上线 checklist 5.1 记录当前镜像 ID |

```bash
# 上线前记录版本
echo "当前镜像: $(docker images -q thermo-chatbot:1.0.0)" >> deploy/release_log.txt
echo "当前 commit: $(git rev-parse --short HEAD)" >> deploy/release_log.txt
echo "上线时间: $(date -Iseconds)" >> deploy/release_log.txt
```
