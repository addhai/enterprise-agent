"""
WebSocket 独立服务入口

启动方式:
  python -m src.websocket.server

或:
  uvicorn src.websocket.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.websocket.routes import router as ws_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Enterprise Agent — WebSocket Service",
    version="0.1.0",
    description="独立 WebSocket 长连接管理微服务",
)


# CORS (WebSocket 需要)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    """启动 WebSocket 会话管理器"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    try:
        from src.websocket.session_manager import get_session_manager
        mgr = get_session_manager()
        await mgr.start()
        logger.info("WebSocket session manager started")
    except Exception as e:
        logger.warning("WebSocket session manager start failed: %s", e)


@app.on_event("shutdown")
async def shutdown():
    """停止会话管理器"""
    try:
        from src.websocket.session_manager import get_session_manager
        mgr = get_session_manager()
        await mgr.stop()
        logger.info("WebSocket session manager stopped")
    except Exception as e:
        logger.warning("WebSocket session manager stop failed: %s", e)


@app.get("/ws/health")
async def health():
    return {"status": "ok", "service": "ws-service"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "ws-service"}


@app.get("/metrics")
async def metrics():
    """Prometheus text format /metrics 端点"""
    from fastapi.responses import PlainTextResponse
    from src.api.metrics import render_metrics, gauge_set
    try:
        from src.websocket.session_manager import get_session_manager
        mgr = get_session_manager()
        # 这里 WS session manager 的活跃连接数需要实际暴露
        # 当前用 session_manager 内部的统计
    except ImportError:
        pass
    return PlainTextResponse(render_metrics(), media_type="text/plain; charset=utf-8")


# 注册 WebSocket 路由
app.include_router(ws_router)


if __name__ == "__main__":
    import uvicorn
    from src.config import settings

    uvicorn.run(
        "src.websocket.server:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
