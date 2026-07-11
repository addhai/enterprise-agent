"""多渠道接入层"""
from src.channels.wechat import router as wechat_router
from src.channels.phone import router as phone_router

__all__ = ["wechat_router", "phone_router"]
