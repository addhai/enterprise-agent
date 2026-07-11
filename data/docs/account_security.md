# 密码与账户安全 / Account Security

## Reset Password / sync not working / two factor authentication

## 重置密码

1. 访问登录页面
2. 点击 "忘记密码" 链接
3. 输入您的注册邮箱地址
4. 查收重置邮件（有效期 30 分钟）
5. 点击邮件中的链接，设置新密码

**注意：** 重置链接仅可使用一次。如果多次请求重置，请检查垃圾邮件文件夹。

## 启用两步验证 (2FA)

1. 登录控制台
2. 进入 Settings > Security > Two-Factor Authentication
3. 选择验证方式：
   - **验证器应用**（推荐）：使用 Google Authenticator 或 Microsoft Authenticator
   - **短信验证**：接收短信验证码
4. 扫描 QR 码或输入密钥
5. 输入验证码确认

**安全建议：** 推荐使用验证器应用，比短信更安全。

## 同步任务失败排查

如果同步任务无法正常执行，请按以下步骤排查：

### 1. 检查服务商认证状态
- 登录控制台 > Settings > Providers
- 确认所有需要的服务商已认证且状态正常
- 如显示 "Expired"，请重新授权

### 2. 检查存储空间
- 登录控制台 > Settings > Storage
- 确认剩余空间充足
- 免费计划：5GB，专业版：100GB，企业版：无限

### 3. 检查文件锁定
- 确认要同步的文件没有被其他程序或进程锁定
- 在 Windows 上，某些杀毒软件可能会锁定文件

### 4. 检查网络连接
- 确认网络连接稳定
- 如需代理，请在控制台配置代理设置

### 5. 查看详细日志
- 登录控制台 > Settings > Sync Jobs > [任务名称]
- 点击 "View Logs" 查看详细错误信息
