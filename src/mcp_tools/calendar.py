"""Calendar MCP 工具 — 日程管理

支持 iCal 订阅读取，以及创建/更新/删除日程事件（基于内存存储 + iCal 导出）。
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.tools import PermissionChecker
from src.config import settings
from src.mcp_tools.common import TenantIsolatedStore, current_utc_time, format_result, generate_id

logger = logging.getLogger(__name__)


class CalendarEvent(BaseModel):
    """日历事件"""
    id: str
    tenant_id: str
    title: str
    description: str = ""
    location: str = ""
    start_time: str
    end_time: str
    all_day: bool = False
    attendees: List[str] = []
    status: str = "confirmed"  # confirmed/tentative/cancelled
    created_at: str
    updated_at: str


_event_store = TenantIsolatedStore(max_items_per_tenant=1000, name="calendar_events")


def _parse_datetime(dt_str: str) -> Optional[datetime]:
    """解析日期时间字符串"""
    for fmt in [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


def create_calendar_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建日历管理工具集"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    if not settings.mcp_calendar_enabled:
        @tool
        def calendar_list_events(start_date: str = "", end_date: str = "") -> str:
            """日历工具（未启用）。"""
            return format_result("未启用", "Calendar MCP 服务未启用，请在配置中开启 mcp_calendar_enabled")

        return [calendar_list_events]

    @tool
    def calendar_create_event(
        title: str,
        start_time: str,
        end_time: str,
        description: str = "",
        location: str = "",
        all_day: bool = False,
        attendees: str = "",
    ) -> str:
        """创建日历事件。

        何时使用：需要安排会议、预约、提醒等日程时。

        Args:
            title: 事件标题
            start_time: 开始时间，格式 YYYY-MM-DD HH:MM:SS
            end_time: 结束时间，格式 YYYY-MM-DD HH:MM:SS
            description: 事件描述
            location: 地点
            all_day: 是否全天事件，默认 false
            attendees: 参与人邮箱，逗号分隔
        """
        if not checker.check("calendar_create_event"):
            return format_result("权限不足", "您没有权限创建日程")

        if not title:
            return format_result("参数错误", "标题不能为空")

        start = _parse_datetime(start_time)
        end = _parse_datetime(end_time)
        if start is None or end is None:
            return format_result("参数错误", "时间格式错误，请使用 YYYY-MM-DD HH:MM:SS")
        if end <= start:
            return format_result("参数错误", "结束时间必须晚于开始时间")

        attendee_list = [a.strip() for a in attendees.split(",") if a.strip()] if attendees else []

        now = current_utc_time().isoformat()
        event = CalendarEvent(
            id=generate_id("EVT"),
            tenant_id=tenant_id,
            title=title,
            description=description,
            location=location,
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            all_day=all_day,
            attendees=attendee_list,
            status="confirmed",
            created_at=now,
            updated_at=now,
        )
        _event_store.save(tenant_id, event.id, event)

        logger.info("Calendar event created: id=%s title=%s", event.id, title)
        return format_result("创建成功", "", {
            "event_id": event.id,
            "title": title,
            "start": start_time,
            "end": end_time,
            "attendees": len(attendee_list),
        })

    @tool
    def calendar_list_events(
        start_date: str = "",
        end_date: str = "",
        limit: int = 50,
    ) -> str:
        """列出指定时间范围内的日历事件。

        何时使用：需要查看某天/某周/某月的日程安排时。

        Args:
            start_date: 开始日期，格式 YYYY-MM-DD（留空为今天起）
            end_date: 结束日期，格式 YYYY-MM-DD（留空为 7 天后）
            limit: 最大返回数量，默认 50
        """
        if not checker.check("calendar_list_events"):
            return format_result("权限不足", "您没有权限查看日程")

        now = datetime.now()
        start = _parse_datetime(start_date) if start_date else now
        end = _parse_datetime(end_date) if end_date else now + timedelta(days=7)

        if start is None or end is None:
            return format_result("参数错误", "日期格式错误，请使用 YYYY-MM-DD")

        all_events = _event_store.list(tenant_id, limit=1000)
        filtered = []
        for evt in all_events:
            evt_start = _parse_datetime(evt.start_time)
            evt_end = _parse_datetime(evt.end_time)
            if evt_start and evt_end:
                if evt_end >= start and evt_start <= end:
                    filtered.append(evt)

        filtered.sort(key=lambda e: e.start_time)
        filtered = filtered[:limit]

        lines = [f"[日程列表] {start.date()} ~ {end.date()}，共 {len(filtered)} 个事件:"]
        for evt in filtered:
            all_day_tag = " [全天]" if evt.all_day else ""
            lines.append(
                f"  • [{evt.id}] {evt.title[:50]}{all_day_tag}\n"
                f"    时间: {evt.start_time} ~ {evt.end_time}\n"
                f"    地点: {evt.location or '未设置'} | 参与人: {len(evt.attendees)}人"
            )
        return "\n".join(lines)

    @tool
    def calendar_get_event(event_id: str) -> str:
        """获取日历事件详情。

        何时使用：需要查看某个事件的完整信息时。

        Args:
            event_id: 事件 ID
        """
        if not checker.check("calendar_get_event"):
            return format_result("权限不足", "您没有权限查看日程")

        evt = _event_store.get(tenant_id, event_id)
        if evt is None:
            return format_result("未找到", f"事件 {event_id} 不存在")

        return format_result("事件详情", "", {
            "id": evt.id,
            "title": evt.title,
            "description": evt.description,
            "location": evt.location,
            "start_time": evt.start_time,
            "end_time": evt.end_time,
            "all_day": evt.all_day,
            "attendees": ", ".join(evt.attendees),
            "status": evt.status,
            "created_at": evt.created_at,
        })

    @tool
    def calendar_update_event(
        event_id: str,
        title: str = "",
        start_time: str = "",
        end_time: str = "",
        description: str = "",
        location: str = "",
        status: str = "",
    ) -> str:
        """更新日历事件。

        何时使用：需要修改已有的日程安排时。

        Args:
            event_id: 事件 ID
            title: 新标题（留空不修改）
            start_time: 新开始时间（留空不修改）
            end_time: 新结束时间（留空不修改）
            description: 新描述（留空不修改）
            location: 新地点（留空不修改）
            status: 新状态 confirmed/tentative/cancelled（留空不修改）
        """
        if not checker.check("calendar_update_event"):
            return format_result("权限不足", "您没有权限修改日程")

        evt = _event_store.get(tenant_id, event_id)
        if evt is None:
            return format_result("未找到", f"事件 {event_id} 不存在")

        if title:
            evt.title = title
        if description:
            evt.description = description
        if location:
            evt.location = location
        if status:
            if status not in ("confirmed", "tentative", "cancelled"):
                return format_result("参数错误", "状态只能是 confirmed/tentative/cancelled")
            evt.status = status

        if start_time:
            st = _parse_datetime(start_time)
            if st is None:
                return format_result("参数错误", "开始时间格式错误")
            evt.start_time = st.isoformat()

        if end_time:
            et = _parse_datetime(end_time)
            if et is None:
                return format_result("参数错误", "结束时间格式错误")
            evt.end_time = et.isoformat()

        evt.updated_at = current_utc_time().isoformat()
        _event_store.save(tenant_id, event_id, evt)

        return format_result("更新成功", "", {
            "event_id": event_id,
            "title": evt.title,
            "status": evt.status,
        })

    @tool
    def calendar_delete_event(event_id: str) -> str:
        """删除日历事件。

        何时使用：需要取消某个日程时。

        Args:
            event_id: 事件 ID
        """
        if not checker.check("calendar_delete_event"):
            return format_result("权限不足", "您没有权限删除日程")

        success = _event_store.delete(tenant_id, event_id)
        if success:
            return format_result("删除成功", f"事件 {event_id} 已删除")
        return format_result("未找到", f"事件 {event_id} 不存在")

    @tool
    def calendar_export_ical(start_date: str = "", end_date: str = "") -> str:
        """导出 iCal 格式日历数据。

        何时使用：需要将日程导出到其他日历应用（Google/Outlook/Apple）时。

        Args:
            start_date: 开始日期，格式 YYYY-MM-DD
            end_date: 结束日期，格式 YYYY-MM-DD
        """
        if not checker.check("calendar_export_ical"):
            return format_result("权限不足", "您没有权限导出日历")

        now = datetime.now()
        start = _parse_datetime(start_date) if start_date else now
        end = _parse_datetime(end_date) if end_date else now + timedelta(days=30)

        all_events = _event_store.list(tenant_id, limit=1000)
        filtered = []
        for evt in all_events:
            evt_start = _parse_datetime(evt.start_time)
            evt_end = _parse_datetime(evt.end_time)
            if evt_start and evt_end:
                if evt_end >= start and evt_start <= end:
                    filtered.append(evt)

        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//enterprise-agent//CN"]
        for evt in filtered:
            lines.append("BEGIN:VEVENT")
            lines.append(f"UID:{evt.id}@enterprise-agent")
            lines.append(f"SUMMARY:{evt.title}")
            lines.append(f"DTSTART:{evt.start_time.replace('-', '').replace(':', '').replace(' ', 'T')}")
            lines.append(f"DTEND:{evt.end_time.replace('-', '').replace(':', '').replace(' ', 'T')}")
            if evt.description:
                lines.append(f"DESCRIPTION:{evt.description}")
            if evt.location:
                lines.append(f"LOCATION:{evt.location}")
            lines.append(f"STATUS:{evt.status.upper()}")
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")

        ical_content = "\r\n".join(lines)
        return format_result("导出成功", f"共 {len(filtered)} 个事件", {
            "format": "iCal 2.0",
            "events": len(filtered),
            "content": ical_content,
        })

    return [
        calendar_create_event,
        calendar_list_events,
        calendar_get_event,
        calendar_update_event,
        calendar_delete_event,
        calendar_export_ical,
    ]
