# Webhook 配置指南

## 概述

CloudSync 支持通过 Webhook 将事件实时推送到您的服务器。当同步任务完成、文件变更或发生错误时，系统会自动发送 HTTP POST 请求到您的配置端点。

## 支持的 Webhook 事件

| 事件类型 | 触发条件 | Payload 示例 |
|---------|---------|-------------|
| `sync.completed` | 同步任务成功完成 | `{"event": "sync.completed", "job_id": "abc123", "files": 42}` |
| `sync.failed` | 同步任务失败 | `{"event": "sync.failed", "job_id": "abc123", "error": "timeout"}` |
| `file.changed` | 文件被修改 | `{"event": "file.changed", "file_id": "xyz789", "action": "updated"}` |
| `provider.connected` | 新提供者已连接 | `{"event": "provider.connected", "provider": "dropbox"}` |
| `provider.disconnected` | 提供者已断开 | `{"event": "provider.disconnected", "provider": "gdrive"}` |

## 配置步骤

### 1. 创建 Webhook 端点

您的服务器需要接收 POST 请求并返回 `200 OK`：

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/webhook/cloudsync', methods=['POST'])
def handle_webhook():
    data = request.json
    event = data.get('event')
    job_id = data.get('job_id')
    
    if event == 'sync.completed':
        # 处理同步完成事件
        print(f"Sync {job_id} completed!")
    elif event == 'sync.failed':
        # 处理同步失败事件
        print(f"Sync {job_id} failed: {data.get('error')}")
    
    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(port=5000)
```

### 2. 在 CloudSync 控制台配置

1. 登录 CloudSync Admin Console
2. 进入 Settings > Webhooks
3. 点击 "Add Webhook"
4. 输入您的端点 URL（如 `https://your-server.com/webhook/cloudsync`）
5. 选择要订阅的事件类型
6. 设置 Secret Key（用于签名验证）
7. 点击 "Save"

### 3. 验证签名

CloudSync 会在请求头中添加 `X-CloudSync-Signature`，您需要验证以确保请求来自 CloudSync：

```python
import hmac
import hashlib

def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """验证 CloudSync Webhook 签名"""
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

## 重试策略

- 首次失败：5 秒后重试
- 第二次失败：30 秒后重试
- 第三次失败：5 分钟后重试
- 最多重试 5 次，之后标记为 "failed" 并在控制台告警

## 常见问题

**Q: Webhook 没有收到事件？**
A: 检查以下几点：
1. 端点 URL 是否正确且可公开访问
2. 防火墙是否允许出站 HTTPS 请求
3. 端点是否返回 200 状态码
4. 签名验证是否通过

**Q: 如何禁用某个事件的 Webhook？**
A: 在 Webhooks 设置页面取消勾选对应的事件类型。

**Q: Webhook 有频率限制吗？**
A: 每个 Webhook 端点每秒最多接收 100 个事件。超过限制会触发 429 响应。
