"""
应用接线守卫测试（App Wiring Guard）

为什么需要这一组测试：
    src/api/server.py 里每个 include_router 都包在 try/except 中。这个设计本意是
    「某个可选模块缺依赖时不要拖垮整个服务」，但副作用非常危险——一旦某个 router
    在特定环境（例如 CI 的干净依赖环境）导入失败，它会被静默跳过：
      - 进程照常启动，/health 照常返回 ok
      - 但该模块的所有接口全部 404
      - 日志里只有一行没有堆栈的 error，几乎无法定位

    真实事故：CI 上 tests/test_api/test_auth.py 的 10 个用例全部 assert 404 == 200，
    本地却完全正常，原因就是 auth router 在 CI 环境注册失败被吞掉了。

    这一组测试就是这类「静默残缺」的守卫：路由消失时，测试必须立刻红，
    并且直接把根因（完整异常信息）打印出来，而不是让人去猜。

写法注意：
    不要遍历 app.routes 判断路由是否存在。FastAPI 0.139+ 的 include_router 会先放一个
    延迟展开的 _IncludedRouter 占位对象，子路由在此时并不出现在 app.routes 里，
    直接遍历会得到「路由都不见了」的假阳性。改用 app.openapi()["paths"]，
    它对新旧版本都稳定，反映的是真正对外暴露的接口。
"""

import importlib

import pytest

# 需要守住的 router 模块清单（模块路径 -> 人类可读名）
# 任何一个导入失败，都意味着线上会静默少一批接口
ROUTER_MODULES = [
    ("src.api.routes", "main API"),
    ("src.websocket.routes", "WebSocket"),
    ("src.api.monitoring", "monitoring"),
    ("src.api.chatwoot", "chatwoot"),
    ("src.api.auth", "auth"),
    ("src.api.admin", "admin"),
    ("src.api.rbac", "rbac"),
    ("src.api.customers", "customers"),
    ("src.api.tickets", "tickets"),
    ("src.api.satisfaction", "satisfaction"),
    ("src.api.conversations", "conversations"),
    ("src.api.notifications", "notifications"),
    ("src.api.dashboard", "dashboard"),
    ("src.api.hitl", "HITL"),
    ("src.api.health", "health"),
    ("src.api.knowledge", "knowledge"),
    ("src.api.workflow", "workflow"),
    ("src.api.evaluation", "evaluation"),
    ("src.api.config", "config"),
]

# 安全关键路由：这些一旦消失，等于鉴权体系整体失效，必须硬性守住
SECURITY_CRITICAL_PATHS = [
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/me",
]


def _openapi_paths() -> set:
    """取出 app 实际对外暴露的全部路径（版本无关写法）。"""
    from src.api.server import app

    return set(app.openapi().get("paths", {}).keys())


@pytest.mark.parametrize("module_path,name", ROUTER_MODULES, ids=[n for _, n in ROUTER_MODULES])
def test_router_module_importable(module_path: str, name: str):
    """每个 router 模块都必须能独立导入。

    失败时保留原始 traceback，这样在 CI 上能直接看到是缺哪个依赖、
    哪一行 import 炸了，而不是只看到一句 "router 没注册"。
    """
    try:
        importlib.import_module(module_path)
    except Exception as e:  # noqa: BLE001 - 这里就是要把任何异常原样暴露出来
        pytest.fail(
            f"{name} router 模块导入失败（线上会静默丢失这批接口）\n"
            f"  模块: {module_path}\n"
            f"  异常: {type(e).__name__}: {e}",
            pytrace=True,
        )


def test_no_router_registration_errors():
    """create_app() 过程中不应有任何 router 注册失败。

    server.py 会把失败清单挂在 app.state.router_registration_errors 上，
    这里直接读它，比事后猜哪个接口 404 精确得多。
    """
    from src.api.server import app

    errors = getattr(app.state, "router_registration_errors", [])
    assert not errors, "以下 router 注册失败，其接口会全部 404：\n" + "\n".join(
        f"  - {name}: {msg}" for name, msg in errors
    )


@pytest.mark.parametrize("path", SECURITY_CRITICAL_PATHS)
def test_security_critical_route_present(path: str):
    """鉴权关键路由必须真实存在于 OpenAPI 中。"""
    paths = _openapi_paths()
    assert path in paths, (
        f"安全关键路由缺失: {path}\n"
        f"  当前 /api/v1/auth 下的路由: {sorted(p for p in paths if p.startswith('/api/v1/auth'))}"
    )


def test_route_count_sanity():
    """接口总量的下限保护。

    不追求精确数字（接口会持续增加），只守住一个下限：
    一旦大批 router 集体消失（例如某个公共依赖挂了），这里会立刻报警。
    """
    paths = _openapi_paths()
    assert len(paths) >= 50, (
        f"对外暴露的接口只剩 {len(paths)} 条，疑似大批 router 注册失败。\n"
        f"  现有路径示例: {sorted(paths)[:20]}"
    )
