# 计费与订阅管理

## 定价方案

| 方案 | 价格 | 存储空间 | 服务商 | 同步任务 | 支持 |
|------|------|---------|--------|---------|------|
| Free | 免费 | 5 GB | 2 个 | 手动 | 社区 |
| Pro | $15/月 | 100 GB | 5 个 | 实时 | 邮件支持 |
| Business | $50/用户/月 | 1 TB/用户 | 不限 | 实时 + 调度 | 优先邮件 |
| Enterprise | 联系销售 | 不限 | 不限 | 实时 + 调度 + 自定义 | 专属客户经理 |

## 订阅变更

### 升级

1. 登录控制台 → Settings > Billing > Change Plan
2. 选择目标方案
3. 确认支付信息
4. 升级立即生效，费用按剩余天数折算

```bash
curl -X PUT https://api.cloudsync.io/v1/billing/subscription \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "plan": "pro",
    "billing_cycle": "monthly"
  }'
```

### 降级

1. 登录控制台 → Settings > Billing > Change Plan
2. 选择目标方案
3. 降级在当前计费周期结束后生效
4. 如果超出新方案限额，同步任务将暂停

### 取消订阅

1. 登录控制台 → Settings > Billing > Cancel Subscription
2. 选择取消原因
3. 确认取消
4. 账户保留到当前计费周期结束
5. 数据保留 30 天后删除

**注意：** 取消订阅后，所有进行中的同步任务将被取消。

## 发票与账单

### 查看账单

1. 登录控制台 → Settings > Billing > Invoices
2. 选择月份查看明细
3. 支持下载 PDF 格式发票

### 账单字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `invoice_number` | 发票编号 | INV-2026-0701-001 |
| `issue_date` | 开票日期 | 2026-07-01 |
| `due_date` | 付款日期 | 2026-07-31 |
| `plan` | 订阅方案 | Pro |
| `storage_gb` | 使用存储（GB） | 45.2 |
| `overage_charge` | 超额费用 | $0.00 |
| `tax` | 税费 | $1.20 |
| `total` | 总金额 | $16.20 |

### API 获取账单

```bash
# 获取当月账单
curl -X GET https://api.cloudsync.io/v1/billing/invoices/current \
  -H "Authorization: Bearer YOUR_API_KEY"

# 获取指定月份账单
curl -X GET https://api.cloudsync.io/v1/billing/invoices/2026-07 \
  -H "Authorization: Bearer YOUR_API_KEY"
```

## 超额使用

### 存储超额

| 方案 | 免费额度 | 超额价格 |
|------|---------|---------|
| Pro | 100 GB | $0.02/GB/月 |
| Business | 1 TB/用户 | $0.01/GB/月 |
| Enterprise | 不限 | 不限 |

超额时：
1. 系统发送通知邮件
2. 下次账单自动加收超额费用
3. 超额 > 20% 时暂停同步任务
4. 超额 > 50% 时暂停所有操作（除登录外）

### API 调用超额

| 方案 | 每小时限制 | 超额处理 |
|------|-----------|---------|
| Free | 100 | 返回 429 |
| Pro | 1000 | 返回 429 |
| Business | 5000 | 返回 429 |
| Enterprise | 10000 | 可协商 |

## 退款政策

### 退款条件

- 订阅后 7 天内可全额退款
- 年度订阅使用超过 30 天后按比例退款
- 企业合同按合同约定执行

### 申请退款

```bash
curl -X POST https://api.cloudsync.io/v1/billing/refund \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "product_not_suitable",
    "amount": 15.00
  }'
```

处理时间：3-5 个工作日。

## 税务信息

### 税率

| 地区 | VAT/GST | 税率 |
|------|---------|------|
| 美国 | Sales Tax | 0-10%（按州） |
| 欧盟 | VAT | 19-27%（按国家） |
| 中国 | VAT | 6% |
| 英国 | VAT | 20% |

### 税务设置

1. 登录控制台 → Settings > Billing > Tax
2. 输入 VAT/GST 号码
3. 选择税号验证方式（VIES for EU）
4. 保存后下次账单自动应用

**注意：** 未提供税号的用户将被收取默认税率。
