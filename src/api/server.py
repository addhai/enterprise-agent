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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import router
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

    @app.on_event("shutdown")
    async def shutdown():
        """应用停止：清理资源"""
        logger.info("App shutting down — cleaning up resources...")
        try:
            from src.api.dependencies import cleanup_resources
            cleanup_resources()
        except Exception as e:
            logger.warning("Cleanup failed: %s", e)

    # 注册路由
    app.include_router(router, prefix="/api/v1")

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
