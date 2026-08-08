"""
FastAPI 应用入口
"""
import logging
import os
import sys
from pathlib import Path

# 强制 libpq/psycopg2 使用 UTF-8 客户端编码 + 英文 locale。必须在导入任何
# 可能触发 psycopg2 加载的模块之前设置，否则 Windows 中文系统会默认使用
# GBK 代码页，导致中文错误信息/数据在 UTF-8 解码时崩溃（UnicodeDecodeError:
# 'utf-8' codec can't decode byte 0xd6 ...）。
os.environ["PGCLIENTENCODING"] = "UTF8"
os.environ["PYTHONUTF8"] = "1"
# LC_ALL/LC_MESSAGES 控制 libpq 客户端自身返回的错误信息语言；设为 C 可
# 让 Windows 中文系统下的 libpq 也用全 ASCII 英文报错，避免 GBK 解码失败。
os.environ["LC_ALL"] = "C"
os.environ["LC_MESSAGES"] = "C"

# 限制 OpenBLAS 线程数，避免内存分配失败
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

# 确保运行时 cwd 是项目根目录（PyCharm 直接运行本文件时 cwd 可能不对）
_project_root = Path(__file__).parent.parent.parent
os.chdir(_project_root)
sys.path.insert(0, str(_project_root))

# 加载 .env 文件（在导入 config 之前）
# 必须显式指定 encoding="utf-8"，否则 Windows 中文系统会用 GBK 读取，
# 行内中文注释可能被污染到环境变量值里。
try:
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env", override=True, encoding="utf-8")
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


OPENAPI_TAGS = [
    {"name": "对话与系统", "description": "健康检查 `/health` 与 REST 兜底对话 `/chat`。"},
    {"name": "认证 Auth", "description": "用户注册、登录、当前用户信息（Bearer Token）。"},
    {"name": "管理后台 Admin", "description": "会话、接入渠道、转人工队列、HITL 审批等管理操作（需 admin 角色）。"},
    {"name": "权限 RBAC", "description": "角色、权限点、用户角色分配。"},
    {"name": "客户 Customers", "description": "客户档案、标签、时间线。"},
    {"name": "工单 Tickets", "description": "工单 CRUD、分配、备注、关闭。"},
    {"name": "满意度 Satisfaction", "description": "满意度评价提交与统计。"},
    {"name": "通知 Notifications", "description": "站内通知列表、未读数、标记已读。"},
    {"name": "仪表盘 Dashboard", "description": "核心指标、实时概览、坐席绩效、意图分布。"},
    {"name": "人工介入 HITL", "description": "人工介入待办、分配、恢复工作流。"},
    {"name": "智能体健康 Health", "description": "智能体注册、心跳、健康状态、统计。"},
    {"name": "知识库 Knowledge", "description": "知识库与文档管理、向量索引、检索命中测试。"},
    {"name": "工作流 Workflow", "description": "LangGraph 工作流定义与管理。"},
    {"name": "质量评估 Evaluation", "description": "评测数据集与评测运行。"},
    {"name": "配置中心 Config", "description": "运行时特性开关与分类配置。"},
    {"name": "Chatwoot 集成", "description": "第三方 Chatwoot webhook 与事件流。"},
]


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="Enterprise Customer Service Agent",
        description=(
            "# 企业级智能客服 Agent API\n\n"
            "基于 **LangGraph + ReAct** 的多智能体企业级智能客服系统。\n\n"
            "## 双通道\n"
            "- **REST**（`/api/v1/*`）：鉴权、管理后台、知识库、RBAC、评价、监控等 CRUD/查询。\n"
            "- **WebSocket**（`/ws/chat`）：实时 AI 对话主链路；`/ws/agent/{agent_id}`：人工坐席工作台。\n\n"
            "## 快速开始\n"
            "1. `cp .env.example .env` 并填入 API Key\n"
            "2. `cd frontend && npm run build`（产出到 `static/`）\n"
            "3. `uvicorn src.api.server:app --host 0.0.0.0 --port 8000`\n\n"
            "详见仓库 `README.md` 与 `docs/api.md`。\n\n"
            "> 管理类端点需要 `admin` 角色，由 RBAC 中间件校验；认证使用 `Authorization: Bearer <token>`。"
        ),
        version="0.2.0",
        openapi_tags=OPENAPI_TAGS,
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
        # 初始化数据库（建表 + seed 默认账号）放在最前，保证后续 store 可用
        try:
            from src.db.init import init_db

            init_db()
            logger.info("Database initialized (tables + seed)")
        except Exception as e:
            logger.warning("Database init failed (non-fatal): %s", e)

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

        # 注册默认 Agent 到注册中心（供健康检查 / Orchestrator 路由使用）
        try:
            from src.protocols.agent_registry import register_default_agents
            register_default_agents()
            logger.info("Default agents registered to registry")
        except Exception as e:
            logger.warning("Register default agents failed: %s", e)

        # 启动 Agent 健康检查器
        try:
            from src.protocols.health_checker import get_health_checker
            checker = get_health_checker()
            await checker.start()
            logger.info("Agent health checker started")
        except Exception as e:
            logger.warning("Health checker start failed: %s", e)

        # 注入演示数据
        try:
            from src.seed import seed_demo_data
            seed_demo_data()
        except Exception as e:
            logger.warning("Demo data seed failed: %s", e)

        # 初始化默认工作流 DAG（为可视化编排打基础）
        try:
            from src.graph.workflow_dag import init_default_workflow
            wf = init_default_workflow()
            logger.info("Default workflow DAG ready: id=%s v%d", wf.id, wf.version)
        except Exception as e:
            logger.warning("Default workflow init failed: %s", e)

    @app.on_event("shutdown")
    async def shutdown():
        """应用停止：清理资源"""
        logger.info("App shutting down — cleaning up resources...")

        # 停止 Agent 健康检查器
        try:
            from src.protocols.health_checker import get_health_checker
            checker = get_health_checker()
            await checker.stop()
            logger.info("Agent health checker stopped")
        except Exception as e:
            logger.warning("Health checker stop failed: %s", e)

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
        app.include_router(router, prefix="/api/v1", tags=["对话与系统"])
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

    # 注册 Chatwoot webhook 路由
    try:
        from src.api.chatwoot import router as chatwoot_router
        app.include_router(chatwoot_router, prefix="/api/v1", tags=["Chatwoot 集成"])
        logger.info("Registered chatwoot router")
    except Exception as e:
        logger.error("Failed to register chatwoot router: %s", e)

    # 注册用户认证路由
    try:
        from src.api.auth import router as auth_router
        app.include_router(auth_router, prefix="/api/v1", tags=["认证 Auth"])
        logger.info("Registered auth router")
    except Exception as e:
        logger.error("Failed to register auth router: %s", e)

    # 注册管理后台路由
    try:
        from src.api.admin import router as admin_router
        app.include_router(admin_router, prefix="/api/v1", tags=["管理后台 Admin"])
        logger.info("Registered admin router")
    except Exception as e:
        logger.error("Failed to register admin router: %s", e)

    # 注册 RBAC 路由
    try:
        from src.api.rbac import router as rbac_router
        app.include_router(rbac_router, prefix="/api/v1", tags=["权限 RBAC"])
        logger.info("Registered rbac router")
    except Exception as e:
        logger.error("Failed to register rbac router: %s", e)

    # 注册客户管理路由
    try:
        from src.api.customers import router as customers_router
        app.include_router(customers_router, prefix="/api/v1", tags=["客户 Customers"])
        logger.info("Registered customers router")
    except Exception as e:
        logger.error("Failed to register customers router: %s", e)

    # 注册工单管理路由
    try:
        from src.api.tickets import router as tickets_router
        app.include_router(tickets_router, prefix="/api/v1", tags=["工单 Tickets"])
        logger.info("Registered tickets router")
    except Exception as e:
        logger.error("Failed to register tickets router: %s", e)

    # 注册满意度路由
    try:
        from src.api.satisfaction import router as satisfaction_router
        app.include_router(satisfaction_router, prefix="/api/v1", tags=["满意度 Satisfaction"])
        logger.info("Registered satisfaction router")
    except Exception as e:
        logger.error("Failed to register satisfaction router: %s", e)

    # 注册会话历史路由
    try:
        from src.api.conversations import router as conversations_router
        app.include_router(conversations_router, prefix="/api/v1", tags=["会话历史 Conversations"])
        logger.info("Registered conversations router")
    except Exception as e:
        logger.error("Failed to register conversations router: %s", e)

    # 注册通知中心路由
    try:
        from src.api.notifications import router as notifications_router
        app.include_router(notifications_router, prefix="/api/v1", tags=["通知 Notifications"])
        logger.info("Registered notifications router")
    except Exception as e:
        logger.error("Failed to register notifications router: %s", e)

    # 注册仪表盘路由
    try:
        from src.api.dashboard import router as dashboard_router
        app.include_router(dashboard_router, prefix="/api/v1", tags=["仪表盘 Dashboard"])
        logger.info("Registered dashboard router")
    except Exception as e:
        logger.error("Failed to register dashboard router: %s", e)

    # 注册 HITL (Human-in-the-loop) 路由
    try:
        from src.api.hitl import router as hitl_router
        app.include_router(hitl_router, prefix="/api/v1", tags=["人工介入 HITL"])
        logger.info("Registered HITL router")
    except Exception as e:
        logger.error("Failed to register HITL router: %s", e)

    # 注册 Agent 健康检查路由
    try:
        from src.api.health import router as health_router
        app.include_router(health_router, prefix="/api/v1", tags=["智能体健康 Health"])
        logger.info("Registered health router")
    except Exception as e:
        logger.error("Failed to register health router: %s", e)

    # 注册知识库管理路由
    try:
        from src.api.knowledge import router as knowledge_router
        app.include_router(knowledge_router, prefix="/api/v1", tags=["知识库 Knowledge"])
        logger.info("Registered knowledge router")
    except Exception as e:
        logger.error("Failed to register knowledge router: %s", e)

    # 注册工作流管理路由
    try:
        from src.api.workflow import router as workflow_router
        app.include_router(workflow_router, prefix="/api/v1", tags=["工作流 Workflow"])
        logger.info("Registered workflow router")
    except Exception as e:
        logger.error("Failed to register workflow router: %s", e)

    # 注册评估管理路由
    try:
        from src.api.evaluation import router as evaluation_router
        app.include_router(evaluation_router, prefix="/api/v1", tags=["质量评估 Evaluation"])
        logger.info("Registered evaluation router")
    except Exception as e:
        logger.error("Failed to register evaluation router: %s", e)

    # 注册配置中心路由
    try:
        from src.api.config import router as config_router
        app.include_router(config_router, prefix="/api/v1", tags=["配置中心 Config"])
        logger.info("Registered config router")
    except Exception as e:
        logger.error("Failed to register config router: %s", e)

    # 注册静态文件（必须在所有路由之后，否则会拦截 /api 请求）
    #
    # ⚠️ static/ 是前端构建产物，已被 .gitignore 忽略，因此在 CI、纯后端开发、
    #    刚 clone 的环境下都不存在。此处若无条件 mount，StaticFiles 会在
    #    create_app() 阶段直接抛 RuntimeError("Directory 'static' does not exist")，
    #    导致 `import src.api.server` 失败、整个测试模块 collect 崩溃。
    #    （GitHub Actions 曾因此连续多次红灯，本地却因构建过前端而始终看不到。）
    # 同时把路径从「依赖当前工作目录」改为基于仓库根解析，避免换 cwd 启动时挂载失效。
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles

    repo_root = Path(__file__).resolve().parents[2]
    static_dir = repo_root / "static"
    if not static_dir.is_dir():
        static_dir = Path("static")  # 兼容自定义工作目录的部署方式

    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
        logger.info("Mounted static frontend: %s", static_dir)
    else:
        logger.warning(
            "未找到 static/ 目录，跳过前端挂载，仅提供 API。"
            "需要前端请先执行 `cd frontend && npm run build`"
        )

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
