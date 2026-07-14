"""
远程 RAG 客户端 — api-service / agent-worker 调用 rag-service 的工具

当 retriever 的 backend 设为 "remote" 时，HybridRetriever 内部已使用 HTTP 调用。
此模块提供独立于 retriever 的直接 RAG API 客户端，用于:
  1. api-service 内直接调用（绕过 retriever 本地索引）
  2. agent-worker 消费 MQ 消息时调用远程检索
  3. 管理接口（/index /stats 等）

使用方式:
    from src.rag.remote_client import RagClient
    client = RagClient()
    results = await client.search("SSO 配置", tenant_id="t1", top_k=5)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class RagClient:
    """RAG Service HTTP 客户端

    支持同步和异步调用。
    内置重试 + 超时 + 熔断降级。
    """

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url or settings.rag_service_url
        self.timeout = timeout or settings.rag_service_timeout
        self.max_retries = max_retries

        # 熔断状态
        self._failure_count = 0
        self._circuit_open_until: float = 0.0
        self._circuit_threshold = 5
        self._circuit_reset_seconds = 30

    # ------------------------------------------------------------------
    # 同步接口
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        tenant_id: str = "",
        top_k: int = 5,
        access_levels: Optional[List[str]] = None,
        filter_expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """同步检索（内部用 httpx 同步客户端）"""
        payload = {
            "query": query,
            "tenant_id": tenant_id,
            "top_k": top_k,
            "access_levels": access_levels,
            "filter_expr": filter_expr,
        }
        return self._request("POST", "/search", json=payload).get("results", [])

    def stats(self) -> Dict[str, Any]:
        """向量库统计"""
        return self._request("GET", "/stats")

    def health(self) -> bool:
        """检查 RAG Service 健康状态"""
        try:
            resp = self._request("GET", "/health")
            return resp.get("status") == "ok"
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 异步接口
    # ------------------------------------------------------------------

    async def search_async(
        self,
        query: str,
        tenant_id: str = "",
        top_k: int = 5,
        access_levels: Optional[List[str]] = None,
        filter_expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """异步检索"""
        payload = {
            "query": query,
            "tenant_id": tenant_id,
            "top_k": top_k,
            "access_levels": access_levels,
            "filter_expr": filter_expr,
        }
        resp = await self._request_async("POST", "/search", json=payload)
        return resp.get("results", [])

    async def stats_async(self) -> Dict[str, Any]:
        """异步统计"""
        return await self._request_async("GET", "/stats")

    # ------------------------------------------------------------------
    # 内部：HTTP 调用 + 重试 + 熔断
    # ------------------------------------------------------------------

    def _request(
        self, method: str, path: str, json: dict = None
    ) -> Dict[str, Any]:
        """同步 HTTP 请求（带重试 + 熔断）"""
        if self._is_circuit_open():
            logger.warning("Circuit breaker open, skipping RAG request: %s %s", method, path)
            return {"results": [], "error": "circuit_breaker_open"}

        last_error = None
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    url = f"{self.base_url}{path}"
                    if method == "GET":
                        resp = client.get(url)
                    else:
                        resp = client.post(url, json=json, headers={"Content-Type": "application/json"})
                    resp.raise_for_status()
                    self._circuit_success()
                    return resp.json()
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning("RAG HTTP %s (attempt %d/%d): %s %s → %d",
                               e.response.status_code, attempt + 1,
                               self.max_retries, method, path, e.response.status_code)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                logger.warning("RAG connection error (attempt %d/%d): %s",
                               attempt + 1, self.max_retries, e)

        self._circuit_failure()
        raise last_error or RuntimeError(f"RAG request failed: {method} {path}")

    async def _request_async(
        self, method: str, path: str, json: dict = None
    ) -> Dict[str, Any]:
        """异步 HTTP 请求（带重试 + 熔断）"""
        if self._is_circuit_open():
            return {"results": [], "error": "circuit_breaker_open"}

        last_error = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    url = f"{self.base_url}{path}"
                    if method == "GET":
                        resp = await client.get(url)
                    else:
                        resp = await client.post(url, json=json, headers={"Content-Type": "application/json"})
                    resp.raise_for_status()
                    self._circuit_success()
                    return resp.json()
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e

        self._circuit_failure()
        raise last_error or RuntimeError(f"RAG async request failed: {method} {path}")

    # ------------------------------------------------------------------
    # 熔断器
    # ------------------------------------------------------------------

    def _is_circuit_open(self) -> bool:
        import time
        if self._circuit_open_until and time.time() < self._circuit_open_until:
            return True
        # 过了熔断时间，进入半开状态
        if self._failure_count >= self._circuit_threshold:
            self._circuit_open_until = 0  # 半开，允许一次尝试
            self._failure_count = 0
        return False

    def _circuit_success(self):
        self._failure_count = 0
        self._circuit_open_until = 0

    def _circuit_failure(self):
        import time
        self._failure_count += 1
        if self._failure_count >= self._circuit_threshold:
            self._circuit_open_until = time.time() + self._circuit_reset_seconds
            logger.error("Circuit breaker OPEN for %ds", self._circuit_reset_seconds)


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_rag_client: Optional[RagClient] = None


def get_rag_client() -> RagClient:
    global _rag_client
    if _rag_client is None:
        _rag_client = RagClient()
    return _rag_client
