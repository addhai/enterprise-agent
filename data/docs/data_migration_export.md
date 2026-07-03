# 数据迁移与导出

## 数据导出

### 导出同步配置

```bash
curl -X GET https://api.cloudsync.io/v1/accounts/me/export/sync-config \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o sync_config.json
```

导出的内容包括：
- 所有同步任务配置
- 连接的服务商信息
- 过滤器和调度设置
- 同步历史记录

### 导出活动日志

```bash
curl -X GET "https://api.cloudsync.io/v1/accounts/me/export/activity-logs?from=2026-01-01&to=2026-07-01" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o activity_logs.json
```

### 导出用户数据（GDPR）

```bash
curl -X POST https://api.cloudsync.io/v1/gdpr/export \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "format": "json",
    "include": ["sync_configs", "activity_logs", "billing_history"]
  }'
```

处理完成后，下载链接将通过邮件发送（有效期 7 天）。

## 数据迁移

### 服务商迁移

#### Dropbox → OneDrive

```bash
curl -X POST https://api.cloudsync.io/v1/sync/jobs \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Dropbox to OneDrive Migration",
    "source": {
      "provider": "onedrive",
      "folder": "/Migration Source"
    },
    "target": {
      "provider": "dropbox",
      "folder": "/Migration Target"
    },
    "schedule": "once",
    "options": {
      "conflict_resolution": "newest_wins",
      "preserve_metadata": true,
      "dry_run": false
    }
  }'
```

#### Google Drive → Amazon S3

```bash
curl -X POST https://api.cloudsync.io/v1/sync/jobs \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GDrive to S3 Migration",
    "source": {
      "provider": "s3",
      "bucket": "my-migration-bucket",
      "region": "us-east-1"
    },
    "target": {
      "provider": "gdrive",
      "folder": "/Migration Target"
    },
    "schedule": "once",
    "options": {
      "conflict_resolution": "newest_wins",
      "preserve_metadata": true,
      "max_file_size": "5GB"
    }
  }'
```

### 批量迁移

```bash
curl -X POST https://api.cloudsync.io/v1/migrations/batch \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Enterprise Migration Q3",
    "jobs": [
      {
        "source": {"provider": "dropbox", "folder": "/Team"},
        "target": {"provider": "onedrive", "folder": "/Team"}
      },
      {
        "source": {"provider": "gdrive", "folder": "/Projects"},
        "target": {"provider": "s3", "bucket": "project-backup"}
      }
    ],
    "options": {
      "conflict_resolution": "newest_wins",
      "preserve_metadata": true,
      "notify_on_complete": true,
      "notify_email": "admin@example.com"
    }
  }'
```

### 迁移状态监控

```bash
# 查看迁移任务状态
curl -X GET https://api.cloudsync.io/v1/migrations/mig_abc123/status \
  -H "Authorization: Bearer YOUR_API_KEY"

# 响应
{
  "id": "mig_abc123",
  "status": "running",
  "progress": {
    "total_files": 15000,
    "processed_files": 8500,
    "failed_files": 12,
    "bytes_transferred": 45678901234
  },
  "estimated_completion": "2026-07-02T14:30:00Z"
}
```

## 数据导入

### 从 CSV 导入同步配置

```bash
curl -X POST https://api.cloudsync.io/v1/accounts/me/import/sync-configs \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@configs.csv" \
  -F "mode=upsert"
```

CSV 格式：

```csv
name,source_provider,target_provider,source_folder,target_folder,schedule
Daily Backup,dropbox,onedrive,/Backup,/Backup,daily
Weekly Sync,gdrive,s3,/Projects,project-backups,weekly
```

### 从 JSON 导入

```bash
curl -X POST https://api.cloudsync.io/v1/accounts/me/import/sync-configs \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d @configs.json
```

## 数据保留策略

| 数据类型 | 保留期限 | 可配置 |
|---------|---------|--------|
| 同步日志 | 90 天 | 否 |
| 活动日志 | 365 天 | 是（最长 3 年） |
| 同步任务配置 | 永久 | 否 |
| API 调用日志 | 30 天 | 否 |
| 审计日志 | 7 年 | 否（合规要求） |
| 用户数据 | 账号删除后 30 天 | 否 |
| 备份数据 | 按备份策略 | 是 |

## 常见问题

**Q: 迁移过程中断怎么办？**
A: 迁移支持断点续传。重新提交相同的迁移任务即可从断点继续。

**Q: 迁移失败的文件如何处理？**
A: 失败的文件会被记录到 `failed_files.json`，包含错误原因和重试建议。

**Q: 迁移需要停机吗？**
A: 不需要。迁移在后台进行，不影响正常使用。

**Q: 可以回滚迁移吗？**
A: 迁移不可自动回滚。建议在迁移前导出配置备份。
