# 账号管理与安全

## 账号创建

### 通过控制台创建

1. 访问 CloudSync 注册页面
2. 输入邮箱地址和密码
3. 验证邮箱（点击确认邮件中的链接）
4. 完成初始设置向导

### 通过 API 创建

```bash
curl -X POST https://api.cloudsync.io/v1/accounts \
  -H "Authorization: Bearer YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "display_name": "张三",
    "plan": "pro"
  }'
```

## 账号恢复

### 忘记密码

1. 在登录页面点击 "Forgot Password"
2. 输入注册邮箱
3. 查收邮件，点击重置链接
4. 设置新密码（密码必须包含大小写字母 + 数字，至少 8 位）

### 邮箱变更

1. 登录控制台
2. 进入 Settings > Account > Email
3. 输入新邮箱地址
4. 验证新邮箱（确认邮件将在 5 分钟内送达）

## 账号删除

### 删除账号

**警告：此操作不可逆。** 删除账号将：
- 永久删除所有同步数据
- 取消所有活跃的同步任务
- 移除所有 SSO 配置
- 删除所有 API Keys

#### 操作步骤

1. 登录控制台
2. 进入 Settings > Account > Delete Account
3. 输入 "DELETE" 确认
4. 输入密码验证身份
5. 等待 30 天冷静期后数据永久删除

#### 通过 API 删除

```bash
curl -X DELETE https://api.cloudsync.io/v1/accounts/me \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"confirm": "DELETE", "password": "your_password"}'
```

## 数据导出

### 导出同步日志

```bash
curl -X GET https://api.cloudsync.io/v1/accounts/me/export/activity-logs \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o activity_logs.json
```

### 导出用户数据

1. 登录控制台
2. 进入 Settings > Account > Export Data
3. 选择要导出的数据类型：
   - 同步配置
   - 活动日志
   - 账单记录
   - API Keys
4. 点击下载链接（链接有效期 24 小时）

## 团队管理

### 添加团队成员

1. 进入 Settings > Team Members
2. 点击 "Add Member"
3. 输入成员邮箱
4. 选择角色：
   - **Owner**: 完全管理权限
   - **Admin**: 管理设置但不能删除账号
   - **Member**: 只能管理自己的同步任务
   - **Viewer**: 只读权限
5. 成员将收到邀请邮件

### 角色权限矩阵

| 操作 | Owner | Admin | Member | Viewer |
|------|-------|-------|--------|--------|
| 管理计费 | ✅ | ✅ | ❌ | ❌ |
| 管理 SSO | ✅ | ✅ | ❌ | ❌ |
| 添加/删除成员 | ✅ | ✅ | ❌ | ❌ |
| 查看活动日志 | ✅ | ✅ | ✅ | ✅ |
| 管理 API Keys | ✅ | ✅ | ❌ | ❌ |
| 创建同步任务 | ✅ | ✅ | ✅ | ❌ |
| 删除同步任务 | ✅ | ✅ | ✅ | ❌ |

## 活动日志

### 查看日志

```bash
curl -X GET "https://api.cloudsync.io/v1/accounts/me/logs?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### 日志字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `timestamp` | 事件发生时间 | `2026-07-01T10:30:00Z` |
| `action` | 操作类型 | `login`, `sync_created`, `api_key_generated` |
| `ip_address` | 来源 IP | `203.0.113.42` |
| `user_agent` | 客户端信息 | `Mozilla/5.0...` |
| `details` | 详细信息 | `{"job_id": "abc123"}` |

### 日志保留策略

- 最近 90 天：在线可查
- 90-365 天：可申请导出
- 超过 365 天：自动归档，不可恢复

## GDPR 合规

### 数据保护

CloudSync 符合 GDPR 要求：
- 数据存储在欧洲区域内（可选美国区域）
- 支持数据主体访问请求（DSAR）
- 支持数据删除请求
- 支持数据可移植性

### 申请数据删除

```bash
curl -X POST https://api.cloudsync.io/v1/gdpr/delete \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason": "user_requested"}'
```

处理时间：1-5 个工作日。
