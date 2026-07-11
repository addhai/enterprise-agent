# 版本冲突处理指南

## 什么是版本冲突

当同一文档存在多个活跃版本时，系统会检测到版本冲突。常见场景：
- 同一配置文档有多个修订版本同时生效
- SDK 文档同时存在 v2 和 v3 版本
- API 文档有多个并行维护版本

## 冲突检测机制

系统自动检测版本冲突的流程：
1. 按 source（文件名）分组文档
2. 每组内按 version 字段排序（升序：旧→新）
3. 过滤 status="deprecated" 或 "superseded" 的版本
4. 保留每组中最新的有效版本
5. 如果同一组有多个活跃版本 → 标记 conflict 并提示用户

## 如何处理版本冲突

### 方式 1：自动选择最新版本（推荐）

系统在检索时自动选择最新版本。当检测到冲突时，会在 metadata 中标注：

```json
{
  "has_conflicts": true,
  "version_conflicts": [
    "冲突：文档 sdk_install.md 有多个活跃版本 (v2.0, v3.0)，已选择最新版本 v3.0。请确认是否需要切换到其他版本。"
  ]
}
```

### 方式 2：手动指定版本

在检索时通过 filter_by 指定版本：

```python
results = retriever.search(
    query="SDK 安装",
    filter_by={"version": "v2.0"}  # 强制指定版本
)
```

### 方式 3：查看所有冲突版本

```python
results = retriever.search_with_scores("SDK 安装", top_k=10)
for doc, score in results:
    if doc.metadata.get("has_conflicts"):
        print("Conflict:", doc.metadata.get("version_conflicts", []))
```

## 预防版本冲突的最佳实践

1. **文档更新时标记旧版本为废弃**：将旧版本的 status 设为 "deprecated"
2. **使用语义化版本号**：v1.0, v2.0, v3.0 便于系统排序
3. **定期清理废弃文档**：删除或归档不再使用的版本
4. **在文档头部注明适用版本**：帮助用户快速识别
