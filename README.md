# Enterprise Customer Service Agent

基于 LangGraph + ReAct 的企业级智能客服系统，覆盖 RAG 检索、多路径工作流编排、记忆管理、安全防护、评估监控。

## 架构

```
接入层(FastAPI) → 安全层(4/5层护栏) → 编排层(LangGraph+DAG) → 能力层(RAG+记忆+工具) → 数据层(Chroma+Redis*+PG*)
                                                                        ↓
                                                               MemoryManager(三节点接入)
                                                              entry→rag→reply
```
*Redis/PG: 可用时自动启用，不可用时自动降级为进程内存

## 技能覆盖

- **RAG 子系统**：文档加载 → 语义分块 → Embedding → 混合检索（向量+BM25+RRF融合） ✅
  - Cross-Encoder 重排序 `[planned]`
- **ReAct Agent**：思考-行动-观察循环，并行工具调用 ✅
- **LangGraph 工作流**：5种对话路径自动路由（FAQ直达/技术排查/人工转接/FAQ升级RAG/RAG转人工） ✅
- **高级记忆管理**：三层架构（滑窗 + LLM 摘要 + 向量检索长期记忆 + 用户画像）
  - 短期记忆：Redis 优先（滑动窗口 + LLM 摘要），内存 fallback ✅
  - 长期记忆：PG 持久化 + Chroma 语义检索，内存 fallback ✅
  - MemoryManager：三节点接入（entry 注入上下文 → rag 提取历史 → reply 持久化） ✅
- **评估监控**：多维评估体系
  - RAG 离线指标（Recall/Precision/MRR/F1） ✅
  - LLM-as-Judge 对话质量评分（5 维） ✅
  - 在线抽样（可配置采样率） ✅
  - 幻觉检测（检索文档交叉验证） ✅
  - 行为指标（响应时长/用户满意度/留存） `[planned]`
- **智能体安全**：五层纵深防御
  - 输入检测（正则注入识别） ✅
  - 编排护栏（reflect_node 自我反思） ✅
  - Agent 护栏（System Prompt 约束） ✅
  - 输出校验（PII 泄露 + 幻觉引用检测） ✅
  - 审计告警（日志持久化 + 异常告警） `[planned]`

## 技术栈

| 组件 | 选型 |
|------|------|
| 编排 | LangGraph |
| Agent | LangChain (create_agent) |
| LLM | 阿里百炼 Qwen-Plus / Qwen-Max（兼容OpenAI格式） |
| Embedding | 阿里百炼 text-embedding-v4 (Qwen3, 1024维) |
| 向量库 | Chroma |
| 服务 | FastAPI + uvicorn |
| 评估 | LangSmith + 自定义指标 |

## 快速开始

### 1. 安装依赖

```bash
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
# 或 venv\Scripts\activate   # Windows cmd
pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env 填入你的阿里百炼 API Key
```

### 3. 入库知识库

```bash
python scripts/ingest_docs.py
```

### 4. 启动服务

```bash
python -m src.api.server
```

### 5. 测试对话

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How do I reset my password?"}'
```

## 项目结构

```
src/
├── config.py              # 配置（含记忆/评估新配置项）
├── rag/                   # RAG子系统
│   ├── loader.py          # 文档加载
│   ├── chunker.py         # 文本切块
│   ├── embedder.py        # Embedding服务（阿里百炼）
│   ├── vector_store.py    # 向量库管理（Chroma）
│   └── retriever.py       # 混合检索器（向量+BM25+RRF）
├── agent/                 # ReAct Agent
│   ├── tools.py           # 客服工具（search_kb / search_faq / escalate）
│   ├── prompt.py          # System Prompt（含 memory_context 注入）
│   └── agent.py           # Agent执行器
├── graph/                 # LangGraph编排
│   ├── state.py           # AgentState（含 memory_context/quality_score）
│   ├── nodes.py           # 7个图节点（entry/rag/reply 接入记忆）
│   └── workflow.py        # 工作流组装（绑定 retriever + memory_manager）
├── api/                   # FastAPI服务
├── memory/                # 记忆管理（全模块重写）
│   ├── short_term.py      # 短期记忆：Redis优先 + LLM摘要 + 内存fallback
│   ├── long_term.py       # 长期记忆：PG+Chroma优先 + 用户画像 + 内存fallback
│   └── manager.py         # MemoryManager：三节点接入 + 生命周期管理
├── evaluation/            # 评估指标
│   └── metrics.py         # RAG指标 + LLM-as-Judge + 在线抽样 + 幻觉检测
└── safety/                # 安全护栏
    ├── input_guard.py     # 输入注入检测
    ├── sanitizer.py       # Observation 清洗
    └── output_guard.py    # 输出敏感信息检测
```

## 运行测试

```bash
# 需要先设置 OPENAI_API_KEY 环境变量
pytest tests/ -v
```

## License

MIT
