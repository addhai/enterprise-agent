# enterprise-agent 项目回顾与剩余任务执行计划

> 项目经理视角 · 2026-09-20
> 项目路径：`C:\Users\hai\enterprise-agent`
> 运行环境：Windows10 + Docker Desktop(WSL2)，纯 CPU，全内网离线

---

## 一、项目目标回顾

### 1.1 核心定位
**工厂级智能客服** —— 面向工业设备知识库的 AI Agent，支持 RAG 问答、故障查询、多轮对话、引用溯源（含页码），**全内网离线部署**，零外网依赖。

### 1.2 技术栈
| 层 | 技术 |
|---|---|
| 后端 | FastAPI + LangGraph + LangChain |
| 向量库 | Chroma（持久化，生产基线 16 块→现 322 块） |
| LLM | Ollama 本地 qwen2.5:7b（CPU 推理） |
| Embedding | Ollama bge-m3（本地） |
| Rerank | bge-reranker-base（本地，safetensors 权重内置镜像） |
| 数据 | PostgreSQL 16 + Redis 7 |
| 部署 | Docker Compose 单容器 app + 独立 pg/redis |
| 监控 | Prometheus + Grafana（独立栈，4 容器） |

### 1.3 三大用户决策（贯穿全项目）
| 决策 | 内容 |
|---|---|
| Q1 | `kb_call_mode` 实现真实语义（always / never / smart） |
| Q2 | 启用 rerank，用本地 local_bge |
| Q3 | 引用需展示页码 |

### 1.4 红线约束
- 零外网依赖（运行时），构建时临时联网除外
- 功能完整性优先于镜像体积，不得以"精简运行时"裁剪 RAG 核心能力
- 所有结论附文件路径 + 行号代码证据
- compose 操作必须显式 `-f deploy/prod/docker-compose.prod.yml`
- 未经授权不重启/重建容器、不改业务代码

---

## 二、已完成进度全景

| 阶段 | 主题 | 核心成果 | 回归基线 |
|---|---|---|---|
| Phase4a | 外网残留收口 + local_bge 补齐 | src/+compose 外网地址清零；sentence-transformers+torch 纳入 runtime；rerank 权重内置 + HF_OFFLINE；rerank 重排序效果验证 | 1407 passed |
| Phase4b | 生产配置收口 + 监控修复 + WS联调 + L3/L4/L5 缺陷修复 | LLM_MODEL 改本地 qwen2.5:7b；monitoring.py datetime.UTC 修复；PG 密码轮换；WS 端到端 T100 测温范围验证通过；L3 工具结果污染修复；L4 检索排序回归修复（候选池放宽）；L5 ReAct 轮次上限死配置修复（Q2 从 900s 超时→48s） | 1413→1417 passed |
| Phase5 P0 | Q1/Q3 功能状态核查 | kb_call_mode 三模式真实实现；引用页码后端五层贯通，断点在前端 | — |
| Phase5 P1 | 前端页码闭环 + kb_call_mode 测试 + PDF导入 + keepalive 修复 | 前端「第 N 页」徽标渲染；4 个 kb_call_mode 分支测试；7 页 T90 PDF 入库（7/7 块带页码）；uvicorn WS keepalive 300s 修复；WS 两题 ALL PASS（page=2/4/5/7） | 1417 passed |
| Phase5 性能基准 | 镜像瘦身 + F02 故障查询优化 | 镜像 14.7GB→4.5GB（torch CPU 版，省 10.2GB/-69%）；F02 查询 558s→112s（降 80%）；CPU 性能基准建立 | 1417 passed |

### 关键技术债务已修复
- **L3**：工具结果污染接地重答（`_exclude_tool_docs` + `_is_resource_query` 精准注册工具）
- **L4**：rerank 前候选池截断导致正确文档被挤出（放宽至 `max(top_k*2, 10)`）
- **L5**：`max_reasoning_turns` 死配置从未生效（`recursion_limit = max_turns*2+4` + GraphRecursionError 降级）
- **C4**：uvicorn WS keepalive 20s 导致 CPU 长推理被 1011 强杀（改为 300s）

---

## 三、当前状态诊断

### 3.1 生产环境实际状态
| 项 | 状态 | 说明 |
|---|---|---|
| 业务栈容器 | 运行中（3 容器 healthy） | prod-app-1 / prod-postgres-1 / prod-redis-1 |
| 监控栈 | 运行中（4 容器） | Grafana:3000 / Prometheus:9090 / exporter / cadvisor |
| **生产镜像** | **14.7GB 旧版** | ⚠️ 性能基准的 4.5GB 瘦身镜像**尚未替换到生产** |
| 前端生产部署 | **未闭环** | ⚠️ prod 容器未托管 frontend/dist，根路径返回 Not Found |
| 知识库 | 322 块 | 仅 7 块带页码（T90 PDF），页码覆盖率 ~2% |
| 数据卷 | 完整保留 | prod-agent-chroma / prod-postgres-data / prod-redis-data |

### 3.2 已知遗留项
| # | 遗留项 | 严重度 | 影响 |
|---|---|---|---|
| 1 | 生产镜像未瘦身 | 中 | 14.7GB，部署/迁移慢，含无用 CUDA 库 5.3GB |
| 2 | 前端生产静态文件未部署 | 中 | 生产环境无法直接访问前端，需 dev server |
| 3 | 多 agent 健康检查持续报错 | 低 | 日志污染，`All connection attempts failed`，不影响主功能 |
| 4 | vite 默认端口 3000 与 Grafana 冲突 | 低 | 开发时需手动指定端口 |
| 5 | 知识库页码覆盖率低 | 低 | 仅 7/322 块带 page，页码展示功能覆盖面窄 |
| 6 | WS 断开后后台推理不取消 | 低 | 客户端断开后 CPU 仍被占用，无联动中止 |

---

## 四、剩余任务执行计划（项目经理视角）

### 4.1 任务优先级与依赖图

```
                        ┌─────────────────────┐
                        │  T1: 瘦身镜像替换生产  │  P0 · 阻塞后续
                        │  (14.7GB → 4.5GB)    │
                        └──────────┬──────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
          ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
          │ T2: 前端生产  │  │ T3: 遗留收口 │  │ T4: 知识库   │
          │ 部署闭环      │  │ (健康报错+   │  │ 批量扩展     │
          │              │  │  端口冲突)   │  │ (可并行)     │
          └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
                 │                │                │
                 └────────────────┼────────────────┘
                                  ▼
                        ┌─────────────────────┐
                        │  T5: 最终交付验收     │  P0 · 收尾
                        └─────────────────────┘
```

| ID | 任务 | 优先级 | 依赖 | 预估耗时 | 风险 |
|---|---|---|---|---|---|
| T1 | 瘦身镜像替换生产 | P0 | 无 | 20-30 min（含构建） | 中：构建期 torch CPU 版下载慢 |
| T2 | 前端生产部署闭环 | P0 | T1 | 30-45 min | 中：StaticFiles 路由顺序可能覆盖 API |
| T3 | 遗留问题收口 | P1 | T1 | 20-30 min | 低：配置级改动 |
| T4 | 知识库批量扩展 | P2 | 无（可并行） | 30-60 min | 低：只读验证为主 |
| T5 | 最终交付验收 | P0 | T1+T2+T3 | 30-45 min | 低：验证为主 |

**关键路径**：T1 → T2 → T5（约 1.5-2 小时）
**可并行**：T4 在 T1 构建期间同时进行，T3 可与 T2 并行

---

### 4.2 T1：瘦身镜像替换生产（P0，先做）

**目标**：生产 `prod-app-1` 从 14.7GB CUDA 版镜像切换到 4.5GB CPU 版镜像。

**为什么先做**：T2（前端部署）和 T3（遗留收口）都需要重建容器，基于新镜像统一重建可避免多次重启。

#### 操作步骤

```powershell
cd C:\Users\hai\enterprise-agent

# === 步骤 1：改动确认（只读） ===
# 确认 Dockerfile 瘦身改动已落盘
Select-String -Path Dockerfile -Pattern "torch.*\+cpu"
Select-String -Path Dockerfile -Pattern "chown=appuser:appuser"
# 预期：torch==2.14.0+cpu；所有 COPY 带 --chown

# === 步骤 2：备份当前镜像（回滚保险） ===
docker tag enterprise-agent-app-ollama:latest enterprise-agent-app-ollama:backup-14.7gb
docker images --filter "reference=enterprise-agent-app-ollama"
# 预期：看到 latest 和 backup-14.7gb 两个 tag

# === 步骤 3：构建瘦身镜像（需临时联网，约 10-15 分钟） ===
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production build app
# 关注：pip install torch CPU 版从 pytorch.org 下载，可能较慢；清华源加速其他包

# === 步骤 4：验证新镜像 ===
docker images enterprise-agent-app-ollama
# 预期：latest TAG 约 4.5GB（4500MB 左右）

# === 步骤 5：重建 app 容器（postgres/redis 不动，数据卷保留） ===
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app

# === 步骤 6：等待 healthy（轮询，约 1-2 分钟） ===
while ($true) {
  $status = docker inspect prod-app-1 --format "{{.State.Health.Status}}" 2>$null
  Write-Host "健康状态: $status"
  if ($status -eq "healthy") { break }
  Start-Sleep -Seconds 10
}

# === 步骤 7：功能验证 ===
# 7a. 健康端点 + 离线合规
curl.exe -s http://localhost:8000/api/v1/health
# 预期：{"status":"ok","service":"enterprise-agent","aliyun_demo_fallback":false}

# 7b. metrics 端点
curl.exe -s http://localhost:8000/api/v1/metrics/prometheus | Select-Object -First 5
# 预期：返回 Prometheus 文本指标

# 7c. torch CPU 版确认
docker exec prod-app-1 python -c "import torch; print(f'torch={torch.__version__}, cuda={torch.cuda.is_available()}')"
# 预期：torch=2.14.0+cpu, cuda=False

# 7d. 无 CUDA 垃圾目录
docker exec prod-app-1 sh -c "ls /usr/local/lib/python3.10/site-packages/ | grep -iE 'nvidia|triton' || echo 'NO_CUDA_PACKAGES'"
# 预期：NO_CUDA_PACKAGES

# 7e. rerank 权重完整
docker exec prod-app-1 ls -lh /app/models/bge-reranker-base/model.safetensors
# 预期：约 1.1GB

# 7f. WS keepalive 参数确认（P1 已改，确认未丢失）
docker inspect prod-app-1 --format "{{.Config.Cmd}}"
# 预期：含 --ws-ping-interval 300 --ws-ping-timeout 300
```

#### 验收标准
- [ ] `docker images` latest ≈ 4.5GB
- [ ] prod-app-1 healthy，启动日志无 ERROR
- [ ] health 端点 `aliyun_demo_fallback: false`
- [ ] torch=2.14.0+cpu，无 nvidia/triton 包
- [ ] rerank 权重存在，metrics 正常
- [ ] WS keepalive 300s 参数保留

#### 回滚方案（如瘦身镜像异常）
```powershell
docker tag enterprise-agent-app-ollama:backup-14.7gb enterprise-agent-app-ollama:latest
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app
```

---

### 4.3 T2：前端生产部署闭环（P0，T1 后）

**目标**：`frontend/dist` 打入镜像，由 FastAPI 托管静态文件，生产环境 `http://localhost:8000/` 直接返回前端页面，无需 dev server。

#### 操作步骤

```powershell
cd C:\Users\hai\enterprise-agent

# === 步骤 1：确认前端构建产物 ===
if (Test-Path frontend\dist\index.html) {
  Write-Host "dist 已存在"
} else {
  Write-Host "dist 不存在，执行构建..."
  cd frontend
  npm run build
  cd ..
}
# 预期：frontend/dist/index.html 存在

# === 步骤 2：检查 main.py 是否有 StaticFiles 挂载 ===
Select-String -Path main.py -Pattern "StaticFiles|mount"
# 如无，需添加（必须在所有 API 路由之后）：
# from fastapi.staticfiles import StaticFiles
# app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")

# === 步骤 3：检查 Dockerfile 是否 COPY frontend/dist ===
Select-String -Path Dockerfile -Pattern "frontend/dist"
# 如无，在 runtime stage 添加：
# COPY --chown=appuser:appuser frontend/dist /app/frontend/dist
# 注意：directory 参数要与容器内路径一致

# === 步骤 4：确认 compose 未用 volume 覆盖 frontend ===
Select-String -Path deploy\prod\docker-compose.prod.yml -Pattern "frontend"
# 预期：无 frontend 相关 volume 挂载（生产用镜像内置）

# === 步骤 5：重新构建镜像（含前端 dist） ===
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production build app

# === 步骤 6：重建容器 ===
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app

# === 步骤 7：等待 healthy ===
while ($true) {
  $status = docker inspect prod-app-1 --format "{{.State.Health.Status}}" 2>$null
  if ($status -eq "healthy") { break }
  Start-Sleep -Seconds 10
}

# === 步骤 8：验证 ===
# 8a. 根路径返回前端 HTML
$root = curl.exe -s http://localhost:8000/
$root | Select-String "<title>|<div id=" 
# 预期：含前端 index.html 内容（<div id="root"> 或 <title>）

# 8b. API 路由未被覆盖（关键！）
curl.exe -s http://localhost:8000/api/v1/health
# 预期：正常返回 JSON，不是 HTML

# 8c. 静态资源可访问
curl.exe -s -o NUL -w "%{http_code}" http://localhost:8000/assets/index-*.js
# 预期：200（实际文件名可能不同，用 ls frontend/dist/assets/ 确认）

# 8d. 浏览器手动验证：打开 http://localhost:8000
#     发送查询 "T90 热像仪的分辨率是多少"
#     确认：流式回复正常 + 引用卡片展示「第 N 页」徽标
```

#### 关键风险与应对
| 风险 | 应对 |
|---|---|
| StaticFiles 挂载在 API 路由之前，覆盖 /api/v1/* | 必须放在 `include_router` 之后；验证 8b 必做 |
| Dockerfile 中 dist 路径与 main.py 的 directory 参数不一致 | 两者统一用 `/app/frontend/dist` |
| 前端构建产物路径变化（Vite 版本差异） | 构建后 `ls frontend/dist/` 确认结构 |

#### 验收标准
- [ ] `http://localhost:8000/` 返回 200 + 前端 HTML
- [ ] `http://localhost:8000/api/v1/health` 返回 JSON（未被覆盖）
- [ ] 静态 JS/CSS 资源 200
- [ ] 浏览器端完整可用：发消息、流式回复、引用卡片+页码徽标
- [ ] 无需启动 dev server

---

### 4.4 T3：遗留问题收口（P1，T1 后，可与 T2 并行）

**目标**：消除多 agent 健康检查持续报错 + 修复 vite 端口冲突。

#### 3a. 多 agent 健康检查报错

```powershell
# === 步骤 1：确认报错来源 ===
docker logs prod-app-1 --tail 100 | Select-String "Probe.*error|All connection attempts failed"
# 预期：看到 customer_service/security_expert 等 probe error

# === 步骤 2：定位代码 ===
Select-String -Path src\ -Pattern "All connection attempts failed" -Recurse
Select-String -Path src\ -Pattern "health_checker|multi_agent.*probe" -Recurse
# 记录文件路径+行号

# === 步骤 3：实施方案（推荐 A，配置禁用） ===
# 方案 A：检查是否有 MULTI_AGENT_ENABLED 或类似配置项
Select-String -Path src\config.py -Pattern "multi_agent|agent_mode|probe"
# 如有，在 .env.production 中设为禁用
# 如无，采用方案 B：将 probe error 日志级别从 error 降为 warning/debug

# 方案 B：修改对应 probe 函数的 logger.error → logger.debug
# （因为当前 ai_chat 模式不依赖多 agent 子进程，probe 失败属预期）

# === 步骤 4：重建容器 ===
docker compose -f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production up -d --force-recreate app

# === 步骤 5：验证 ===
Start-Sleep -Seconds 30
docker logs prod-app-1 --tail 50 | Select-String "All connection attempts failed"
# 预期：无新增持续报错（启动时可能有一次，之后不再出现）
```

#### 3b. vite 端口冲突

```powershell
# === 步骤 1：检查 vite 配置 ===
Get-Content frontend\vite.config.ts -ErrorAction SilentlyContinue
Get-Content frontend\vite.config.js -ErrorAction SilentlyContinue
# 查找 server.port 或 port: 3000

# === 步骤 2：修改为 5173 ===
# 在 vite.config 中设置：
# server: { port: 5173 }

# === 步骤 3：验证 ===
Select-String -Path frontend\vite.config.* -Pattern "port"
# 预期：port: 5173（或其他非 3000 端口）
```

#### 验收标准
- [ ] `docker logs prod-app-1 --tail 100` 无持续 "All connection attempts failed"
- [ ] vite 默认端口 ≠ 3000
- [ ] 主功能（ai_chat）不受影响
- [ ] health 端点正常

---

### 4.5 T4：知识库批量扩展（P2，可与 T1 并行）

**目标**：导入更多多页 PDF 工业手册，提升知识库覆盖度和页码展示率。

**可并行原因**：通过 API 入库不依赖镜像重建，T1 构建期间可同时进行。

#### 操作步骤

```powershell
cd C:\Users\hai\enterprise-agent

# === 步骤 1：准备 PDF 素材 ===
# 放入 data/docs/，要求 PDF 正文含 markdown 风格 "# 标题" 行
# （否则 OutlineTree.split 不切章，页码无法注入）
# 可用 scripts/generate_demo_pdf.py 为模板生成演示素材
ls data\docs\*.pdf

# === 步骤 2：获取知识库 ID ===
curl.exe -s http://localhost:8000/api/v1/admin/knowledge | python -m json.tool
# 记录 kb_id（如 KBS-050822）

# === 步骤 3：逐个上传 PDF ===
foreach ($pdf in Get-ChildItem data\docs\*.pdf) {
  Write-Host "上传: $($pdf.Name)"
  curl.exe -s -X POST "http://localhost:8000/api/v1/admin/knowledge/KBS-050822/documents/upload" `
    -F "file=@$($pdf.FullName)"
  Write-Host ""
}

# === 步骤 4：验证入库结果（Chroma 只读） ===
docker exec prod-app-1 python -c "
import chromadb
c = chromadb.PersistentClient('/app/chroma_data')
col = c.get_collection('knowledge_base')
print(f'总块数: {col.count()}')
results = col.get(include=['metadatas'])
page_count = sum(1 for m in results['metadatas'] if m.get('page') is not None)
print(f'带页码块数: {page_count}')
print(f'页码覆盖率: {page_count/col.count()*100:.1f}%')
# 列出所有来源文档
sources = set(m.get('source','?') for m in results['metadatas'])
print(f'文档来源数: {len(sources)}')
for s in sorted(sources): print(f'  - {s}')
"

# === 步骤 5：WS 验证新 PDF 检索 + 页码 ===
python scripts\verify_pdf_page_citation.py
# 或手动发送针对新文档的查询

# === 步骤 6：备份 Chroma 数据卷 ===
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
docker run --rm -v prod-agent-chroma:/data -v "${PWD}:/backup" alpine `
  tar czf "/backup/chroma_backup_${timestamp}.tar.gz" -C /data .
```

#### 验收标准
- [ ] 知识库总块数 > 322
- [ ] 带页码块数增加，页码覆盖率 > 5%
- [ ] 新文档可被检索命中，citations.page 为非 None 整数
- [ ] Chroma 数据卷已备份

---

### 4.6 T5：最终交付验收（P0，最后做）

**目标**：全量回归 + 外网审计 + 端到端验证 + 文档归档，确认可交付上线。

#### 操作步骤

```powershell
cd C:\Users\hai\enterprise-agent

# === 1. 全量回归测试 ===
.\venv\Scripts\python.exe -m pytest -o addopts="" -q -n 2 --basetemp=".pytest_tmp" -p no:cacheprovider
# 预期：>= 1417 passed / 0 failed
# 记录 passed / skipped / failed / 耗时

# === 2. 外网依赖审计 ===
# 2a. 源码外网地址扫描（排除 localhost/127.0.0.1）
Select-String -Path src\ -Pattern "https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)" -Recurse
# 预期：仅第三方协作平台 Webhook（钉钉/飞书/Slack/GitHub），默认不调用

# 2b. compose 文件扫描
Select-String -Path deploy\prod\docker-compose.prod.yml -Pattern "https?://|qwen-plus|text-embedding"
# 预期：无外网 API 地址，LLM_MODEL=qwen2.5:7b

# 2c. 运行时离线验证
curl.exe -s http://localhost:8000/api/v1/health
# 预期：aliyun_demo_fallback: false

# 2d. 离线环境变量
docker exec prod-app-1 python -c "
import os
print(f'HF_HUB_OFFLINE={os.environ.get(\"HF_HUB_OFFLINE\")}')
print(f'TRANSFORMERS_OFFLINE={os.environ.get(\"TRANSFORMERS_OFFLINE\")}')
"
# 预期：均为 1

# === 3. 核心功能端到端验证 ===
# 3a. 规格查询（FAQ 快速路径，< 30s）
curl.exe -s -X POST http://localhost:8000/api/v1/chat `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"ThermoView T100测温范围是多少？\",\"session_id\":\"final_spec\"}" `
  --max-time 120
# 预期：回答含 -20~550℃

# 3b. 故障查询（快速 RAG 路径，< 180s）
curl.exe -s -X POST http://localhost:8000/api/v1/chat `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"F02故障代码怎么处理？\",\"session_id\":\"final_fault\"}" `
  --max-time 180
# 预期：回答含快门校正步骤

# 3c. WS 流式 + 页码验证
python scripts\verify_pdf_page_citation.py
# 预期：ALL PASS，citations.page 非 None（page=2/4/5/7）

# 3d. 前端页面验证（浏览器手动）
# 打开 http://localhost:8000，发送上述查询，确认：
# - 流式输出正常
# - 引用卡片展示「第 N 页」徽标
# - 无控制台报错

# === 4. 数据完整性验证 ===
docker exec prod-app-1 python -c "
import chromadb
c = chromadb.PersistentClient('/app/chroma_data')
for name in ['knowledge_base', 'long_term_memory']:
    col = c.get_collection(name)
    print(f'{name}: {col.count()} 块')
"
# 预期：knowledge_base >= 322，long_term_memory >= 2

# === 5. 容器状态验证 ===
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# 预期：业务栈 3 容器 healthy，监控栈 4 容器 running

# === 6. 镜像体积确认 ===
docker images enterprise-agent-app-ollama --format "table {{.Tag}}\t{{.Size}}"
# 预期：latest <= 5GB

# === 7. 文档归档确认 ===
# 确认以下文档齐全且为最新版本：
ls *.md
# - README-生产部署与运维手册.md
# - Phase4a-改动清单与验收报告.md
# - Phase4b-镜像重建与端到端联调报告.md
# - Phase4b-改动清单与验收报告.md
# - Phase5-P1-验收报告.md
# - Phase5-性能基准与故障查询优化报告.md
# - 本文件（项目回顾与剩余任务执行计划）
```

#### 最终验收清单（全部勾选后方可交付）

- [ ] 全量回归 >= 1417 passed / 0 failed
- [ ] 源码 + compose 无新增外网依赖
- [ ] health 端点 `aliyun_demo_fallback: false`
- [ ] HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1
- [ ] 规格查询返回 -20~550℃
- [ ] 故障查询返回 F02 快门校正步骤
- [ ] WS 验证 ALL PASS，citations.page 非 None
- [ ] 前端根路径可访问，页码徽标正常展示
- [ ] 知识库数据完整（>= 322 块）
- [ ] 业务栈 3 容器 healthy，监控栈 4 容器 running
- [ ] 镜像 <= 5GB
- [ ] 无持续 error 日志
- [ ] 所有文档齐全且最新

---

## 五、风险管理

| 风险 | 概率 | 影响 | 应对措施 |
|---|---|---|---|
| T1 构建期 torch CPU 版下载慢/失败 | 中 | 构建超时 | 提前确认 pytorch.org 可达；失败则重试或用国内镜像 |
| T2 StaticFiles 覆盖 API 路由 | 中 | /api/v1/* 返回 HTML | 挂载必须在路由之后；验证 8b 为强制检查项 |
| T1 新镜像启动异常 | 低 | 服务中断 | 已 tag backup-14.7gb，5 分钟内可回滚 |
| T4 PDF 入库后无页码 | 中 | 页码覆盖率不提升 | PDF 必须含 `# 标题` 行；入库后 Chroma 只读验证 page 字段 |
| 全量回归出现环境相关失败 | 低 | 验收阻塞 | 已知 test_llm_rebuild_hot_reload 已修复为离线 mock；如遇新失败先定位是否依赖主机 Ollama |
| Docker Desktop 未启动 | 低 | 全部阻塞 | 执行前 `docker version` 确认 daemon 运行 |

---

## 六、执行纪律（全程遵守）

1. **每步执行前先只读确认**，不跳过改动确认直接操作
2. **compose 命令必须完整**：`-f deploy/prod/docker-compose.prod.yml --env-file deploy/prod/.env.production`
3. **重建只重建 app**，postgres/redis 不动，数据卷不丢
4. **改动前备份**：T1 镜像 tag 备份 + T4 Chroma 卷备份
5. **每步验收通过后再进下一步**，不累积未验证改动
6. **所有结论附文件路径 + 行号**，不使用"应该/大概"
7. **构建期临时联网，运行时必须验证离线**
8. **遇到异常立刻停止**，排查根因后再继续，不绕过

---

## 七、预计总工时

| 任务 | 耗时 | 备注 |
|---|---|---|
| T1 瘦身镜像替换 | 20-30 min | 构建占主要时间 |
| T2 前端部署闭环 | 30-45 min | 含代码确认+构建+验证 |
| T3 遗留收口 | 20-30 min | 可与 T2 并行 |
| T4 知识库扩展 | 30-60 min | 可与 T1 并行 |
| T5 最终验收 | 30-45 min | 回归测试占主要时间 |
| **关键路径合计** | **约 1.5-2 小时** | T1→T2→T5 |
| **全部完成（含并行）** | **约 2-2.5 小时** | |

---

## 八、交付物清单

完成 T1-T5 后，项目交付物包括：

1. **生产镜像**：`enterprise-agent-app-ollama:latest`（≈4.5GB，含前端 dist + rerank 权重 + Chroma 数据）
2. **运行环境**：3 业务容器 + 4 监控容器，全离线，healthy
3. **数据卷**：prod-agent-chroma（>=322 块）+ prod-postgres-data + prod-redis-data
4. **文档**：7 份阶段报告 + 运维手册 + 本执行计划
5. **测试基线**：>= 1417 passed / 0 failed
6. **合规证明**：外网审计零运行时依赖，health 端点 aliyun_demo_fallback=false
