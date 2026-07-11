"""底层系统适配器"""
from src.adapters.base import (
    OrderAdapter,
    CrmAdapter,
    TicketAdapter,
    LogisticsAdapter,
    MockOrderAdapter,
    MockCrmAdapter,
    MockTicketAdapter,
    MockLogisticsAdapter,
    AdapterFactory,
)

__all__ = [
    "OrderAdapter", "CrmAdapter", "TicketAdapter", "LogisticsAdapter",
    "MockOrderAdapter", "MockCrmAdapter", "MockTicketAdapter", "MockLogisticsAdapter",
    "AdapterFactory",
]
