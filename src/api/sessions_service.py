"""会话 API 共享 service 层。

把 admin.py 与 conversations.py 重复的 list/detail/messages/delete 逻辑集中到这里，
两套路由都调本模块，避免行为分叉。所有函数同步、纯逻辑、不依赖 FastAPI。

设计要点：
    - ORM 标量必须在 ``db_session()`` 作用域内提取，避免 ``DetachedInstanceError``
      （HANDOFF 坑21）。
    - 越权访问通过抛 ``PermissionError`` 上报，由路由层翻译为 HTTP 403；
      ``None`` 统一表示「找不到」→ 路由层翻译为 HTTP 404。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ADMIN_ROLES = ("admin", "super_admin", "agent")


# ---------------------------------------------------------------------------
# 基础 helper（从 admin.py 搬迁，去掉下划线前缀以供跨模块复用）
# ---------------------------------------------------------------------------


def get_last_message_preview(conversation_history: list, max_length: int = 50) -> str:
    """获取最后一条消息的预览"""
    if not conversation_history:
        return ""
    last_msg = conversation_history[-1]
    content = last_msg.get("content", "")
    if len(content) > max_length:
        return content[:max_length] + "..."
    return content


def session_to_dict(session, include_history: bool = False) -> dict[str, Any]:
    """将会话状态转换为可序列化的字典"""
    result = {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "mode": session.mode.value,
        "created_at": session.created_at,
        "last_active": session.last_active,
        "turn_count": session.turn_count,
        "last_message_preview": get_last_message_preview(session.conversation_history),
    }
    if include_history:
        result["conversation_history"] = session.conversation_history
        result["handoff_context"] = session.handoff_context
        result["assigned_agent"] = session.assigned_agent
        result["needs_human"] = session.needs_human
        result["failed_attempts"] = session.failed_attempts
        result["suggest_human"] = session.suggest_human
    return result


def db_sessions_as_dicts(
    user_id_filter: str | None = None, limit: int = 500
) -> list[dict[str, Any]]:
    """从持久化 DB 读取历史会话，返回与 session_to_dict 兼容的 dict 列表。

    把「重启后仍在 DB 里的会话」合并进会话列表（原接口只看内存活跃会话）。
    """
    from src.db.models import Conversation as _Conv
    from src.db.repositories import DEFAULT_TENANT, _dt2f
    from src.db.repositories import conversation_list as _repo_list
    from src.db.session import db_session

    out: list[dict[str, Any]] = []
    try:
        rows = _repo_list(DEFAULT_TENANT, user_id_filter, limit)
    except Exception as e:
        logger.warning("读取持久化会话列表失败（非致命）: %s", e)
        return out
    try:
        with db_session() as s:
            convs = s.query(_Conv).all()
        # 在 session 作用域内提取标量，避免闭包外访问已分离实例
        conv_meta = {}
        for c in convs:
            conv_meta[c.id] = (c.user_id, _dt2f(c.created_at) if c.created_at else 0.0)
    except Exception:
        conv_meta = {}
    for row in rows:
        sid = row.get("session_id") or row.get("id") or ""
        if not sid:
            continue
        meta = conv_meta.get(sid)
        user_id = meta[0] if meta else (row.get("user_id") or "anonymous")
        created_at = meta[1] if meta else row.get("updated_at", 0)
        out.append(
            {
                "session_id": sid,
                "user_id": user_id,
                "mode": "ai_chat",
                "created_at": created_at,
                "last_active": row.get("updated_at", 0),
                "turn_count": row.get("message_count", 0),
                "last_message_preview": (row.get("last_message") or "")[:50],
            }
        )
    return out


def db_session_detail_dict(session_id: str) -> dict[str, Any] | None:
    """从持久化 DB 读取单个会话详情（含消息历史）。

    兼容 session_to_dict(include_history=True) 的结构。
    """
    from src.db.models import Conversation as _Conv
    from src.db.repositories import _dt2f, message_list
    from src.db.session import db_session

    try:
        msgs = message_list(session_id, 500)
    except Exception as e:
        logger.warning("读取持久化会话详情失败（非致命）: %s", e)
        return None
    if not msgs:
        return None
    try:
        with db_session() as s:
            conv = s.query(_Conv).filter(_Conv.id == session_id).first()
            user_id = conv.user_id if conv else "anonymous"
            created_at = (
                _dt2f(conv.created_at)
                if conv and conv.created_at
                else (msgs[0].get("created_at", 0) if msgs else 0)
            )
    except Exception:
        user_id = "anonymous"
        created_at = msgs[0].get("created_at", 0) if msgs else 0
    history = [
        {"role": m["role"], "content": m["content"], "timestamp": m.get("created_at")}
        for m in msgs
    ]
    return {
        "session_id": session_id,
        "user_id": user_id,
        "mode": "ai_chat",
        "created_at": created_at,
        "last_active": msgs[-1].get("created_at", 0),
        "turn_count": len(msgs),
        "last_message_preview": (msgs[-1].get("content", "") or "")[:50],
        "conversation_history": history,
        "handoff_context": None,
        "assigned_agent": None,
        "needs_human": False,
        "failed_attempts": 0,
        "suggest_human": False,
    }


# ---------------------------------------------------------------------------
# 面向路由的高层函数
# ---------------------------------------------------------------------------


def _is_admin(requester: dict | None) -> bool:
    if not requester:
        return False
    return requester.get("role", "viewer") in _ADMIN_ROLES


def list_sessions(
    requester: dict | None,
    user_id_filter: str | None = None,
    limit: int = 50,
    include_live: bool = True,
    all_users: bool = False,
) -> list[dict[str, Any]]:
    """返回 normalized session dict 列表（不含 history）。

    - requester: 当前用户 dict（含 user_id/role）；None 表示未登录
    - user_id_filter: 显式指定查看某用户；仅 admin/agent 越权生效，否则回退到自己
    - include_live: True=内存活跃会话 + DB 历史合并去重（legacy 用）；
      False=仅 DB（conversations 用）
    - all_users: True=查看全部用户（仅 admin/agent 路由调用，target=None + 合并 DB）
    - 按 last_active 倒序
    """
    from src.websocket.session_manager import get_session_manager

    requester_id = requester.get("user_id") if requester else None

    if all_users:
        target: str | None = None
        merge_db = True
    elif user_id_filter and _is_admin(requester):
        target = user_id_filter
        merge_db = True
    elif user_id_filter and not _is_admin(requester):
        # 非管理员试图越权 → 忽略 filter，回退到自己
        target = requester_id
        merge_db = bool(requester_id)
    else:
        target = requester_id
        merge_db = bool(requester_id)

    result: list[dict[str, Any]] = []

    if include_live:
        try:
            session_mgr = get_session_manager()
            live_sessions = list(session_mgr._sessions.values())
        except Exception as e:
            logger.warning("读取内存会话失败（非致命）: %s", e)
            live_sessions = []
        if target:
            live_sessions = [s for s in live_sessions if s.user_id == target]
        result = [session_to_dict(s) for s in live_sessions]

    if merge_db:
        try:
            for d in db_sessions_as_dicts(target, limit):
                if not any(x["session_id"] == d["session_id"] for x in result):
                    result.append(d)
        except Exception as e:
            logger.warning("合并持久化会话失败（非致命）: %s", e)

    result.sort(key=lambda x: x.get("last_active", 0), reverse=True)
    return result


def get_session_detail(session_id: str) -> dict[str, Any] | None:
    """内存优先，DB 回退。返回含 history 的 rich dict；找不到返回 None。"""
    from src.websocket.session_manager import get_session_manager

    try:
        session_mgr = get_session_manager()
        session = session_mgr.get_session(session_id)
    except Exception as e:
        logger.warning("读取内存会话详情失败（非致命）: %s", e)
        session = None
    if session:
        return session_to_dict(session, include_history=True)
    return db_session_detail_dict(session_id)


def get_session_ownership(session_id: str) -> dict[str, Any] | None:
    """返回会话归属 ``{user_id, tenant_id}``（内存优先，DB 回退）；找不到 None。

    P0-3：归属判定同时看 user_id 与 tenant_id 两个维度。
    """
    from src.websocket.session_manager import get_session_manager

    try:
        session_mgr = get_session_manager()
        session = session_mgr.get_session(session_id)
    except Exception:
        session = None
    if session:
        return {
            "user_id": getattr(session, "user_id", "") or "",
            "tenant_id": getattr(session, "tenant_id", "default") or "default",
        }
    # DB 回退
    try:
        from src.db.repositories import conversation_get

        meta = conversation_get(session_id)
        if meta is None:
            return None
        return {
            "user_id": meta.get("user_id", ""),
            "tenant_id": meta.get("tenant_id", "default"),
        }
    except Exception as e:
        logger.warning("查询会话归属失败（非致命）: %s", e)
        return None


def get_session_owner(session_id: str) -> str | None:
    """返回会话归属 user_id（内存优先，DB 回退）；找不到返回 None。"""
    ownership = get_session_ownership(session_id)
    return ownership["user_id"] if ownership else None


def _requester_tenant(requester: dict | None) -> str:
    return (requester or {}).get("tenant_id") or "default"


def _session_access_allowed(
    requester: dict | None,
    ownership: dict[str, Any],
) -> bool:
    """会话访问判定（P0-3）：租户隔离对所有角色生效；用户隔离对非管理角色生效。"""
    if not requester:
        return False
    if ownership.get("tenant_id", "default") != _requester_tenant(requester):
        return False
    if _is_admin(requester):
        return True
    return ownership.get("user_id") == requester.get("user_id")


def _session_owner_allowed(
    requester: dict | None,
    ownership: dict[str, Any],
) -> bool:
    """用户端会话接口的严格本人判定（P0-3 收口）。

    与 ``_session_access_allowed`` 的边界差异：
        - 本判定不看角色，super_admin 也只能访问本人会话；
        - 未登录（None）一律拒绝。
    员工跨用户访问统一走 /admin/sessions 与 /conversations 系列接口，
    用户端 /sessions 严格本人，避免安全批次把 master 原有边界放宽
    （自注册用户默认 role=agent，矩阵判定会让其读到同租户所有人会话）。
    """
    if not requester:
        return False
    if ownership.get("tenant_id", "default") != _requester_tenant(requester):
        return False
    return ownership.get("user_id") == requester.get("user_id")


def get_session_messages(
    session_id: str,
    requester: dict | None,
    limit: int = 200,
) -> dict[str, Any] | None:
    """返回 ``{session_id, count, messages}``。

    - 内存会话优先，否则回退 DB message_list
    - 归属校验：非 admin/agent 只能读 requester.user_id 自己的会话；
      越权抛 ``PermissionError``
    - 找不到返回 None
    """
    from src.websocket.session_manager import get_session_manager

    # 内存会话
    try:
        session_mgr = get_session_manager()
        session = session_mgr.get_session(session_id)
    except Exception:
        session = None
    if session:
        ownership = {
            "user_id": getattr(session, "user_id", "") or "",
            "tenant_id": getattr(session, "tenant_id", "default") or "default",
        }
        if not _session_access_allowed(requester, ownership):
            raise PermissionError("无权访问此会话")
        history = list(session.conversation_history)
        if limit:
            history = history[-limit:]
        messages = [
            {
                "role": m.get("role", "user"),
                "content": m.get("content", ""),
                "timestamp": m.get("timestamp"),
            }
            for m in history
        ]
        return {"session_id": session_id, "count": len(messages), "messages": messages}

    # DB 回退：一次查询拿归属，租户过滤下推到 SQL
    try:
        from src.db.repositories import conversation_get, message_list

        ownership_meta = conversation_get(session_id)
        msgs = message_list(session_id, limit, tenant_id=_requester_tenant(requester))
    except Exception as e:
        logger.warning("读取会话消息失败（非致命）: %s", e)
        return None
    if not msgs and not ownership_meta:
        return None
    # 归属校验（用户 + 租户双维度）
    if not ownership_meta or not _session_access_allowed(requester, ownership_meta):
        raise PermissionError("无权访问此会话")
    return {"session_id": session_id, "count": len(msgs), "messages": msgs}


def delete_session(session_id: str) -> bool:
    """同时从内存 session_mgr 与 DB 删除。

    返回是否曾存在并删除（内存或 DB 任一存在即 True；全不存在 False）。
    """
    from src.websocket.session_manager import get_session_manager

    live_existed = False
    try:
        session_mgr = get_session_manager()
        if session_mgr.get_session(session_id):
            session_mgr.remove_session(session_id)
            live_existed = True
    except Exception as e:
        logger.warning("删除内存会话失败（非致命）: %s", e)

    db_existed = False
    try:
        from src.db.repositories import conversation_delete

        db_existed = conversation_delete(session_id)
    except Exception as e:
        logger.warning("删除持久化会话失败（非致命）: %s", e)

    return live_existed or db_existed


def delete_session_checked(
    session_id: str,
    requester: dict | None,
    owner_only: bool = False,
) -> bool | None:
    """带归属/租户校验的删除（P0-3）。

    返回：
        True  = 校验通过且已删除；
        None  = 会话不存在（路由层翻译为 404，不泄露存在性）；
    校验失败抛 PermissionError（路由层翻译为 403）。

    规则：
        - owner_only=False（员工端 /admin、/conversations）：租户隔离对所有
          角色生效；同租户下 admin/agent 可删任意会话；
        - owner_only=True（用户端 /sessions）：严格本人 + 同租户，角色不豁免；
        - 未登录一律拒绝。
    """
    ownership = get_session_ownership(session_id)
    if ownership is None:
        return None
    allowed = (
        _session_owner_allowed(requester, ownership)
        if owner_only
        else _session_access_allowed(requester, ownership)
    )
    if not allowed:
        raise PermissionError("无权删除此会话")
    return delete_session(session_id)
