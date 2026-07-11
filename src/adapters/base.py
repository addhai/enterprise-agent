"""底层系统适配器 — 对接外部业务系统

职责：
    将 Agent 的工具调用转换为对底层系统的实际 API 调用。
    提供统一的接口抽象，便于替换真实系统或保持模拟模式。

支持的系统：
    - 订单系统：查订单、催发货、改地址、申请售后
    - CRM 系统：客户画像、历史订单、订阅计划
    - 工单系统：创建工单、查询工单状态、升级工单
    - 物流系统：查物流轨迹、预估到达时间

适配策略：
    - 默认使用模拟模式（MockAdapter），方便开发和测试
    - 生产环境替换为真实 API 适配器（RealAdapter）
    - 所有适配器实现相同的接口，可热切换
"""
from __future__ import annotations

import abc
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ====================================================================
# 抽象基类
# ====================================================================

class OrderAdapter(abc.ABC):
    """订单系统适配器接口"""

    @abc.abstractmethod
    def query_order(self, order_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """查询订单详情"""
        ...

    @abc.abstractmethod
    def cancel_order(self, order_id: str, user_id: str) -> Dict[str, Any]:
        """取消订单"""
        ...

    @abc.abstractmethod
    def apply_refund(self, order_id: str, user_id: str, reason: str) -> Dict[str, Any]:
        """申请退款"""
        ...

    @abc.abstractmethod
    def urge_shipment(self, order_id: str, user_id: str) -> Dict[str, Any]:
        """催发货"""
        ...

    @abc.abstractmethod
    def change_address(self, order_id: str, user_id: str, new_address: str) -> Dict[str, Any]:
        """修改收货地址"""
        ...


class CrmAdapter(abc.ABC):
    """CRM 系统适配器接口"""

    @abc.abstractmethod
    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """获取用户画像"""
        ...

    @abc.abstractmethod
    def get_order_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取历史订单"""
        ...

    @abc.abstractmethod
    def get_subscription(self, user_id: str) -> Dict[str, Any]:
        """获取订阅信息"""
        ...


class TicketAdapter(abc.ABC):
    """工单系统适配器接口"""

    @abc.abstractmethod
    def create_ticket(self, user_id: str, subject: str, description: str,
                      priority: str = "normal") -> Dict[str, Any]:
        """创建工单"""
        ...

    @abc.abstractmethod
    def get_ticket_status(self, ticket_id: str) -> Dict[str, Any]:
        """查询工单状态"""
        ...

    @abc.abstractmethod
    def escalate_ticket(self, ticket_id: str, reason: str) -> Dict[str, Any]:
        """升级工单"""
        ...


class LogisticsAdapter(abc.ABC):
    """物流系统适配器接口"""

    @abc.abstractmethod
    def query_tracking(self, tracking_number: str) -> Dict[str, Any]:
        """查询物流轨迹"""
        ...

    @abc.abstractmethod
    def estimate_delivery(self, order_id: str) -> Dict[str, Any]:
        """预估送达时间"""
        ...


# ====================================================================
# 模拟适配器（开发/测试用）
# ====================================================================

class MockOrderAdapter(OrderAdapter):
    """订单系统模拟适配器"""

    _ORDERS = {
        "ORD-123456": {
            "order_id": "ORD-123456",
            "status": "shipped",
            "tracking_number": "SF1234567890",
            "carrier": "顺丰快递",
            "estimated_delivery": "2026-07-10",
            "items": [{"name": "CloudSync Pro 年费", "price": 180}],
            "total": 180.0,
            "created_at": "2026-07-01",
            "shipping_address": "北京市朝阳区xxx路123号",
        },
        "ORD-789012": {
            "order_id": "ORD-789012",
            "status": "processing",
            "tracking_number": None,
            "carrier": None,
            "estimated_delivery": "2026-07-08",
            "items": [{"name": "CloudSync Pro 月费", "price": 15}],
            "total": 15.0,
            "created_at": "2026-07-05",
            "shipping_address": "上海市浦东新区xxx路456号",
        },
    }

    def query_order(self, order_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        order = self._ORDERS.get(order_id)
        if order:
            return dict(order)
        return {"error": f"未找到订单 {order_id}"}

    def cancel_order(self, order_id: str, user_id: str) -> Dict[str, Any]:
        if order_id in self._ORDERS:
            self._ORDERS[order_id]["status"] = "cancelled"
            return {"success": True, "message": f"订单 {order_id} 已取消"}
        return {"success": False, "error": "订单不存在"}

    def apply_refund(self, order_id: str, user_id: str, reason: str) -> Dict[str, Any]:
        return {
            "success": True,
            "ticket_id": f"REF-{int(time.time())}",
            "message": f"退款申请已提交，工单号：REF-{int(time.time())}",
            "estimated_processing_days": 3,
        }

    def urge_shipment(self, order_id: str, user_id: str) -> Dict[str, Any]:
        return {
            "success": True,
            "message": f"已向仓库发送催发货请求，订单 {order_id}",
            "expected_action": "仓库将在 24 小时内处理",
        }

    def change_address(self, order_id: str, user_id: str, new_address: str) -> Dict[str, Any]:
        if order_id in self._ORDERS:
            self._ORDERS[order_id]["shipping_address"] = new_address
            return {"success": True, "message": "地址已更新"}
        return {"success": False, "error": "订单不存在"}


class MockCrmAdapter(CrmAdapter):
    """CRM 系统模拟适配器"""

    _PROFILES = {
        "test-user": {
            "user_id": "test-user",
            "name": "张三",
            "plan": "enterprise",
            "created_at": "2025-01-15",
            "total_orders": 5,
            "total_spent": 900.0,
            "last_login": "2026-07-06",
            "preferred_language": "zh-CN",
            "support_level": "priority",  # priority / standard
        },
    }

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        return dict(self._PROFILES.get(user_id, {"user_id": user_id, "plan": "free"}))

    def get_order_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return [
            {"order_id": "ORD-123456", "status": "shipped", "amount": 180.0},
            {"order_id": "ORD-789012", "status": "processing", "amount": 15.0},
        ][:limit]

    def get_subscription(self, user_id: str) -> Dict[str, Any]:
        profile = self.get_user_profile(user_id)
        return {
            "plan": profile.get("plan", "free"),
            "status": "active",
            "next_billing_date": "2026-08-01",
        }


class MockTicketAdapter(TicketAdapter):
    """工单系统模拟适配器"""

    def create_ticket(self, user_id: str, subject: str, description: str,
                      priority: str = "normal") -> Dict[str, Any]:
        ticket_id = f"TKT-{int(time.time())}"
        return {
            "ticket_id": ticket_id,
            "user_id": user_id,
            "subject": subject,
            "description": description,
            "priority": priority,
            "status": "open",
            "created_at": time.time(),
            "assigned_to": None,  # 待分配
        }

    def get_ticket_status(self, ticket_id: str) -> Dict[str, Any]:
        return {
            "ticket_id": ticket_id,
            "status": "open",
            "priority": "normal",
            "updated_at": time.time(),
        }

    def escalate_ticket(self, ticket_id: str, reason: str) -> Dict[str, Any]:
        return {
            "success": True,
            "ticket_id": ticket_id,
            "new_priority": "high",
            "message": f"工单已升级，原因：{reason}",
        }


class MockLogisticsAdapter(LogisticsAdapter):
    """物流系统模拟适配器"""

    _TRACKING = {
        "SF1234567890": {
            "tracking_number": "SF1234567890",
            "carrier": "顺丰快递",
            "status": "in_transit",
            "events": [
                {"time": "2026-07-05 14:00", "location": "北京转运中心", "status": "已发出"},
                {"time": "2026-07-05 08:00", "location": "北京仓库", "status": "已揽收"},
            ],
            "estimated_delivery": "2026-07-07",
        },
    }

    def query_tracking(self, tracking_number: str) -> Dict[str, Any]:
        return self._TRACKING.get(tracking_number, {"error": "未找到物流信息"})

    def estimate_delivery(self, order_id: str) -> Dict[str, Any]:
        return {"estimated_delivery": "2026-07-10", "confidence": 0.85}


# ====================================================================
# 适配器工厂
# ====================================================================

from src.adapters.real import AdapterFactory  # noqa: F401
