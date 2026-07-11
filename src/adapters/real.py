"""真实 API 适配器 — 对接生产环境系统

职责：
    将 Agent 的工具调用转换为对真实外部系统的 API 调用。
    提供配置开关，可在 Mock 模式和真实模式间切换。

支持的系统：
    - 订单系统：REST API（可对接 Shopify/Salesforce/自研）
    - CRM 系统：REST API（可对接 Salesforce HubSpot/自研）
    - 工单系统：REST API（可对接 Zendesk/Jira/自研）
    - 物流系统：REST API（可对接顺丰/圆通/菜鸟）

配置方式：
    config.yaml 中设置 adapters.use_real = true/false
    或通过环境变量 ADAPTERS_USE_REAL=true 覆盖
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from src.adapters.base import (
    OrderAdapter, CrmAdapter, TicketAdapter, LogisticsAdapter,
    MockOrderAdapter, MockCrmAdapter, MockTicketAdapter, MockLogisticsAdapter,
)
from src.config import settings

logger = logging.getLogger(__name__)


# ====================================================================
# 配置：是否使用真实 API
# ====================================================================

def _use_real_adapters() -> bool:
    """检查是否启用真实 API 适配器

    优先级：环境变量 > settings > 默认 False
    """
    import os
    env_val = os.environ.get("ADAPTERS_USE_REAL", "").lower()
    if env_val in ("true", "1", "yes"):
        return True
    if env_val in ("false", "0", "no"):
        return False
    # 从 settings 读取
    try:
        from src.config import settings
        return getattr(settings.server, "use_real_adapters", False)
    except Exception:
        return False


# ====================================================================
# 订单系统真实适配器
# ====================================================================

class RealOrderAdapter(OrderAdapter):
    """订单系统真实 API 适配器

    可对接的系统：
        - Shopify: https://shopify.dev/api/rest
        - Salesforce: https://developer.salesforce.com/docs
        - 自研系统: 自定义 REST API
    """

    def __init__(self, api_base_url: str = "", api_key: str = "", timeout: float = 10.0):
        self.api_base_url = api_base_url or "https://api.your-order-system.com/v1"
        self.api_key = api_key or ""
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> Optional[Dict]:
        """发送 HTTP 请求"""
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        kwargs.setdefault("headers", {})
        kwargs["headers"].update(headers)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error("Order API request failed: %s %s - %s", method, url, e)
            return None

    def query_order(self, order_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        return self._request("GET", f"/orders/{order_id}")

    def cancel_order(self, order_id: str, user_id: str) -> Dict[str, Any]:
        result = self._request("POST", f"/orders/{order_id}/cancel", json={"reason": "customer_request"})
        return {"success": result is not None, "message": "订单已取消" if result else "取消失败"}

    def apply_refund(self, order_id: str, user_id: str, reason: str) -> Dict[str, Any]:
        result = self._request("POST", "/refunds", json={
            "order_id": order_id,
            "reason": reason,
            "user_id": user_id,
        })
        return {"success": result is not None, "ticket_id": result.get("id") if result else ""}

    def urge_shipment(self, order_id: str, user_id: str) -> Dict[str, Any]:
        result = self._request("POST", f"/orders/{order_id}/urge-shipment")
        return {"success": result is not None, "message": "催发货请求已发送"}

    def change_address(self, order_id: str, user_id: str, new_address: str) -> Dict[str, Any]:
        result = self._request("PUT", f"/orders/{order_id}/address", json={"address": new_address})
        return {"success": result is not None}


# ====================================================================
# CRM 系统真实适配器
# ====================================================================

class RealCrmAdapter(CrmAdapter):
    """CRM 系统真实 API 适配器

    可对接的系统：
        - Salesforce: https://www.salesforce.com/products/
        - HubSpot: https://developers.hubspot.com/docs/api
        - 自研系统: 自定义 REST API
    """

    def __init__(self, api_base_url: str = "", api_key: str = "", timeout: float = 10.0):
        self.api_base_url = api_base_url or "https://api.your-crm-system.com/v1"
        self.api_key = api_key or ""
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> Optional[Dict]:
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        kwargs.setdefault("headers", {})
        kwargs["headers"].update(headers)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error("CRM API request failed: %s %s - %s", method, url, e)
            return None

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        result = self._request("GET", f"/contacts/{user_id}")
        return result or {"user_id": user_id, "plan": "free"}

    def get_order_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        result = self._request("GET", f"/contacts/{user_id}/orders", params={"limit": limit})
        return result.get("orders", []) if result else []

    def get_subscription(self, user_id: str) -> Dict[str, Any]:
        result = self._request("GET", f"/contacts/{user_id}/subscription")
        return result or {"plan": "free", "status": "active"}


# ====================================================================
# 工单系统真实适配器
# ====================================================================

class RealTicketAdapter(TicketAdapter):
    """工单系统真实 API 适配器

    可对接的系统：
        - Zendesk: https://developer.zendesk.com/api-reference/
        - Jira Service Desk: https://developer.atlassian.com/cloud/jira/service-desk/
        - 自研系统: 自定义 REST API
    """

    def __init__(self, api_base_url: str = "", api_key: str = "", timeout: float = 10.0):
        self.api_base_url = api_base_url or "https://api.your-ticket-system.com/v1"
        self.api_key = api_key or ""
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> Optional[Dict]:
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        kwargs.setdefault("headers", {})
        kwargs["headers"].update(headers)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error("Ticket API request failed: %s %s - %s", method, url, e)
            return None

    def create_ticket(self, user_id: str, subject: str, description: str,
                      priority: str = "normal") -> Dict[str, Any]:
        result = self._request("POST", "/tickets", json={
            "requester_id": user_id,
            "subject": subject,
            "description": description,
            "priority": priority,
        })
        return result or {}

    def get_ticket_status(self, ticket_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/tickets/{ticket_id}") or {}

    def escalate_ticket(self, ticket_id: str, reason: str) -> Dict[str, Any]:
        result = self._request("PATCH", f"/tickets/{ticket_id}", json={
            "priority": "high",
            "tags": ["escalated", reason],
        })
        return {"success": result is not None}


# ====================================================================
# 物流系统真实适配器
# ====================================================================

class RealLogisticsAdapter(LogisticsAdapter):
    """物流系统真实 API 适配器

    可对接的系统：
        - 顺丰: https://open.sf-express.com/
        - 菜鸟: https://open.cainiao.com/
        - 快递100: https://api.kuaidi100.com/
    """

    def __init__(self, api_base_url: str = "", api_key: str = "", timeout: float = 10.0):
        self.api_base_url = api_base_url or "https://api.your-logistics-system.com/v1"
        self.api_key = api_key or ""
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> Optional[Dict]:
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        kwargs.setdefault("headers", {})
        kwargs["headers"].update(headers)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error("Logistics API request failed: %s %s - %s", method, url, e)
            return None

    def query_tracking(self, tracking_number: str) -> Dict[str, Any]:
        return self._request("GET", f"/track/{tracking_number}") or {}

    def estimate_delivery(self, order_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/orders/{order_id}/estimate-delivery") or {}


# ====================================================================
# 适配器工厂（支持 Mock/Real 切换）
# ====================================================================

class AdapterFactory:
    """适配器工厂 — 根据配置返回真实或模拟适配器"""

    @classmethod
    def get_order_adapter(cls, use_real: Optional[bool] = None) -> OrderAdapter:
        if use_real is None:
            use_real = _use_real_adapters()
        if use_real:
            return RealOrderAdapter()
        return MockOrderAdapter()

    @classmethod
    def get_crm_adapter(cls, use_real: Optional[bool] = None) -> CrmAdapter:
        if use_real is None:
            use_real = _use_real_adapters()
        if use_real:
            return RealCrmAdapter()
        return MockCrmAdapter()

    @classmethod
    def get_ticket_adapter(cls, use_real: Optional[bool] = None) -> TicketAdapter:
        if use_real is None:
            use_real = _use_real_adapters()
        if use_real:
            return RealTicketAdapter()
        return MockTicketAdapter()

    @classmethod
    def get_logistics_adapter(cls, use_real: Optional[bool] = None) -> LogisticsAdapter:
        if use_real is None:
            use_real = _use_real_adapters()
        if use_real:
            return RealLogisticsAdapter()
        return MockLogisticsAdapter()
