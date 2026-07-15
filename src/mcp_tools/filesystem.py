"""文件系统 MCP 工具 — 沙箱化文件读写

安全策略：
  1. 沙箱隔离：所有操作限制在 mcp_fs_root_dir 目录内
  2. 路径穿越防护：拒绝包含 ../ 的路径
  3. 写入开关：mcp_fs_allow_write 控制是否允许写入操作
  4. 大小限制：单文件最大 10MB
"""
import logging
import os
import shutil
from pathlib import Path
from typing import Callable, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.tools import PermissionChecker
from src.config import settings
from src.mcp_tools.common import format_result, require_admin

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _get_root_dir() -> Path:
    """获取沙箱根目录"""
    root = Path(settings.mcp_fs_root_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_path(rel_path: str) -> Path:
    """解析路径并校验安全性，防止路径穿越"""
    root = _get_root_dir()
    target = (root / rel_path).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("路径越界：不允许访问沙箱目录之外的文件")

    return target


def _format_size(size: int) -> str:
    """格式化文件大小"""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"


def create_filesystem_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建文件系统工具集"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    if not settings.mcp_fs_enabled:
        @tool
        def fs_list_dir(path: str = ".") -> str:
            """文件系统工具（未启用）。"""
            return format_result("未启用", "文件系统 MCP 服务未启用，请在配置中开启 mcp_fs_enabled")

        return [fs_list_dir]

    @tool
    def fs_list_dir(path: str = ".", show_hidden: bool = False) -> str:
        """列出目录内容。

        何时使用：需要查看某个目录下有哪些文件和子目录时。

        Args:
            path: 相对路径，默认 .
            show_hidden: 是否显示隐藏文件，默认 false
        """
        if not checker.check("fs_list_dir"):
            return format_result("权限不足", "您没有权限浏览文件系统")

        try:
            target = _resolve_path(path)
        except ValueError as e:
            return format_result("路径错误", str(e))

        if not target.exists():
            return format_result("未找到", f"目录 {path} 不存在")
        if not target.is_dir():
            return format_result("参数错误", f"{path} 不是目录")

        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            if not show_hidden:
                entries = [e for e in entries if not e.name.startswith(".")]

            lines = [f"[目录列表] {path}/ ({len(entries)} 项):"]
            for entry in entries:
                icon = "📁" if entry.is_dir() else "📄"
                if entry.is_file():
                    size = _format_size(entry.stat().st_size)
                    lines.append(f"  {icon} {entry.name} ({size})")
                else:
                    lines.append(f"  {icon} {entry.name}/")
            return "\n".join(lines)
        except Exception as e:
            logger.error("fs_list_dir error: %s", e)
            return format_result("操作失败", str(e))

    @tool
    def fs_read_file(path: str) -> str:
        """读取文件内容（文本文件）。

        何时使用：需要查看某个文件的内容时。

        Args:
            path: 文件相对路径
        """
        if not checker.check("fs_read_file"):
            return format_result("权限不足", "您没有权限读取文件")

        try:
            target = _resolve_path(path)
        except ValueError as e:
            return format_result("路径错误", str(e))

        if not target.exists():
            return format_result("未找到", f"文件 {path} 不存在")
        if not target.is_file():
            return format_result("参数错误", f"{path} 不是文件")

        size = target.stat().st_size
        if size > _MAX_FILE_SIZE:
            return format_result("文件过大", f"文件大小 {_format_size(size)} 超过限制 {_format_size(_MAX_FILE_SIZE)}")

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            return format_result("读取成功", f"{path} ({_format_size(size)})", {
                "content": content[:5000],
                "truncated": len(content) > 5000,
            })
        except Exception as e:
            logger.error("fs_read_file error: %s", e)
            return format_result("读取失败", str(e))

    @tool
    def fs_write_file(path: str, content: str, overwrite: bool = False) -> str:
        """写入文件内容（仅文本，需开启写入权限）。

        何时使用：需要创建或更新文件时。需要 admin 权限且 mcp_fs_allow_write=true。

        Args:
            path: 文件相对路径
            content: 文件内容
            overwrite: 是否覆盖已存在的文件，默认 false
        """
        if not checker.check("fs_write_file"):
            return format_result("权限不足", "您没有权限写入文件")

        if not settings.mcp_fs_allow_write:
            return format_result("只读模式", "当前为只读模式，禁止写入文件")

        try:
            target = _resolve_path(path)
        except ValueError as e:
            return format_result("路径错误", str(e))

        if target.exists() and not overwrite:
            return format_result("文件已存在", f"{path} 已存在，设置 overwrite=true 可覆盖")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            size = target.stat().st_size
            return format_result("写入成功", f"已写入 {path} ({_format_size(size)})")
        except Exception as e:
            logger.error("fs_write_file error: %s", e)
            return format_result("写入失败", str(e))

    @tool
    def fs_delete_file(path: str) -> str:
        """删除文件或目录（需开启写入权限）。

        何时使用：需要删除不再需要的文件或目录时。需要 admin 权限。

        Args:
            path: 文件或目录相对路径
        """
        if not checker.check("fs_delete_file"):
            return format_result("权限不足", "您没有权限删除文件")
        if not require_admin(checker, "fs_delete_file"):
            return format_result("权限不足", "需要 admin 角色才能删除文件")

        if not settings.mcp_fs_allow_write:
            return format_result("只读模式", "当前为只读模式，禁止删除文件")

        try:
            target = _resolve_path(path)
        except ValueError as e:
            return format_result("路径错误", str(e))

        if not target.exists():
            return format_result("未找到", f"{path} 不存在")

        try:
            if target.is_file():
                target.unlink()
                return format_result("删除成功", f"文件 {path} 已删除")
            else:
                shutil.rmtree(target)
                return format_result("删除成功", f"目录 {path} 已递归删除")
        except Exception as e:
            logger.error("fs_delete_file error: %s", e)
            return format_result("删除失败", str(e))

    @tool
    def fs_mkdir(path: str) -> str:
        """创建目录（需开启写入权限）。

        何时使用：需要创建新的目录用于组织文件时。

        Args:
            path: 目录相对路径
        """
        if not checker.check("fs_mkdir"):
            return format_result("权限不足", "您没有权限创建目录")

        if not settings.mcp_fs_allow_write:
            return format_result("只读模式", "当前为只读模式，禁止创建目录")

        try:
            target = _resolve_path(path)
        except ValueError as e:
            return format_result("路径错误", str(e))

        if target.exists():
            return format_result("已存在", f"目录 {path} 已存在")

        try:
            target.mkdir(parents=True, exist_ok=True)
            return format_result("创建成功", f"目录 {path} 已创建")
        except Exception as e:
            logger.error("fs_mkdir error: %s", e)
            return format_result("创建失败", str(e))

    @tool
    def fs_stat(path: str) -> str:
        """获取文件/目录信息（大小、修改时间、类型等）。

        何时使用：需要了解文件的详细属性时。

        Args:
            path: 文件或目录相对路径
        """
        if not checker.check("fs_stat"):
            return format_result("权限不足", "您没有权限查看文件信息")

        try:
            target = _resolve_path(path)
        except ValueError as e:
            return format_result("路径错误", str(e))

        if not target.exists():
            return format_result("未找到", f"{path} 不存在")

        try:
            stat = target.stat()
            import datetime

            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
            ftype = "目录" if target.is_dir() else "文件"
            size = _format_size(stat.st_size) if target.is_file() else "-"

            return format_result("文件信息", f"{path} ({ftype})", {
                "name": target.name,
                "type": ftype,
                "size": size,
                "modified": mtime,
                "absolute_path": str(target),
            })
        except Exception as e:
            logger.error("fs_stat error: %s", e)
            return format_result("查询失败", str(e))

    @tool
    def fs_search(pattern: str, path: str = ".", max_results: int = 50) -> str:
        """按文件名搜索文件。

        何时使用：需要在目录树中查找特定名称的文件时。

        Args:
            pattern: 文件名匹配模式（支持 * 通配符）
            path: 搜索起点目录，默认 .
            max_results: 最大结果数，默认 50
        """
        if not checker.check("fs_search"):
            return format_result("权限不足", "您没有权限搜索文件")

        try:
            target = _resolve_path(path)
        except ValueError as e:
            return format_result("路径错误", str(e))

        if not target.exists() or not target.is_dir():
            return format_result("未找到", f"目录 {path} 不存在")

        import fnmatch

        results = []
        try:
            for root, dirs, files in os.walk(target):
                # 跳过隐藏目录
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if f.startswith("."):
                        continue
                    if fnmatch.fnmatch(f.lower(), pattern.lower()):
                        full_path = Path(root) / f
                        rel_path = full_path.relative_to(_get_root_dir())
                        results.append(str(rel_path))
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break

            lines = [f"[搜索结果] 模式: {pattern}，找到 {len(results)} 个:"]
            for r in results:
                lines.append(f"  • {r}")
            return "\n".join(lines)
        except Exception as e:
            logger.error("fs_search error: %s", e)
            return format_result("搜索失败", str(e))

    return [
        fs_list_dir,
        fs_read_file,
        fs_write_file,
        fs_delete_file,
        fs_mkdir,
        fs_stat,
        fs_search,
    ]
