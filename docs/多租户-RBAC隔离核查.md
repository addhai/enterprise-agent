# 多租户 + RBAC 隔离核查报告

> 核查日期：2026-08-07
> 核查目标：对标「阿里云智能客服」4 条硬性规定之一——**多租户 + RBAC** 是否已真正贯穿并隔离
> 核查方式：静态代码走查（`grep` + 关键文件精读）+ 运行态观察（uvicorn `:8000` 已起，WS 已实测）

---

## 一、核查结论速览

| 维度 | 结论 |
|---|---|
| 多租户**机制**是否贯穿全链路 | ✅ 是（所有表/API/RAG 都有 `tenant_id` 概念） |
| 多租户**运行态**是否真多租户 | ⚠️ 否——实际只有 `default` 一个租户在跑 |
| RBAC 角色/权限点是否实现 | ✅ 是（5 角色 + 17 权限点 + 依赖注入） |
| RBAC 是否带**租户维度** | ❌ 否——角色只认 `role`，不认 `tenant`，靠数据层 `tenant_id` 过滤兜底 |
| 跨租户**数据越权**是否被挡 | ✅ SQL 级过滤（Ticket/KB/Conversation）；⚠️ 向量检索有空 tenant 后门 |

**一句话结论**：多租户是「架构就绪但未运行化」——代码框架完整支持，但当前所有用户/数据都活在 `default` 租户里，没有「创建租户 / 用户归属租户 / API 从 JWT 动态取 tenant」这套运行时逻辑，因此**没有真实的跨租户隔离验证场景**。

---

## 二、多租户（tenant_id）各层现状

### 2.1 DB 模型层 ✅
`src/db/models.py`：User / KnowledgeBase / KbDocument / Conversation / Message / Ticket / Evaluation… **全部带 `tenant_id = Column(String(64), default="default", index=True)`**。

### 2.2 DB 查询层（Repositories）✅ 真隔离
`src/db/repositories.py` 全部用 **SQL 级**过滤（不是取回内存再 filter）：
```python
# repositories.py:437 ticket_get
row = (s.query(Ticket)
       .filter(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
       .first())
# repositories.py:475 ticket_list
if filter.tenant_id:
    q = q.filter(Ticket.tenant_id == filter.tenant_id)
# repositories.py:233/243/251 KbDocument / KnowledgeBase 同理
```
→ 跨租户查询在数据库层就被截断，正确。

### 2.3 知识库（KB）API 层 ✅ 真隔离
`src/api/knowledge.py`：
```python
_DEFAULT_TENANT = "default"
def _get_tenant_id(current_user):
    return current_user.get("tenant_id") or _DEFAULT_TENANT
```
且 `_kb_set_store` / `_kb_store` 都按 tenant 分区（`_kb_set_store.get(tenant_id, kb_id)`）。
→ 不同租户的知识库/文档物理隔离，**这是全系统做最彻底的一层**。

### 2.4 工单（Ticket）API 层 ⚠️ 硬编码 default
`src/api/tickets.py` 大量端点**写死 `tenant_id="default"`**：
```python
# tickets.py:123 / 160 / 211 / 224
all_tickets = store.list(TicketListFilter(tenant_id="default", limit=10000))
ticket = store.get(ticket_id, tenant_id="default")
existing = store.get(ticket_id, tenant_id="default")
ticket = store.update(ticket_id, tenant_id="default", req=request)
```
→ 即使 repositories 支持多租户，API 层也只查 default，多租户能力**未被激活**。

### 2.5 向量检索（RAG Retriever）层 ⚠️ 空 tenant 后门
`src/rag/retriever.py:670-677`：
```python
doc_tenant = meta.get("tenant_id", "")
if doc_tenant and doc_tenant != tenant_id:
    # 文档属于其他租户，跳过
    continue
```
**漏洞**：当 `doc_tenant == ""`（文档未打 tenant 标签）时，条件不成立 → **该文档对所有租户可见**。
→ 如果某租户文档漏打 `tenant_id`，隔离形同虚设。当前因为全在 default 所以无害，但多租户运行化后这是高危点。

### 2.6 WebSocket 入口 ⚠️ 匿名共享空租户
`src/websocket/routes.py:68`：
```python
user_id = "anonymous"
tenant_id = ""   # 匿名用户 tenant_id 为空
```
匿名用户之间**完全没有租户隔离**（都在空租户里），且能看所有空 tenant 标记的文档。
→ 对标阿里云坐席场景通常强制登录，匿名仅 demo 用，但要写清楚这是 demo 简化。

### 2.7 租户管理端点 ❌ 不存在
全仓 `grep "tenant"` 在 `src/api/*.py`：**没有任何「创建租户 / 切换租户 / 租户列表」端点**。
`tenant_id` 来源于 JWT payload / user dict 的 `tenant_id` 字段，但注册/登录链路没有「归属到非 default 租户」的逻辑。
→ 这是「运行化」缺失的根因。

---

## 三、RBAC 现状

### 3.1 角色与权限点 ✅
`src/api/rbac.py`：
- **5 角色**：`super_admin` / `admin` / `agent` / `viewer` / `supervisor`
- **17 权限点**：`dashboard:view` `customer:view/manage` `ticket:view/manage/assign` `agent:workspace` `satisfaction:view` `knowledge:view/manage` `channel:view/manage` `user:view/manage` `notification:view` `config:view/manage` `evaluation:view/manage` `workflow:view/manage`
- **映射**：`ROLE_PERMISSIONS: Dict[UserRole, List[Permission]]` 严格绑定（super_admin 拿全部）

### 3.2 校验机制 ✅
- `require_permissions(*perms)` 依赖注入工厂（`rbac.py:154`）
- `require_role(*roles)` / `require_roles`（`rbac.py:173/199`）
- `super_admin` 自动通过所有校验（向后兼容，`rbac.py:207`）
- 工单层有**角色级数据过滤**（`tickets.py:97-99` agent 只看自己分配的工单；`tickets.py:216-222` agent 不能关非自己的工单）

### 3.3 缺失：租户维度 ❌
RBAC 只认 `role`，**不认 `tenant`**。即：
- tenant-A 的 `admin` 和 tenant-B 的 `admin` 权限完全一样
- 跨租户越权防护**完全依赖数据层 `tenant_id` 过滤**（repositories SQL 级）
- 如果某 API 漏传 `tenant_id`（如 `ticket_list` 的 `if filter.tenant_id:` 分支），RBAC 不会补刀

---

## 四、已验证项（如何确认上面的结论）

1. **SQL 级过滤**：精读 `repositories.py` 确认 `.filter(Tenant.tenant_id == tenant_id)` 在 query 构造期生效，非内存后过滤。
2. **KB 真隔离**：`knowledge.py` 的 `_get_tenant_id` 从 JWT 用户取 tenant，store 按 `(tenant_id, kb_id)` 分区。
3. **RBAC 生效**：`tickets.py` 用 `require_roles(Role.ADMIN, Role.AGENT)`，且 agent 角色数据过滤在代码层可见。
4. **运行态单租户**：`tickets.py` 全硬编码 `tenant_id="default"`，无租户管理端点 → 实际只有 default 在跑（与之前的 WS 实测 `tenant_id="default"` 一致）。
5. **空 tenant 后门**：代码走查确认 `retriever.py:675` 的 `if doc_tenant and ...` 逻辑在 `doc_tenant==""` 时跳过隔离。

---

## 五、风险点清单

| # | 风险 | 严重度 | 当前是否触发 | 说明 |
|---|---|---|---|---|
| R1 | 向量检索空 tenant 后门 | 高 | **已修复**（见第八节） | 文档漏打 `tenant_id` → 跨租户可见 |
| R2 | Ticket API 硬编码 default | 中 | 是（但无害） | 多租户能力未激活，无真实隔离场景 |
| R3 | WS 匿名共享空租户 | 中 | 是（demo 简化） | 匿名用户间无隔离 |
| R4 | RBAC 无租户维度 | 中 | 否（靠数据层兜底） | 漏传 tenant_id 的 API 会越权 |
| R5 | 无租户管理端点 | 高 | 是 | 「运行化」缺失根因，无法演示真多租户 |

---

## 六、修复建议（若要把多租户真正运行化）

> 优先级按「对作品集说服力」排序。当前阶段（放简历 demo）**不强制全做**，但应在文档里如实声明。

1. **P0 — 堵空 tenant 后门（R1）【已实施 2026-08-07】**：`src/rag/retriever.py` 规则 1 改为：
   ```python
   # 文档未标注 tenant_id 时默认归属 default 租户（既堵住「漏打 tenant 对所有租户可见」的后门，
   # 又保持 default 租户现状不回归）
   doc_tenant = meta.get("tenant_id") or "default"
   if doc_tenant != tenant_id:
       continue
   ```
   实测：default 租户命中正常，evil-corp / 匿名空 tenant 查询均 0 命中（后门已堵）。

2. **P1 — Ticket API 动态取 tenant（R2）**：把 `tickets.py` 里 `tenant_id="default"` 替换为 `_get_tenant_id(current_user)`（仿 `knowledge.py` 写法），让工单层也按 JWT 租户隔离。

3. **P1 — 加租户管理端点（R5）**：`src/api/admin.py` 增加 `POST /admin/tenants`、`GET /admin/tenants`，并让注册/登录支持「归属指定租户」，这样才能在 demo 里真实演示两个租户互不可见。

4. **P2 — RBAC 加租户维度（R4）**：`require_permissions` 增加「租户归属校验」——确认 `current_user.tenant_id` 与目标资源 `tenant_id` 一致，作为纵深防御。

5. **P2 — WS 匿名语义明确化（R3）**：要么强制坐席场景登录、要么把匿名 tenant 标记为独立 `anonymous` 租户而非空串，避免与其他租户混淆。

---

## 七、给简历/作品集的诚实表述

> ✅ **已实现**：多租户数据模型（全表 `tenant_id` + 索引）、SQL 级租户过滤、知识库的前端管理 UI、RBAC 4 级角色与 17 个权限点的依赖注入校验、JWT 鉴权。
> ⚠️ **运行态现状**：当前以单租户 `default` 运行（无独立租户管理端点），多租户隔离在「架构与 SQL 层」已就绪，已通过代码走查验证；生产级多租户运行化（租户创建/切换/跨租户越权端到端测试）为后续迭代项。

---

*附：本次核查最初为静态走查 + 运行时观察；经用户确认后已实施 P0 修复（改动 `src/rag/retriever.py` 与 `src/graph/nodes.py`）。所有引用行号基于 2026-08-07 代码状态。*

---

## 八、实施记录（2026-08-07）

用户确认后实施 P0 修复，过程中暴露并修复了一个回归：

1. **P0 本体 — `src/rag/retriever.py:674`（规则 1 租户隔离）**
   空 tenant 文档默认归属 `default`，堵住「漏打 `tenant_id` 的文档对所有租户可见」后门。
   直测验证：`default` 命中 1 条，`evil-corp` / 匿名空 tenant 查询均 0 命中（后门已堵）。

2. **连带修复 — WS 匿名聊天气泡回归（R3 相关）**
   P0 上线后，WS 端到端实测 `citations` 从 1 掉到 0。根因：WS 匿名连接的 `tenant_id` 一路是空串
   （连接时 `tenant_id=""`，`state.get("tenant_id", "")` 对空值不兜底），被新隔离逻辑挡掉，
   导致 `default` 知识库对匿名聊天不可见、引用气泡消失。
   修复：`src/graph/nodes.py` 两处 `state.get("tenant_id", "")` 改为 `state.get("tenant_id") or "default"`
   （空串 falsy → default，真租户 `evil-corp` 原样保留，多租户隔离不受影响）。
   重测：`citations` 恢复 1 条，引用气泡正常显形。

> 隔离语义澄清：该兜底**不影响**多租户隔离——`evil-corp` 这类非空 `tenant_id` 仍严格隔离；
> 仅把「未携带租户」的匿名/单租户 demo 场景映射到 `default`，符合「单租户 demo 看公共知识库」的预期。
