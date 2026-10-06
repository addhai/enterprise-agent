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
    ("src.api.config_center", "config_center"),
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


@pytest.mark.parametrize(
    "module_path,name", ROUTER_MODULES, ids=[n for _, n in ROUTER_MODULES]
)
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


def test_every_listed_router_is_actually_mounted():
    """每个登记在案的 router 模块，其路由必须真实出现在 OpenAPI 里。

    为什么需要这一条（2026-09-30 补充）：
        上面两个测试存在一个共同的盲区。test_router_module_importable 只验证
        「模块能被导入」，test_no_router_registration_errors 只验证「注册过程
        没抛异常」。如果一个模块写好了却压根没写 include_router 那几行代码，
        两件事都成立，测试全绿，但接口在线上是 404。

        真实案例：src/api/config_center.py（1527 行，含 36 个单测）就处于
        这种状态——模块能导入、注册无报错、守卫测试通过，但它从未被挂载。
        直到 36 个接口测试全部 404 才被发现。

        修法：这里不依赖 ROUTER_MODULES 的完整性，改为反向扫描——
        把 src/api/ 下所有「定义了 router 变量」的模块与 OpenAPI 实际路径
        做交叉验证，任何「有 router 但没挂载」的模块都会被点名。
    """
    import ast
    from pathlib import Path

    api_dir = Path(__file__).resolve().parents[2] / "src" / "api"
    server_path = api_dir / "server.py"

    # ---- 第一步：找出哪些模块定义了模块级 router 变量 ----
    defines_router: list[str] = []
    for py in sorted(api_dir.glob("*.py")):
        if py.name.startswith("_") or py.name in {"server.py", "dependencies.py"}:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        # 形如 router = APIRouter(...)
        defines_router.extend(
            py.stem
            for node in tree.body
            if isinstance(node, ast.Assign)
            for tgt in node.targets
            if isinstance(tgt, ast.Name) and tgt.id == "router"
        )

    # ---- 第二步：找出 server.py 真正 include_router 了哪些模块 ----
    # 关键：不能只匹配 import 语句。`import router as xxx` 这类别名写法会让
    # 单纯的 import 检查永远为真，测试形同虚设（2026-09-30 反向验证踩坑）。
    # 必须追踪「哪个 import 名来自哪个模块」→「哪个 import 名被 include_router 用」。
    server_src = server_path.read_text(encoding="utf-8")
    server_tree = ast.parse(server_src)

    # import_name -> 来源模块（如 config_center_router -> config_center）
    alias_to_module: dict[str, str] = {}
    for node in ast.walk(server_tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # 形如 from src.api.config_center import router as config_center_router
            if not node.module.startswith("src.api."):
                continue
            mod = node.module[len("src.api.") :]
            for a in node.names:
                if a.name == "router":
                    # 无别名时导入名就是 "router"（多个模块会互相覆盖，
                    # 所以只认带别名或本模块独有的情况）
                    alias_to_module[a.asname or "router"] = mod

    # 被实际用于挂载的 import 名。必须同时识别两种挂载形式：
    #   ① app.include_router(xxx_router, ...)      —— 主流写法
    #   ② for route in xxx_router.routes: app.add_api_route(...)
    #      —— monitoring.py 用的历史写法，等价但形态不同，只认 ① 会误报
    used_names: set[str] = set()
    for node in ast.walk(server_tree):
        # 形式①：include_router(xxx_router)
        if isinstance(node, ast.Call):
            fn = node.func
            is_include = (
                isinstance(fn, ast.Attribute) and fn.attr == "include_router"
            ) or (isinstance(fn, ast.Name) and fn.id == "include_router")
            if is_include and node.args:
                first = node.args[0]
                if isinstance(first, ast.Name):
                    used_names.add(first.id)
        # 形式②：xxx_router.routes（for 循环遍历子路由）
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "routes"
            and isinstance(node.value, ast.Name)
        ):
            used_names.add(node.value.id)

    mounted = {alias_to_module[n] for n in used_names if n in alias_to_module}
    missing = sorted(set(defines_router) - mounted)

    assert not missing, (
        "以下模块定义了 router 却从未在 src/api/server.py 挂载（或挂载后被注释），"
        "其接口在线上会全部 404：\n"
        + "\n".join(f"  - src/api/{m}.py" for m in missing)
        + "\n  修法：在 server.py 中补 include_router，并在上方 ROUTER_MODULES 登记。"
    )


@pytest.mark.parametrize("path", SECURITY_CRITICAL_PATHS)
def test_security_critical_route_present(path: str):
    """鉴权关键路由必须真实存在于 OpenAPI 中。"""
    paths = _openapi_paths()
    assert path in paths, (
        f"安全关键路由缺失: {path}\n"
        f"  当前 /api/v1/auth 下的路由: "
        f"{sorted(p for p in paths if p.startswith('/api/v1/auth'))}"
    )


def test_no_py311_only_stdlib_imports():
    """src 不得使用生产运行时（容器 Python 3.10）没有的标准库符号。

    为什么需要（2026-10-06 事故）：
        本地/CI 是 Python 3.14，``from datetime import UTC`` 完全合法，
        全部接线测试通过；但容器里是 3.10，config_center router 在
        create_app() 阶段 ImportError 被 try/except 吞掉，36 个接口静默 404，
        只有启动日志一行错误。这里做静态扫描，把版本差挡在上线前。
    """
    import ast
    from pathlib import Path

    # (导入模块, 被禁符号, 最低支持版本)。新增 3.11+ 语法时在这里登记。
    banned = [
        ("datetime", "UTC", (3, 11)),
        ("tomllib", None, (3, 11)),
    ]
    src_root = Path(__file__).resolve().parents[2] / "src"
    offenders = []
    for py in src_root.rglob("*.py"):
        # utf-8-sig：仓内个别文件带 BOM，CPython 能正常导入但 ast 需显式容忍
        tree = ast.parse(py.read_text(encoding="utf-8-sig"))
        rel = py.relative_to(src_root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for mod, symbol, _ver in banned:
                if node.module != mod:
                    continue
                if symbol is None or any(a.name == symbol for a in node.names):
                    offenders.append(
                        f"{rel}:{node.lineno} 从 {mod} 导入 {symbol or '*'}"
                    )

    assert not offenders, (
        "以下写法需要 Python 3.11+，但生产容器是 3.10，会导致 ImportError：\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n  datetime.UTC 请改用 datetime.timezone.utc。"
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
