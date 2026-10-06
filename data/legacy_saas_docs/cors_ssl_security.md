# CORS 与安全配置

## CORS 配置

### 概述

CloudSync API 使用 CORS（跨域资源共享）来控制哪些域名可以调用 API。这是防止 CSRF 攻击和保护 API 安全的重要机制。

### 配置步骤

1. 登录 CloudSync Admin Console
2. 进入 Settings > Security > CORS
3. 点击 "Add Allowed Origin"
4. 输入允许的域名：
   - 完整域名：`https://app.example.com`
   - 通配符：`https://*.example.com`
   - 本地开发：`http://localhost:3000`
5. 点击 "Save"

### 允许的请求头

| 请求头 | 说明 | 是否必需 |
|--------|------|---------|
| `Authorization` | API Key / OAuth Token | 是 |
| `Content-Type` | 请求体类型 | 是 |
| `X-Request-ID` | 请求追踪 ID | 否 |
| `X-Correlation-ID` | 链路追踪 ID | 否 |

### 允许的 HTTP 方法

| 方法 | 用途 | 是否需要预检 |
|------|------|-------------|
| GET | 查询数据 | 否 |
| POST | 创建资源 | 是 |
| PUT | 更新资源 | 是 |
| DELETE | 删除资源 | 是 |
| PATCH | 部分更新 | 是 |

### 常见 CORS 错误

**错误 1: CORS 预检失败**

```
Access to XMLHttpRequest at 'https://api.cloudsync.io/v1/sync/jobs'
from origin 'https://app.example.com' has been blocked by CORS policy:
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

**原因：** 域名未在 CORS 白名单中。

**修复：**
1. 在 Admin Console 中添加 `https://app.example.com`
2. 等待 5 分钟生效
3. 清除浏览器缓存后重试

**错误 2: 请求头不被允许**

```
Request header field authorization is not allowed by Access-Control-Allow-Headers
```

**原因：** 自定义请求头未在 CORS 配置中声明。

**修复：**
1. 检查请求头是否在允许的列表中
2. 如需自定义头，联系技术支持添加

**错误 3: 凭证问题**

```
The value of the 'Access-Control-Allow-Credentials' header in the response is ''
which must be 'true' when the request's credentials mode is 'include'.
```

**原因：** 浏览器要求带凭证的请求必须明确允许。

**修复：** 在前端代码中设置 `credentials: 'include'`：

```javascript
fetch('https://api.cloudsync.io/v1/sync/jobs', {
  credentials: 'include',
  headers: {
    'Authorization': 'Bearer cs_live_xxx',
  },
});
```

## SSL/TLS 证书

### 证书信息

| 属性 | 值 |
|------|-----|
| CA | Let's Encrypt / DigiCert |
| 协议 | TLS 1.2 / TLS 1.3 |
|  cipher suite | AES-256-GCM / ChaCha20-Poly1305 |
| 密钥交换 | ECDHE (P-256 / X25519) |
| 证书有效期 | 90 天（自动续签） |

### 验证证书

```bash
# 检查证书链
openssl s_client -connect api.cloudsync.io:443 -servername api.cloudsync.io

# 验证证书有效期
curl -vI https://api.cloudsync.io/v1/health 2>&1 | grep -i "subject\|expire"

# 检查 TLS 版本
openssl s_client -connect api.cloudsync.io:443 -tls1_3
```

### 自签名证书

CloudSync API **不支持**自签名证书。所有连接必须使用有效的 CA 签发证书。

## API Key 安全

### 最佳实践

1. **不要硬编码** — 使用环境变量或密钥管理服务
2. **定期轮换** — 每 90 天更换一次 API Key
3. **最小权限** — 为每个应用使用独立的 API Key
4. **IP 白名单** — 限制 API Key 的使用来源 IP
5. **监控异常** — 定期检查 API Key 的使用日志

### API Key 格式

```
cs_live_xxxxxxxxxxxxxxxx    # 生产环境 Key
cs_test_xxxxxxxxxxxxxxxx    # 测试环境 Key
cs_revoked_xxxxxxxxxxxxxxxx # 已吊销 Key
```

### 吊销 API Key

```bash
curl -X POST https://api.cloudsync.io/v1/api-keys/revoke \
  -H "Authorization: Bearer YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "key_id": "key_abc123",
    "reason": "compromised"
  }'
```

吊销后：
- 旧 Key 立即失效
- 所有使用该 Key 的会话被终止
- 自动发送安全通知邮件

## 安全审计日志

### 查看审计日志

```bash
curl -X GET "https://api.cloudsync.io/v1/accounts/me/audit-logs?limit=50" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### 日志事件类型

| 事件类型 | 严重等级 | 说明 |
|---------|---------|------|
| `login.success` | 低 | 用户登录成功 |
| `login.failure` | 中 | 登录失败（密码错误） |
| `login.mfa_failure` | 高 | MFA 验证失败 |
| `api_key.created` | 中 | 新 API Key 创建 |
| `api_key.revoked` | 中 | API Key 吊销 |
| `permission.change` | 高 | 权限变更 |
| `data.export` | 中 | 数据导出 |
| `account.deleted` | 高 | 账号删除 |

### 告警规则

| 规则 | 条件 | 通知方式 |
|------|------|---------|
| 登录失败过多 | 5 次失败/5 分钟 | 邮件 + 短信 |
| 异常地理位置 | 新国家/地区登录 | 邮件 + 确认 |
| API Key 异常使用 | 短时间大量请求 | 邮件 |
| 权限变更 | 任何人修改权限 | 邮件 + 管理员确认 |
