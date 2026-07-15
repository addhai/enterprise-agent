"""GitHub MCP 工具 — 仓库管理、Issue、PR、代码查询

使用 GitHub REST API (https://api.github.com)。
"""
import logging
from typing import Callable, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.tools import PermissionChecker
from src.config import settings
from src.mcp_tools.common import format_result, require_admin

logger = logging.getLogger(__name__)


def _github_request(method: str, path: str, params: dict = None, body: dict = None) -> dict:
    """GitHub API 请求"""
    import httpx

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "enterprise-agent",
    }
    if settings.mcp_github_token:
        headers["Authorization"] = f"token {settings.mcp_github_token}"

    url = f"https://api.github.com{path}"
    try:
        resp = httpx.request(
            method, url, headers=headers, params=params, json=body, timeout=15
        )
        if resp.status_code >= 400:
            return {"error": True, "status": resp.status_code, "message": resp.text}
        return resp.json()
    except Exception as e:
        logger.error("GitHub API error: %s", e)
        return {"error": True, "message": str(e)}


def _resolve_repo(owner: str = "", repo: str = "") -> tuple[str, str]:
    """解析仓库所有者和名称，使用默认配置填充"""
    o = owner or settings.mcp_github_default_owner
    r = repo or settings.mcp_github_default_repo
    return o, r


def create_github_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建 GitHub 工具集"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    if not settings.mcp_github_enabled:
        @tool
        def github_get_repo(owner: str = "", repo: str = "") -> str:
            """GitHub 工具（未启用）。"""
            return format_result("未启用", "GitHub MCP 服务未启用，请在配置中开启 mcp_github_enabled")

        return [github_get_repo]

    @tool
    def github_get_repo(owner: str = "", repo: str = "") -> str:
        """获取 GitHub 仓库信息。

        何时使用：想了解某个仓库的基本信息（Star、Fork、描述、语言等）。

        Args:
            owner: 仓库所有者（留空使用默认配置）
            repo: 仓库名（留空使用默认配置）
        """
        if not checker.check("github_get_repo"):
            return format_result("权限不足", "您没有权限查询 GitHub 仓库")

        o, r = _resolve_repo(owner, repo)
        if not o or not r:
            return format_result("参数错误", "请提供 owner 和 repo")

        result = _github_request("GET", f"/repos/{o}/{r}")
        if result.get("error"):
            return format_result("查询失败", result.get("message", "未知错误"))

        return format_result("查询成功", "", {
            "name": result.get("full_name", ""),
            "description": result.get("description", "")[:80] if result.get("description") else "",
            "stars": result.get("stargazers_count", 0),
            "forks": result.get("forks_count", 0),
            "open_issues": result.get("open_issues_count", 0),
            "language": result.get("language", ""),
            "default_branch": result.get("default_branch", ""),
            "license": result.get("license", {}).get("spdx_id", "") if result.get("license") else "",
        })

    @tool
    def github_list_issues(
        owner: str = "",
        repo: str = "",
        state: str = "open",
        labels: str = "",
        per_page: int = 20,
        page: int = 1,
    ) -> str:
        """列出 GitHub 仓库的 Issue。

        何时使用：需要查看仓库的 Issue 列表时。

        Args:
            owner: 仓库所有者
            repo: 仓库名
            state: 状态 open/closed/all，默认 open
            labels: 标签，逗号分隔，如 bug,feature
            per_page: 每页数量，默认 20
            page: 页码，默认 1
        """
        if not checker.check("github_list_issues"):
            return format_result("权限不足", "您没有权限查询 GitHub Issue")

        o, r = _resolve_repo(owner, repo)
        if not o or not r:
            return format_result("参数错误", "请提供 owner 和 repo")

        params = {"state": state, "per_page": per_page, "page": page}
        if labels:
            params["labels"] = labels

        result = _github_request("GET", f"/repos/{o}/{r}/issues", params=params)
        if isinstance(result, dict) and result.get("error"):
            return format_result("查询失败", result.get("message", "未知错误"))

        issues = result if isinstance(result, list) else []
        lines = [f"[查询成功] 共 {len(issues)} 个 Issue (state={state}):"]
        for issue in issues:
            if "pull_request" in issue:
                continue
            lines.append(
                f"  • #{issue.get('number', '')} [{issue.get('state', '')}] "
                f"{issue.get('title', '')[:60]} "
                f"({issue.get('user', {}).get('login', '')})"
            )
        return "\n".join(lines)

    @tool
    def github_create_issue(
        title: str,
        body: str = "",
        owner: str = "",
        repo: str = "",
        labels: str = "",
        assignees: str = "",
    ) -> str:
        """创建 GitHub Issue。

        何时使用：需要提交 Bug 报告、功能建议或任务时。

        Args:
            title: Issue 标题
            body: Issue 内容（支持 Markdown）
            owner: 仓库所有者
            repo: 仓库名
            labels: 标签，逗号分隔
            assignees: 负责人，逗号分隔
        """
        if not checker.check("github_create_issue"):
            return format_result("权限不足", "您没有权限创建 GitHub Issue")

        o, r = _resolve_repo(owner, repo)
        if not o or not r:
            return format_result("参数错误", "请提供 owner 和 repo")
        if not title:
            return format_result("参数错误", "标题不能为空")

        issue_body = {"title": title, "body": body}
        if labels:
            issue_body["labels"] = [l.strip() for l in labels.split(",") if l.strip()]
        if assignees:
            issue_body["assignees"] = [a.strip() for a in assignees.split(",") if a.strip()]

        result = _github_request("POST", f"/repos/{o}/{r}/issues", body=issue_body)
        if result.get("error"):
            return format_result("创建失败", result.get("message", "未知错误"))

        return format_result("创建成功", "", {
            "number": result.get("number", ""),
            "title": result.get("title", ""),
            "url": result.get("html_url", ""),
            "state": result.get("state", ""),
        })

    @tool
    def github_get_issue(number: int, owner: str = "", repo: str = "") -> str:
        """获取单个 GitHub Issue 的详情。

        何时使用：需要查看某个 Issue 的完整内容和评论时。

        Args:
            number: Issue 编号
            owner: 仓库所有者
            repo: 仓库名
        """
        if not checker.check("github_get_issue"):
            return format_result("权限不足", "您没有权限查看 GitHub Issue")

        o, r = _resolve_repo(owner, repo)
        if not o or not r:
            return format_result("参数错误", "请提供 owner 和 repo")

        result = _github_request("GET", f"/repos/{o}/{r}/issues/{number}")
        if result.get("error"):
            return format_result("查询失败", result.get("message", "未知错误"))

        labels = ", ".join(l.get("name", "") for l in result.get("labels", []))
        return format_result("查询成功", "", {
            "number": result.get("number", ""),
            "title": result.get("title", ""),
            "state": result.get("state", ""),
            "author": result.get("user", {}).get("login", ""),
            "labels": labels,
            "created_at": result.get("created_at", ""),
            "body": (result.get("body", "") or "")[:500],
            "comments": result.get("comments", 0),
            "url": result.get("html_url", ""),
        })

    @tool
    def github_list_pulls(
        owner: str = "",
        repo: str = "",
        state: str = "open",
        per_page: int = 20,
        page: int = 1,
    ) -> str:
        """列出 GitHub 仓库的 Pull Request。

        何时使用：需要查看 PR 列表、代码评审状态时。

        Args:
            owner: 仓库所有者
            repo: 仓库名
            state: 状态 open/closed/all，默认 open
            per_page: 每页数量，默认 20
            page: 页码，默认 1
        """
        if not checker.check("github_list_pulls"):
            return format_result("权限不足", "您没有权限查询 GitHub PR")

        o, r = _resolve_repo(owner, repo)
        if not o or not r:
            return format_result("参数错误", "请提供 owner 和 repo")

        params = {"state": state, "per_page": per_page, "page": page}
        result = _github_request("GET", f"/repos/{o}/{r}/pulls", params=params)
        if isinstance(result, dict) and result.get("error"):
            return format_result("查询失败", result.get("message", "未知错误"))

        prs = result if isinstance(result, list) else []
        lines = [f"[查询成功] 共 {len(prs)} 个 PR (state={state}):"]
        for pr in prs:
            lines.append(
                f"  • #{pr.get('number', '')} [{pr.get('state', '')}] "
                f"{pr.get('title', '')[:60]} "
                f"({pr.get('user', {}).get('login', '')}) "
                f"{pr.get('base', {}).get('ref', '')} ← {pr.get('head', {}).get('ref', '')}"
            )
        return "\n".join(lines)

    @tool
    def github_get_file_content(
        path: str,
        owner: str = "",
        repo: str = "",
        ref: str = "",
    ) -> str:
        """获取 GitHub 仓库中文件的内容。

        何时使用：需要查看仓库中某个文件的源代码时。

        Args:
            path: 文件路径，如 src/main.py
            owner: 仓库所有者
            repo: 仓库名
            ref: 分支/标签/commit，默认主分支
        """
        if not checker.check("github_get_file_content"):
            return format_result("权限不足", "您没有权限查看仓库文件")

        o, r = _resolve_repo(owner, repo)
        if not o or not r:
            return format_result("参数错误", "请提供 owner 和 repo")

        params = {}
        if ref:
            params["ref"] = ref

        result = _github_request("GET", f"/repos/{o}/{r}/contents/{path}", params=params)
        if result.get("error"):
            return format_result("查询失败", result.get("message", "未知错误"))

        if isinstance(result, list):
            lines = [f"[目录列表] {path}/ ({len(result)} 项):"]
            for item in result:
                icon = "📁" if item.get("type") == "dir" else "📄"
                lines.append(f"  {icon} {item.get('name', '')}")
            return "\n".join(lines)

        import base64

        content = result.get("content", "")
        if content:
            try:
                content = base64.b64decode(content).decode("utf-8", errors="replace")
            except Exception:
                pass

        return format_result("文件内容", f"{result.get('name', '')} ({result.get('size', 0)} bytes)", {
            "path": result.get("path", ""),
            "sha": result.get("sha", "")[:8],
            "content": content[:2000] if content else "",
        })

    @tool
    def github_search_code(
        query: str,
        owner: str = "",
        repo: str = "",
        per_page: int = 10,
    ) -> str:
        """在 GitHub 仓库中搜索代码。

        何时使用：需要在代码库中搜索特定内容时。

        Args:
            query: 搜索关键词
            owner: 仓库所有者（限定仓库时需要）
            repo: 仓库名（限定仓库时需要）
            per_page: 结果数量，默认 10
        """
        if not checker.check("github_search_code"):
            return format_result("权限不足", "您没有权限搜索代码")

        o, r = _resolve_repo(owner, repo)
        if o and r:
            query = f"{query} repo:{o}/{r}"

        params = {"q": query, "per_page": per_page}
        result = _github_request("GET", "/search/code", params=params)

        if result.get("error"):
            return format_result("搜索失败", result.get("message", "未知错误"))

        items = result.get("items", [])
        total = result.get("total_count", 0)
        lines = [f"[搜索完成] 共 {total} 个结果，显示前 {len(items)} 个:"]
        for item in items:
            lines.append(
                f"  • {item.get('repository', {}).get('full_name', '')}"
                f"/{item.get('path', '')}"
            )
        return "\n".join(lines)

    return [
        github_get_repo,
        github_list_issues,
        github_create_issue,
        github_get_issue,
        github_list_pulls,
        github_get_file_content,
        github_search_code,
    ]
