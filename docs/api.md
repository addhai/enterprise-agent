# API / WebSocket 接口文档

本文档描述企业智能客服系统的对外接口。系统采用 **HTTP REST + WebSocket** 双通道：

- **REST**（`/api/v1/*`）负责鉴权、管理后台、知识库、RBAC、评价、监控等 CRUD/查询类操作。
- **WebSocket**（`/ws/chat`、`/ws/agent/{agent_id}`）负责**实时对话**——这是产品主链路，前端浮动聊天组件即走 `/ws/chat`。

> 所有时间戳为 Unix epoch（秒），所有消息为 UTF-8 JSON。

---

## 1. 通用约定

| 项 | 说明 |
|----|------|
| REST Base URL | `/api/v1` |
| 内容类型 | `application/json` |
| 鉴权 | Bearer Token：`Authorization: Bearer <token>`（登录接口 `/api/v1/auth/login` 返回） |
| 角色 | 普通用户 / `admin`（管理后台接口需 admin 角色，由 RBAC 中间件校验） |
| 错误格式 | `{"detail": "..."}`（FastAPI 标准）/ 或 WebSocket `error` 消息 |

健康检查（无需鉴权）：

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok"}
```

---

## 2. WebSocket：`/ws/chat`（用户 ↔ AI 对话）

这是系统的**核心实时通道**：前端浮动客服组件 → `new WebSocket('/ws/chat')` → 后端触发 LangGraph 多智能体 DAG → 流式回推。

### 2.1 连接与就绪

连接后，服务端**首先**推送一条 `session_ready`，告知客户端会话已建立（客户端无需显式"创建会话"）：

```json
// ← 服务端
{
  "type": "session_ready",
  "session_id": "3f1c...uuid",
  "message": "连接成功",
  "timestamp": 1754120000.0
}
```

### 2.2 客户端 → 服务端（发送）

| type | 字段 | 说明 |
|------|------|------|
| `chat_message` | `message`(str, ≤2000字)、`session_id?`、`user_id?`、`tenant_id?`、`user_plan?`、`image_base64?`、`audio_base64?` | 用户发言 / 多模态输入 |
| `heartbeat` | — | 心跳保活，服务端回 `heartbeat_ack` |
| `human_escalation` | `session_id?`、`reason?` | 用户主动请求转人工 |

最小发消息示例：

```json
// → 客户端发送
{
  "type": "chat_message",
  "message": "你们的产品支持私有化部署吗？"
}
```

### 2.3 服务端 → 客户端（接收）

| type | 关键字段 | 说明 |
|------|----------|------|
| `session_ready` | `session_id` | 连接/新会话就绪 |
| `typing_indicator` | `is_typing`(bool)、`status?` | "正在理解您的问题…" |
| `streaming_chunk` | `text`、`delta`、`done`(bool)、`suggest_human`(bool) | **流式文本片段**；收到 `done:true` 表示本轮结束 |
| `transfer_notice` | `reason`、`estimated_wait_seconds`、`message` | 转人工通知 |
| `handoff_context` | `summary`、`conversation`、`user_profile`、`attempted_solutions`、`quality_score` | 转人工上下文包（内部） |
| `info` | `text` | 状态提示（如"正在转接…"、"有 N 条结果因权限不足被过滤"） |
| `error` | `error_code`、`error_message` | 错误（`INVALID_JSON` / `MESSAGE_TOO_LONG` / `CHAT_ERROR` / `INTERNAL_ERROR`） |
| `heartbeat_ack` | `timestamp` | 心跳响应 |

### 2.4 一轮典型对话（服务端推送顺序）

```
typing_indicator   {is_typing:true, status:"正在理解您的问题..."}
streaming_chunk    {text:"我们支持", delta:"我们支持", done:false}
streaming_chunk    {text:"私有化部署。", delta:"私有化部署。", done:false}
streaming_chunk    {text:"", done:true, suggest_human:false}   ← 本轮结束
typing_indicator   {is_typing:false}                            ← 思考结束
```

### 2.5 前端参考实现（TypeScript）

```ts
const ws = new WebSocket('/ws/chat');
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  switch (msg.type) {
    case 'session_ready':      /* 记录 msg.session_id */ break;
    case 'streaming_chunk':    /* 追加 msg.text；msg.done 时收尾 */ break;
    case 'typing_indicator':   /* 显示"正在输入…" */ break;
    case 'transfer_notice':    /* 提示转人工 */ break;
    case 'error':              /* 处理错误 */ break;
  }
};
// 发送
ws.send(JSON.stringify({ type: 'chat_message', message: '你好' }));
```

### 2.6 转人工流程

当 AI 判定需转人工（或用户发 `human_escalation`）时：

1. 服务端 `build_typing_indicator(is_typing:false)`
2. 推送 `streaming_chunk`（提示"正在为您转接人工"）+ `done:true`（`needs_human:true, awaiting_human:true`）
3. 推送 `transfer_notice` + `handoff_context` 给人工坐席工作台
4. 会话状态置为 `WAITING_HUMAN`，后续用户消息被转发给坐席

---

## 3. WebSocket：`/ws/agent/{agent_id}`（人工坐席工作台）

坐席登录后接入，接收转接任务、向用户回复。

### 客户端 → 服务端

| type | 字段 | 说明 |
|------|------|------|
| `agent_send_reply` | `session_id`、`text` | 坐席回复某会话的用户 |
| `agent_login` | — | 登录（连接即注册，一般无需显式） |
| `agent_logout` | — | 登出 |
| `heartbeat` | — | 心跳 |

### 服务端 → 坐席

| type | 关键字段 | 说明 |
|------|----------|------|
| `new_transfer` | `transfer_id`、`session_id`、`user_id`、`summary`、`conversation`、`user_profile`、`urgency` | 新转接任务（low/normal/high/critical） |
| `agent_chat_message` | `session_id`、`user_message` | 用户发来新消息 |
| `session_update` | `mode`、`assigned_agent` | 会话状态变更 |
| `agent_reply_ack` | `session_id`、`sent`(bool) | 回复投递确认 |
| `copilot_suggestion` | `session_id`、`suggestions[]`、`confidence[]` | AI 辅助建议回复 |
| `heartbeat_ack` | `timestamp` | 心跳响应 |

坐席回复示例：

```json
// → 坐席发送
{ "type": "agent_send_reply", "session_id": "3f1c...", "text": "您好，我是人工客服，已为您接入。" }
```

---

## 4. REST API 速查（按域分组）

> 所有路径前缀 `/api/v1`。下表为代表性端点，非穷举；完整列表见源码 `src/api/*.py`。

### 4.1 鉴权 `auth`
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 注册，返回 `LoginResponse`（含 token） |
| POST | `/auth/login` | 登录，返回 token |
| GET  | `/auth/me` | 当前用户信息 |

### 4.2 会话 / 工单
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/sessions` | 会话列表（admin） |
| GET/DELETE | `/sessions/{session_id}` | 会话详情 / 删除 |
| POST | `/chat` | REST 兜底对话端点（主链路为 WebSocket） |

工单 `tickets`：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/tickets` | 工单列表 |
| GET  | `/tickets/stats` | 工单统计 |
| GET  | `/tickets/{ticket_id}` | 工单详情 |
| POST | `/tickets` | 创建工单 |
| PUT  | `/tickets/{ticket_id}` | 更新工单 |
| POST | `/tickets/{ticket_id}/assign` | 分配坐席 |
| POST | `/tickets/{ticket_id}/comments` | 添加备注 |
| POST | `/tickets/{ticket_id}/close` | 关闭工单 |
| DELETE | `/tickets/{ticket_id}` | 删除工单 |

### 4.3 管理后台 `admin`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/admin/sessions` | 全量会话 |
| GET/PUT | `/admin/channels/{channel_name}/config` | 接入渠道配置 + 测试 |
| GET  | `/admin/handoff/queue` | 转人工队列 |
| POST | `/admin/handoff/{session_id}/accept` | 坐席接手 |
| POST | `/admin/handoff/{session_id}/reply` | 坐席回复 |
| POST | `/admin/handoff/{session_id}/close` | 关闭转接 |
| GET  | `/admin/approvals` | HITL 待审批列表 |
| POST | `/admin/approvals/{request_id}/review` | 审批 |

### 4.4 知识库 `knowledge`
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/admin/knowledge` | 新建知识库 |
| GET  | `/admin/knowledge/{kb_id}` | 知识库详情 |
| PUT/DELETE | `/admin/knowledge/{kb_id}` | 更新 / 删除 |
| POST | `/admin/knowledge/{kb_id}/documents` | 上传文档（支持 multipart 上传） |
| POST | `/admin/knowledge/{kb_id}/reindex` | 重建向量索引 |
| POST | `/admin/knowledge/{kb_id}/hit_test` | 检索命中测试 |

### 4.5 RBAC 权限 `rbac`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/rbac/roles` | 角色列表 |
| GET  | `/rbac/permissions` | 权限点列表 |
| GET  | `/rbac/users` | 用户列表 |
| PUT  | `/rbac/users/{user_id}/role` | 调整用户角色 |
| GET  | `/rbac/me/permissions` | 当前用户权限 |

### 4.6 客户 / 满意度
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/customers` | 客户列表 |
| GET  | `/customers/{user_id}/timeline` | 客户时间线 |
| POST | `/satisfaction` | 提交满意度评价 |
| GET  | `/satisfaction/stats` | 满意度统计 |

### 4.7 仪表盘 `dashboard`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/dashboard/kpi` | 核心指标卡 |
| GET  | `/dashboard/realtime` | 实时概览 |
| GET  | `/dashboard/agent-performance` | 坐席绩效 |
| GET  | `/dashboard/intent-distribution` | 意图分布 |

### 4.8 质量评估 `evaluation`
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/admin/evaluation/datasets` | 新建评测数据集 |
| GET  | `/admin/evaluation/datasets` | 数据集列表 |
| POST | `/admin/evaluation/runs` | 发起评测运行 |
| GET  | `/admin/evaluation/runs/{run_id}` | 评测结果 |

### 4.9 可观测性 `monitoring`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/prometheus` | Prometheus 指标拉取 |
| GET  | `/all`、`/business`、`/quality`、`/risk`、`/system` | 多维监控面板数据 |

### 4.10 其他
- `notifications`：站内通知（列表 / 未读数 / 标记已读）。
- `hitl`：人工介入待办（`/admin/hitl/pending`、`/admin/hitl/{thread_id}/resume` 等）。
- `health`：智能体注册与健康（`/agents`、`/agents/{id}/heartbeat`、`/stats`）。
- `config`：运行时配置（特性开关 `features`、分类配置、重置）。
- `chatwoot`：第三方 Chatwoot 集成 webhook（`/chatwoot/webhook`、`/chatwoot/events`）。

---

## 5. 端到端联调示例

### 5.1 curl 健康检查

```bash
curl http://localhost:8000/api/v1/health
```

### 5.2 Python WebSocket 对话（最小可跑）

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8000/ws/chat") as ws:
        # 等待 session_ready
        print(await ws.recv())
        # 发消息
        await ws.send(json.dumps({"type": "chat_message", "message": "你们的产品有哪些核心功能？"}))
        # 收流式回复
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == "streaming_chunk":
                print(msg.get("text", ""), end="", flush=True)
                if msg.get("done"):
                    break

asyncio.run(main())
```

---

## 6. 说明与边界

- **会话由连接隐式创建**：客户端无需预创建 session，`session_ready` 会下发 `session_id`；后续消息可带 `session_id` 续接同一会话。
- **多模态**：`chat_message` 支持 `image_base64` / `audio_base64`，由视觉/语音引擎识别后参与推理。
- **权限过滤**：检索结果按用户 `access_levels`（public/internal/confidential/restricted）过滤，被过滤条数通过 `info` 消息提示。
- **限流与护栏**：REST/WS 均有速率限制与输入长度上限（文本 ≤2000 字符），详见《resume-project.md》"安全护栏 5 层"。
- 完整字段与最新变更以源码 `src/api/`、`src/websocket/` 为准。
