"""
RAG 独立服务 — FastAPI 微服务

提供独立的检索 API，可独立部署、扩容。
被 api-service 和 agent-worker 通过 HTTP 调用。

启动方式:
  uvicorn src.rag.server:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import logging
import sys
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Enterprise Agent — RAG Service",
    version="0.1.0",
    description="独立 RAG 检索微服务（Milvus + BM25 混合检索）",
)


# ---- Request / Response Models ----

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    tenant_id: str = Field("", description="租户 ID")
    top_k: int = Field(5, ge=1, le=50)
    access_levels: Optional[List[str]] = Field(
        None, description="用户权限等级"
    )
    filter_expr: Optional[str] = Field(None, description="额外过滤表达式")


class SearchResult(BaseModel):
    chunk_id: str
    doc_id: str
    chunk_index: int
    text: str
    score: float
    access_level: str
    metadata: dict


class SearchResponse(BaseModel):
    results: List[SearchResult]
    total: int
    latency_ms: float


class IndexRequest(BaseModel):
    doc_id: str
    tenant_id: str
    text: str
    metadata: dict = Field(default_factory=dict)
    access_level: str = "public"


# ---- Health ----

@app.get("/health")
async def health():
    return {"status": "ok", "service": "rag-service"}


# ---- Prometheus Metrics ----

@app.get("/metrics")
async def metrics():
    """Prometheus text format /metrics 端点"""
    from fastapi.responses import PlainTextResponse
    from src.api.metrics import render_metrics
    return PlainTextResponse(render_metrics(), media_type="text/plain; charset=utf-8")


# ---- Search ----

@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    """混合检索：向量语义 + 标量过滤"""
    import time
    start = time.time()

    try:
        from src.rag.milvus_store import get_milvus_store

        store = get_milvus_store()
        hits = store.search(
            query_text=req.query,
            top_k=req.top_k,
            tenant_id=req.tenant_id,
            access_levels=req.access_levels,
            filter_expr=req.filter_expr,
        )

        results = [
            SearchResult(
                chunk_id=h["id"],
                doc_id=h["doc_id"],
                chunk_index=h["chunk_index"],
                text=h["text"],
                score=h["score"],
                access_level=h["access_level"],
                metadata=h["metadata"],
            )
            for h in hits
        ]

        latency_ms = (time.time() - start) * 1000
        logger.info("Search completed: query='%s', hits=%d, latency=%.1fms",
                     req.query[:50], len(results), latency_ms)

        return SearchResponse(results=results, total=len(results), latency_ms=latency_ms)

    except Exception as e:
        logger.exception("Search failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)[:200]}")


# ---- Index (Admin) ----

@app.post("/index")
async def index_document(req: IndexRequest):
    """索引单个文档（同步）"""
    # TODO: 实际索引逻辑 — Phase 2
    return {"status": "queued", "doc_id": req.doc_id}


@app.get("/stats")
async def stats():
    """向量库统计信息"""
    try:
        from src.rag.milvus_store import get_milvus_store
        store = get_milvus_store()
        return {"total_chunks": store.count(), "collection": store.collection_name}
    except Exception as e:
        return {"error": str(e), "total_chunks": 0}
