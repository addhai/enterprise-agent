# API 接口详细文档（P2-2 交付物）

> 本文档覆盖 5 个核心接口的完整定义：请求路径、方法、入参、返回体、错误码、示例。
> 全部端点速查见 `docs/api.md`，本文档为其子集的详细展开。
>
> 源码基准：`src/api/routes.py`、`src/api/conversations.py`、`src/api/knowledge.py`、
> `src/api/admin.py`、`src/api/sessions_service.py`

## 目录

1. [对话发起接口（REST）](#1-对话发起接口rest)
2. [对话发起接口（WebSocket）](#2-对话发起接口websocket)
3. [历史消息读取接口](#3-历史消息读取接口)
4. [知识库文档上传接口](#4-知识库文档上传接口)
5. [RAG 检索接口（命中测试）](#5-rag-检索接口命中测试)
6. [会话清除接口](#6-会话清除接口)
7. [通用错误码表](#7-通用错误码表)

---

## 1. 对话发起接口（REST）

REST 同步对话端点，适合非流式场景（脚本调用、后端间联调）。
产品主链路为 WebSocket 流式对话（见第 2 节）。

### 请求

| 项 | 值 |
|---|---|
| 方法 | `POST` |
| 路径 | `/api/v1/chat` |
| Content-Type | `application/json` |
| 鉴权 | 无（公开接口） |

### 入参

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `message` | string | 是 | 用户消息，长度 1~2000 字符 |
| `session_id` | string | 否 | 会话 ID，不传则服务端生成 UUID |
| `user_id` | string | 否 | 用户 ID，默认 `"anonymous"` |
| `tenant_id` | string | 否 | 租户 ID（多租户隔离），默认空串 |
| `user_access_levels` | string[] | 否 | 权限等级，如 `["public","internal"]`，默认全部四级 |
| `user_roles` | string[] | 否 | 用户角色，如 `["admin"]`，默认空 |
| `user_plan` | string | 否 | 订阅计划 `free`/`pro`/`enterprise`，默认 `free` |

### 请求示例

```json
{
  "message": "你们的产品支持私有化部署吗？",
  "session_id": "3f1c8a2e-0011-4b2c-9d3e-0a1b2c3d4e5f",
  "user_id": "u_001",
  "tenant_id": "tenant_default",
  "user_plan": "pro"
}
```

### 返回体结构

```json
{
  "session_id": "3f1c8a2e-0011-4b2c-9d3e-0a1b2c3d4e5f",
  "reply": "我们支持私有化部署，提供 Docker 镜像和 Helm Chart 两种方案...",
  "needs_human": false,
  "suggest_human": false,
  "intent": "faq"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | string | 会话 ID（与入参一致或服务端生成） |
| `reply` | string | AI 回复全文 |
| `needs_human` | bool | 是否已触发转人工（`true` 时会话已转接） |
| `suggest_human` | bool | 是否建议转人工（用户可主动接受） |
| `intent` | string? | 意图分类：`faq`/`technical`/`human` |

### 错误码

| HTTP | detail | 触发场景 |
|---|---|---|
| 422 | (Pydantic 校验错误数组) | `message` 为空或超 2000 字符 |
| 503 | `工作流未就绪: {e}` | LangGraph 工作流初始化失败 |
| 500 | `Internal error: {str(e)[:200]}` | 对话处理内部异常 |

### curl 示例

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"你们的产品支持私有化部署吗？"}'
```

---

## 2. 对话发起接口（WebSocket）

产品主链路。前端浮动客服组件通过 WebSocket 连接 `/ws/chat`，获得流式回复。

### 连接

| 项 | 值 |
|---|---|
| 协议 | `ws://`（开发）/ `wss://`（生产） |
| 路径 | `/ws/chat` |
| 鉴权 | URL query 参数 `?token=<JWT>`（可选，匿名连接按 `anon-<session_id>` 隔离） |

### 连接后服务端首推

```json
{
  "type": "session_ready",
  "session_id": "3f1c8a2e-0011-4b2c-9d3e-0a1b2c3d4e5f",
  "message": "连接成功",
  "timestamp": 1754120000.0
}
```

### 客户端 -> 服务端

| type | 必填字段 | 可选字段 | 说明 |
|---|---|---|---|
| `chat_message` | `message`(string, 1~2000) | `session_id`、`user_plan`、`image_base64`、`audio_base64` | 发送对话消息（支持多模态） |
| `heartbeat` | 无 | 无 | 心跳保活 |
| `human_escalation` | 无 | `session_id`、`reason` | 用户主动请求转人工 |
| `resume_session` | 无 | `session_id`、`user_plan` | 续接历史会话 |

### 服务端 -> 客户端

| type | 关键字段 | 说明 |
|---|---|---|
| `session_ready` | `session_id` | 连接/新会话就绪 |
| `typing_indicator` | `is_typing`(bool)、`status?` | "正在理解您的问题..." |
| `streaming_chunk` | `text`、`delta`、`done`(bool)、`suggest_human`(bool)、`citations?` | 流式文本片段；`done:true` 结束本轮 |
| `transfer_notice` | `reason`、`estimated_wait_seconds` | 转人工通知 |
| `info` | `text` | 状态提示 |
| `error` | `error_code`、`error_message` | 错误消息 |
| `heartbeat_ack` | `timestamp` | 心跳响应 |

### WebSocket 错误码

| error_code | 触发场景 |
|---|---|
| `INVALID_JSON` | 消息不是合法 JSON |
| `MESSAGE_TOO_LONG` | 消息超 2000 字符 |
| `CHAT_ERROR` | 聊天处理错误 |
| `INTERNAL_ERROR` | 服务端内部异常 |

### 前端参考实现（TypeScript）

```typescript
const ws = new WebSocket('/ws/chat');
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  switch (msg.type) {
    case 'session_ready':    /* 记录 session_id */ break;
    case 'streaming_chunk':  /* 追加 msg.text; done 时收尾 */ break;
    case 'typing_indicator': /* 显示"正在输入..." */ break;
    case 'transfer_notice':  /* 提示转人工 */ break;
    case 'error':            /* 处理错误 */ break;
  }
};
ws.send(JSON.stringify({ type: 'chat_message', message: '你好' }));
```

---

## 3. 历史消息读取接口

读取指定会话的全部对话消息（按时间正序）。

### 请求

| 项 | 值 |
|---|---|
| 方法 | `GET` |
| 路径 | `/api/v1/conversations/{session_id}/messages` |
| 鉴权 | Bearer Token（已登录用户） |
| 权限 | 普通用户只能读自己的会话；admin/agent 可读任意会话 |

### 路径参数

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `session_id` | string | 是 | 会话 ID |

### Query 参数

| 参数名 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | int | 否 | 200 | 返回消息条数上限，范围 1~500 |

### 请求示例

```bash
curl http://localhost:8000/api/v1/conversations/3f1c8a2e/messages?limit=50 \
  -H "Authorization: Bearer eyJhbGciOi..."
```

### 返回体结构

```json
{
  "session_id": "3f1c8a2e-0011-4b2c-9d3e-0a1b2c3d4e5f",
  "count": 4,
  "messages": [
    {
      "role": "user",
      "content": "你们的产品支持私有化部署吗？",
      "timestamp": "2026-09-12T10:30:00"
    },
    {
      "role": "assistant",
      "content": "我们支持私有化部署...",
      "timestamp": "2026-09-12T10:30:05"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | string | 会话 ID |
| `count` | int | 实际返回消息数 |
| `messages` | array | 消息列表（时间正序） |
| `messages[].role` | string | `"user"` 或 `"assistant"` |
| `messages[].content` | string | 消息文本 |
| `messages[].timestamp` | string? | 时间戳（内存会话为 ISO 格式，DB 回退为存储格式） |

### 错误码

| HTTP | detail | 触发场景 |
|---|---|---|
| 401 | `未提供认证令牌` | 无 Authorization header |
| 403 | `无权访问此会话` | 普通用户访问他人会话 |
| 404 | `会话不存在` | session_id 不存在或已过期 |

---

## 4. 知识库文档上传接口

通过 multipart 上传文档文件到指定知识库，自动切块、向量化、入库。

### 请求

| 项 | 值 |
|---|---|
| 方法 | `POST` |
| 路径 | `/api/v1/admin/knowledge/{kb_id}/documents/upload` |
| Content-Type | `multipart/form-data` |
| 鉴权 | Bearer Token |
| 权限 | `admin` 或 `agent` 角色 |

### 路径参数

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `kb_id` | string | 是 | 知识库 ID |

### Query 参数

| 参数名 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `title` | string | 否 | 空串 | 文档标题，不传则用文件名 |

### Body 参数（multipart）

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 上传的文档文件（支持 .md / .txt / .pdf / .docx） |

### 请求示例

```bash
curl -X POST \
  "http://localhost:8000/api/v1/admin/knowledge/kb_001/documents/upload?title=产品手册v2" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -F "file=@/path/to/product_manual_v2.md"
```

### 返回体结构

```json
{
  "success": true,
  "document": {
    "id": "doc_a1b2c3d4",
    "title": "产品手册v2",
    "source_type": "document",
    "status": "indexed",
    "chunk_count": 42,
    "file_path": "/app/chroma_data/uploads/kb_001/product_manual_v2.md",
    "created_at": "2026-09-12T10:35:00"
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `success` | bool | 是否上传成功 |
| `document.id` | string | 文档唯一 ID |
| `document.title` | string | 文档标题 |
| `document.source_type` | string | 来源类型：`document` |
| `document.status` | string | 索引状态：`indexed`/`pending`/`failed` |
| `document.chunk_count` | int | 切块数量 |
| `document.file_path` | string | 服务器端存储路径 |
| `document.created_at` | string | 入库时间 |

### 错误码

| HTTP | detail | 触发场景 |
|---|---|---|
| 401 | `未提供认证令牌` | 无 Authorization header |
| 403 | `当前角色无权限执行此操作` | 非 admin/agent 角色 |
| 404 | `知识库不存在: {kb_id}` | kb_id 不存在 |
| 400 | `参数错误: {e}` | 文档解析/切块失败 |
| 500 | `文件保存失败: {e}` | 磁盘写入失败 |

---

## 5. RAG 检索接口（命中测试）

在指定知识库范围内执行 RAG 检索，返回 top_k 命中结果，用于验证检索效果。

### 请求

| 项 | 值 |
|---|---|
| 方法 | `POST` |
| 路径 | `/api/v1/admin/knowledge/{kb_id}/hit_test` |
| Content-Type | `application/json` |
| 鉴权 | Bearer Token |
| 权限 | `admin` 或 `agent` 角色 |

### 路径参数

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `kb_id` | string | 是 | 知识库 ID |

### Body 入参

| 参数名 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 | 无 | 测试查询，长度 1~500 |
| `top_k` | int | 否 | 3 | 返回条数，范围 1~20 |

### 请求示例

```bash
curl -X POST \
  "http://localhost:8000/api/v1/admin/knowledge/kb_001/hit_test" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -H "Content-Type: application/json" \
  -d '{"query":"如何校准设备","top_k":5}'
```

### 返回体结构

```json
{
  "kb_id": "kb_001",
  "query": "如何校准设备",
  "top_k": 5,
  "total_hits": 3,
  "hits": [
    {
      "content": "校准前准备：环境温度 20 +/- 3 C，相对湿度 <= 60% RH...",
      "score": 1.0,
      "source": "calibration_guide.md",
      "metadata": {
        "chunk_index": 42,
        "source_file": "calibration_guide.md",
        "chunk_type": "standard"
      }
    },
    {
      "content": "校准步骤：1. 开机预热 30 分钟...",
      "score": 0.8462,
      "source": "calibration_guide.md",
      "metadata": {
        "chunk_index": 43,
        "source_file": "calibration_guide.md",
        "chunk_type": "standard"
      }
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `kb_id` | string | 知识库 ID |
| `query` | string | 原始查询 |
| `top_k` | int | 请求的 top_k |
| `total_hits` | int | 实际命中条数 |
| `hits[].content` | string | 命中片段文本（截断至 300 字符） |
| `hits[].score` | float | 归一化相关性分数（0~1，top1=1.0） |
| `hits[].source` | string | 来源文件名 |
| `hits[].metadata` | object | chunk 元数据（chunk_index、chunk_type 等） |

### 错误码

| HTTP | detail | 触发场景 |
|---|---|---|
| 401 | `未提供认证令牌` | 无 Authorization header |
| 403 | `当前角色无权限执行此操作` | 非 admin/agent 角色 |
| 404 | `知识库不存在: {kb_id}` | kb_id 不存在 |
| 422 | (Pydantic 校验错误) | query 为空或超 500 字符 |
| 503 | `检索器未安装: {e}` | HybridRetriever 导入失败 |
| 503 | `检索器初始化失败: {e}` | 向量库连接失败 |
| 500 | `检索失败: {e}` | 检索过程异常 |

---

## 6. 会话清除接口

删除指定会话及其全部消息，同时从内存与持久化 DB 清除。

提供两个端点，权限粒度不同：

### 6.1 用户端：删除自己的会话

| 项 | 值 |
|---|---|
| 方法 | `DELETE` |
| 路径 | `/api/v1/sessions/{session_id}` |
| 鉴权 | Bearer Token（可选登录） |
| 权限 | 只能删除自己的会话 |

#### 路径参数

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `session_id` | string | 是 | 会话 ID |

#### 请求示例

```bash
curl -X DELETE \
  http://localhost:8000/api/v1/sessions/3f1c8a2e-0011-4b2c-9d3e-0a1b2c3d4e5f \
  -H "Authorization: Bearer eyJhbGciOi..."
```

#### 返回体

```json
{
  "success": true,
  "message": "会话已删除"
}
```

#### 错误码

| HTTP | detail | 触发场景 |
|---|---|---|
| 403 | `无权删除此会话` | 尝试删除他人会话 |
| 404 | `会话不存在: {session_id}` | session_id 不存在 |

### 6.2 管理端：删除任意会话

| 项 | 值 |
|---|---|
| 方法 | `DELETE` |
| 路径 | `/api/v1/conversations/{session_id}` |
| 鉴权 | Bearer Token |
| 权限 | `admin` 或 `agent` 角色 |

#### 路径参数

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `session_id` | string | 是 | 会话 ID |

#### 请求示例

```bash
curl -X DELETE \
  http://localhost:8000/api/v1/conversations/3f1c8a2e-0011-4b2c-9d3e-0a1b2c3d4e5f \
  -H "Authorization: Bearer eyJhbGciOi..."
```

#### 返回体

```json
{
  "success": true,
  "session_id": "3f1c8a2e-0011-4b2c-9d3e-0a1b2c3d4e5f"
}
```

#### 错误码

| HTTP | detail | 触发场景 |
|---|---|---|
| 401 | `未提供认证令牌` | 无 Authorization header |
| 403 | `需要以下角色之一: [admin, agent]` | 权限不足 |
| 404 | `会话不存在` | session_id 不存在 |

---

## 7. 通用错误码表

### 7.1 HTTP 状态码

| 状态码 | 含义 | 典型场景 |
|---|---|---|
| 200 | 成功 | 正常请求 |
| 400 | 参数错误 | 校验失败、冲突操作 |
| 401 | 未认证 | token 缺失/过期/无效 |
| 403 | 权限不足 | 角色/权限校验失败 |
| 404 | 资源不存在 | 会话/知识库/工单不存在 |
| 409 | 资源冲突 | 并发认领冲突、重复创建 |
| 422 | 实体校验错误 | Pydantic 字段校验不通过 |
| 500 | 服务器内部错误 | 未捕获异常 |
| 503 | 服务不可用 | 依赖未就绪（工作流/检索器） |

### 7.2 认证错误明细

| HTTP | detail | 触发条件 |
|---|---|---|
| 401 | `未提供认证令牌` | 无 Authorization header |
| 401 | `认证令牌格式错误` | 非 `Bearer ` 前缀 |
| 401 | `认证令牌无效或已过期` | JWT 验签失败或过期 |
| 401 | `用户名或密码错误` | 登录失败 |
| 403 | `账号已被禁用` | 用户状态为 suspended |
| 403 | `权限不足，缺少: xxx` | require_permissions 校验失败 |
| 403 | `当前角色无权限执行此操作` | require_role 校验失败 |
| 403 | `需要以下角色之一: [...]` | require_roles 校验失败 |
| 403 | `无权访问此会话` | 会话归属校验 |
| 403 | `无权管理其他租户的用户` | 跨租户操作 |

### 7.3 标准错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

Pydantic 422 校验错误：

```json
{
  "detail": [
    {
      "type": "value_error.missing",
      "loc": ["body", "message"],
      "msg": "field required",
      "input": {}
    }
  ]
}
```
