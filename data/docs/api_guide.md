# CloudSync API Guide

## Authentication
CloudSync API uses API Key authentication. Generate keys at: Console > Developer Settings > API Keys.

Include the key in HTTP headers:
```
Authorization: Bearer cs_live_xxxxxxxxxxxxxxxx
```

## Rate Limits
- Free plan: 100 requests/hour
- Pro plan: 1000 requests/hour
- Enterprise: 10000 requests/hour

## Core Endpoints

### List Files
GET /api/v1/files
Query: ?folder_id=123&page=1&per_page=50

### Upload File
POST /api/v1/files/upload
Content-Type: multipart/form-data

### Sync Status
GET /api/v1/sync/status

## Error Codes
| Code | Description |
|------|-------------|
| 401 | Invalid API Key |
| 403 | Access Denied (check API Key permissions and domain whitelist) |
| 429 | Rate Limit Exceeded |
| 500 | Internal Server Error |

## Python SDK
```python
from cloudsync import CloudSyncClient

client = CloudSyncClient(api_key="cs_live_xxx")
client.connect_dropbox()
client.start_sync(source="Dropbox", target="OneDrive")
```
