#!/usr/bin/env python3
"""
Enterprise Agent — 单进程轻量 Demo 启动脚本

用途
----
一键启动「后端 + 前端 + WebSocket」最小可演示实例：
- 后端：FastAPI + LangGraph Agent（ VECTOR_STORE_BACKEND=chroma 避免 Milvus 依赖）
- 前端：后端用 StaticFiles 托管 static/ 目录（同源，避免跨域）
- WebSocket：/ws/chat 为聊天主链路

前置条件
--------
1. Python 依赖已安装（requirements.txt）
2. Node 依赖已安装（frontend/node_modules）
3. 已执行 `cd frontend && npm run build` 生成 static/ 产物
4. 项目根目录存在 `.env` 且填入了 OPENAI_API_KEY（DashScope key）

使用
----
    python scripts/run_demo.py

Windows 推荐在 Git Bash / PowerShell 中运行；脚本会自动优先使用 venv/Scripts/python.exe。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
STATIC_INDEX = PROJECT_ROOT / "static" / "index.html"


def _print(msg: str, *, fatal: bool = False) -> None:
    prefix = "❌ " if fatal else "ℹ️  "
    print(f"{prefix}{msg}")


def find_python() -> Path:
    """优先使用项目 venv，其次 .venv，最后系统 python。"""
    candidates = [
        PROJECT_ROOT / "venv" / "Scripts" / "python.exe",   # Windows
        PROJECT_ROOT / "venv" / "bin" / "python",           # Unix
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        PROJECT_ROOT / ".venv" / "bin" / "python",          # Unix
        Path(sys.executable),
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    _print("找不到可用的 Python 解释器，请先创建 venv 并安装依赖。", fatal=True)
    sys.exit(1)


def ensure_env() -> None:
    """确保 .env 存在；若不存在则从模板复制并提示用户。"""
    if ENV_FILE.exists():
        content = ENV_FILE.read_text(encoding="utf-8")
        if "OPENAI_API_KEY=sk-xxx" in content or "OPENAI_API_KEY=" not in content:
            _print(".env 中的 OPENAI_API_KEY 仍是占位符，聊天会失败。请填入真实 DashScope key 后重试。", fatal=True)
            sys.exit(1)
        return

    if ENV_EXAMPLE.exists():
        shutil.copy(ENV_EXAMPLE, ENV_FILE)
        _print(f"已从 {ENV_EXAMPLE.name} 创建 {ENV_FILE.name}。请编辑它填入 OPENAI_API_KEY，然后重新运行本脚本。")
    else:
        _print("缺少 .env 与 .env.example，无法启动。", fatal=True)
    sys.exit(1)


def ensure_static_build() -> None:
    """确保前端产物已生成。"""
    if STATIC_INDEX.exists():
        return
    _print("static/index.html 不存在。请先构建前端：")
    print("   cd frontend")
    print("   npm run build")
    print("   cd ..")
    print("   python scripts/run_demo.py")
    sys.exit(1)


def main() -> int:
    check_only = "--check" in sys.argv[1:]

    ensure_env()
    ensure_static_build()

    python = find_python()
    _print(f"使用 Python: {python}")

    env = os.environ.copy()
    env.setdefault("VECTOR_STORE_BACKEND", "chroma")
    env.setdefault("PYTHONUNBUFFERED", "1")

    host = env.get("HOST", "0.0.0.0")
    port = env.get("PORT", "8000")

    cmd = [
        str(python), "-m", "uvicorn",
        "src.api.server:app",
        "--host", host,
        "--port", port,
    ]

    if check_only:
        _print("前置检查通过。将要执行的命令：")
        print("   " + " ".join(cmd))
        print(f"   访问地址：http://{host}:{port}")
        return 0

    _print(f"启动 Enterprise Agent demo: http://{host}:{port}")
    _print("按 Ctrl+C 停止服务")

    try:
        return subprocess.call(cmd, cwd=PROJECT_ROOT, env=env)
    except KeyboardInterrupt:
        _print("收到中断信号，正在停止...")
        return 0


if __name__ == "__main__":
    sys.exit(main())
