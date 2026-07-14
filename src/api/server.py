"""
FastAPI 应用入口
"""
import logging
import os
import sys
from pathlib import Path

# 确保运行时 cwd 是项目根目录（PyCharm 直接运行本文件时 cwd 可能不对）
_project_root = Path(__file__).parent.parent.parent
os.chdir(_project_root)
sys.path.insert(0, str(_project_root))

# 加载 .env 文件（在导入 config 之前）
try:
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env", override=True)
except ImportError:
    pass  # python-dotenv 未安装则跳过

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import router
from src.websocket.routes import router as websocket_router
from src.config import settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="Enterprise Customer Service Agent",
        description="基于 LangGraph + ReAct 的企业级智能客服",
        version="0.2.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 生命周期事件
    @app.on_event("startup")
    async def startup():
        """应用启动：预初始化单例，确保首次请求不阻塞"""
        logger.info("App starting — pre-warming singletons...")
        try:
            from src.api.dependencies import get_workflow
            get_workflow()
            logger.info("Workflow compiled and ready")
        except Exception as e:
            logger.warning("Workflow pre-warm failed (will retry on first request): %s", e)

        # 启动 WebSocket 会话管理器
        try:
            from src.websocket.session_manager import get_session_manager
            mgr = get_session_manager()
            await mgr.start()
            logger.info("WebSocket session manager started")
        except Exception as e:
            logger.warning("WebSocket session manager start failed: %s", e)

    @app.on_event("shutdown")
    async def shutdown():
        """应用停止：清理资源"""
        logger.info("App shutting down — cleaning up resources...")
        try:
            from src.api.dependencies import cleanup_resources
            cleanup_resources()
        except Exception as e:
            logger.warning("Cleanup failed: %s", e)

        # 停止 WebSocket 会话管理器
        try:
            from src.websocket.session_manager import get_session_manager
            mgr = get_session_manager()
            await mgr.stop()
            logger.info("WebSocket session manager stopped")
        except Exception as e:
            logger.warning("WebSocket cleanup failed: %s", e)

    # 注册路由
    try:
        app.include_router(router, prefix="/api/v1")
        logger.info("Registered main API router")
    except Exception as e:
        logger.error("Failed to register main API router: %s", e)

    # 注册 WebSocket 路由（无前缀，直接挂载到根路径）
    try:
        app.include_router(websocket_router)
        logger.info("Registered WebSocket router")
    except Exception as e:
        logger.error("Failed to register WebSocket router: %s", e)

    # 注册监控路由
    try:
        from src.api.monitoring import router as monitoring_router
        for route in monitoring_router.routes:
                app.add_api_route(f"/api/v1{route.path}", route.endpoint, methods=list(route.methods or ["GET"]), tags=route.tags)
        logger.info("Registered monitoring router")
    except Exception as e:
        logger.error("Failed to register monitoring router: %s", e)

    # 注册多渠道接入路由
    try:
        from src.channels.wechat import router as wechat_router
        app.include_router(wechat_router, prefix="/api/v1")
        logger.info("Registered wechat router")
    except Exception as e:
        logger.error("Failed to register wechat router: %s", e)
    try:
        from src.channels.phone import router as phone_router
        app.include_router(phone_router, prefix="/api/v1")
        logger.info("Registered phone router")
    except Exception as e:
        logger.error("Failed to register phone router: %s", e)

    # 注册 Chatwoot webhook 路由
    try:
        from src.api.chatwoot import router as chatwoot_router
        app.include_router(chatwoot_router, prefix="/api/v1")
        logger.info("Registered chatwoot router")
    except Exception as e:
        logger.error("Failed to register chatwoot router: %s", e)

    # 注册静态文件（必须在所有路由之后，否则会拦截 /api 请求）
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.server:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
