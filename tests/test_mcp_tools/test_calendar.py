"""Calendar MCP 工具测试"""
import pytest
from unittest.mock import patch
from src.mcp_tools.calendar import create_calendar_tools, CalendarEvent, _event_store
from src.mcp_tools.common import generate_id


def _find(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise ValueError(f"Tool {name} not found")


@pytest.fixture(autouse=True)
def clear_store():
    _event_store._store.clear()
    _event_store._timestamps.clear()
    yield


@pytest.fixture()
def admin_tools():
    with patch("src.mcp_tools.calendar.settings") as mock_settings:
        mock_settings.mcp_calendar_enabled = True
        tools = create_calendar_tools(
            user_id="admin_001", tenant_id="tenant_A", roles=["admin"], plan="enterprise"
        )
        yield tools


@pytest.fixture()
def user_tools():
    with patch("src.mcp_tools.calendar.settings") as mock_settings:
        mock_settings.mcp_calendar_enabled = True
        tools = create_calendar_tools(
            user_id="user_001", tenant_id="tenant_A", roles=["user"], plan="enterprise"
        )
        yield tools


@pytest.fixture()
def other_tenant_tools():
    with patch("src.mcp_tools.calendar.settings") as mock_settings:
        mock_settings.mcp_calendar_enabled = True
        tools = create_calendar_tools(
            user_id="admin_002", tenant_id="tenant_B", roles=["admin"], plan="enterprise"
        )
        yield tools


class TestCalendarDisabled:
    def test_disabled_returns_unenabled(self):
        from unittest.mock import patch

        with patch("src.mcp_tools.calendar.settings") as mock_settings:
            mock_settings.mcp_calendar_enabled = False
            tools = create_calendar_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            assert len(tools) == 1
            result = tools[0].invoke({"start_date": "", "end_date": ""})
            assert "[未启用]" in result


class TestCalendarCreate:
    def test_create_event_success(self, admin_tools):
        result = _find(admin_tools, "calendar_create_event").invoke({
            "title": "团队周会",
            "start_time": "2026-07-20 10:00:00",
            "end_time": "2026-07-20 11:00:00",
            "description": "每周例会",
            "location": "会议室A",
            "attendees": "a@test.com,b@test.com",
        })
        assert "[创建成功]" in result
        assert "团队周会" in result
        assert "event_id" in result

    def test_create_event_empty_title(self, admin_tools):
        result = _find(admin_tools, "calendar_create_event").invoke({
            "title": "",
            "start_time": "2026-07-20 10:00:00",
            "end_time": "2026-07-20 11:00:00",
        })
        assert "[参数错误]" in result
        assert "标题不能为空" in result

    def test_create_event_end_before_start(self, admin_tools):
        result = _find(admin_tools, "calendar_create_event").invoke({
            "title": "测试",
            "start_time": "2026-07-20 11:00:00",
            "end_time": "2026-07-20 10:00:00",
        })
        assert "[参数错误]" in result
        assert "结束时间必须晚于开始时间" in result

    def test_create_event_invalid_time(self, admin_tools):
        result = _find(admin_tools, "calendar_create_event").invoke({
            "title": "测试",
            "start_time": "not-a-date",
            "end_time": "2026-07-20 10:00:00",
        })
        assert "[参数错误]" in result


class TestCalendarList:
    def test_list_events_empty(self, admin_tools):
        result = _find(admin_tools, "calendar_list_events").invoke({
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        })
        assert "[日程列表]" in result
        assert "0 个事件" in result

    def test_list_events_after_create(self, admin_tools):
        _find(admin_tools, "calendar_create_event").invoke({
            "title": "测试会议",
            "start_time": "2026-07-20 10:00:00",
            "end_time": "2026-07-20 11:00:00",
        })
        result = _find(admin_tools, "calendar_list_events").invoke({
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        })
        assert "[日程列表]" in result
        assert "1 个事件" in result
        assert "测试会议" in result


class TestCalendarGet:
    def test_get_event_success(self, admin_tools):
        create_result = _find(admin_tools, "calendar_create_event").invoke({
            "title": "详情测试",
            "start_time": "2026-07-20 10:00:00",
            "end_time": "2026-07-20 11:00:00",
            "description": "详情描述",
        })
        # 从结果中提取 event_id
        import re
        m = re.search(r"event_id:\s*(\S+)", create_result)
        assert m is not None
        event_id = m.group(1)

        result = _find(admin_tools, "calendar_get_event").invoke({"event_id": event_id})
        assert "[事件详情]" in result
        assert "详情测试" in result
        assert "详情描述" in result

    def test_get_event_not_found(self, admin_tools):
        result = _find(admin_tools, "calendar_get_event").invoke({"event_id": "EVT-NOTEXIST"})
        assert "[未找到]" in result


class TestCalendarUpdate:
    def test_update_event_title(self, admin_tools):
        create_result = _find(admin_tools, "calendar_create_event").invoke({
            "title": "原标题",
            "start_time": "2026-07-20 10:00:00",
            "end_time": "2026-07-20 11:00:00",
        })
        import re
        m = re.search(r"event_id:\s*(\S+)", create_result)
        event_id = m.group(1)

        result = _find(admin_tools, "calendar_update_event").invoke({
            "event_id": event_id,
            "title": "新标题",
        })
        assert "[更新成功]" in result
        assert "新标题" in result

    def test_update_event_not_found(self, admin_tools):
        result = _find(admin_tools, "calendar_update_event").invoke({
            "event_id": "EVT-NOPE",
            "title": "随便改",
        })
        assert "[未找到]" in result


class TestCalendarDelete:
    def test_delete_event_success(self, admin_tools):
        create_result = _find(admin_tools, "calendar_create_event").invoke({
            "title": "待删除",
            "start_time": "2026-07-20 10:00:00",
            "end_time": "2026-07-20 11:00:00",
        })
        import re
        m = re.search(r"event_id:\s*(\S+)", create_result)
        event_id = m.group(1)

        result = _find(admin_tools, "calendar_delete_event").invoke({"event_id": event_id})
        assert "[删除成功]" in result

    def test_delete_event_not_found(self, admin_tools):
        result = _find(admin_tools, "calendar_delete_event").invoke({"event_id": "EVT-NOPE"})
        assert "[未找到]" in result


class TestCalendarExport:
    def test_export_ical(self, admin_tools):
        _find(admin_tools, "calendar_create_event").invoke({
            "title": "导出测试",
            "start_time": "2026-07-20 10:00:00",
            "end_time": "2026-07-20 11:00:00",
        })
        result = _find(admin_tools, "calendar_export_ical").invoke({
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        })
        assert "[导出成功]" in result
        assert "iCal" in result
        assert "BEGIN:VCALENDAR" in result
        assert "BEGIN:VEVENT" in result
        assert "导出测试" in result


class TestTenantIsolation:
    def test_tenant_isolation(self, admin_tools, other_tenant_tools):
        # tenant_A 创建事件
        _find(admin_tools, "calendar_create_event").invoke({
            "title": "租户A的会议",
            "start_time": "2026-07-20 10:00:00",
            "end_time": "2026-07-20 11:00:00",
        })

        # tenant_B 看不到
        result = _find(other_tenant_tools, "calendar_list_events").invoke({
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        })
        assert "0 个事件" in result
