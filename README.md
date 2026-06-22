# Enterprise Customer Service Agent

基于 LangGraph + ReAct 的企业级智能客服系统，覆盖 RAG 检索、多路径工作流编排、记忆管理、安全防护、评估监控。

## 架构

```
接入层(FastAPI) → 安全层(5层护栏) → 编排层(LangGraph状态图) → 能力层(RAG+记忆+工具) → 数据层(Chroma+Redis+PG)
```

## 技能覆盖

- **RAG 子系统**：文档加载 → 语义分块 → Embedding → 混合检索（向量+BM25+RRF融合+Cross-Encoder重排序）
- **ReAct Agent**：思考-行动-观察循环，并行工具调用
- **LangGraph 工作流**：5种对话路径自动路由（FAQ直达/技术排查/人工转接/FAQ升级RAG/RAG转人工）
- **高级记忆管理**：三层架构（滑窗+对话摘要+检索式长期记忆+用户画像）
- **评估监控**：多维评估体系（RAG指标+LLM-as-Judge成对比较+在线抽样+行为指标）
- **智能体安全**：五层纵深防御（输入检测→编排护栏→Agent护栏→输出校验→审计告警）

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
├── config.py              # 配置
├── rag/                   # RAG子系统
│   ├── loader.py          # 文档加载
│   ├── chunker.py         # 文本切块
│   ├── embedder.py        # Embedding服务
│   ├── vector_store.py    # 向量库管理
│   └── retriever.py       # 混合检索器
├── agent/                 # ReAct Agent
│   ├── tools.py           # 客服工具
│   ├── prompt.py          # System Prompt
│   └── agent.py           # Agent执行器
├── graph/                 # LangGraph编排
│   ├── state.py           # AgentState
│   ├── nodes.py           # 6个图节点
│   └── workflow.py        # 工作流组装
├── api/                   # FastAPI服务
├── memory/                # 记忆管理
├── evaluation/            # 评估指标
└── safety/                # 安全护栏
```

## 运行测试

```bash
# 需要先设置 OPENAI_API_KEY 环境变量
pytest tests/ -v
```

## License

MIT
