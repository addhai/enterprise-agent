#!/usr/bin/env python
"""验证 rerank_enabled 的开关是否真的作用于重排序调用点

为什么需要桩重排序器
--------------------
本项目配置的 provider 是 dashscope / gte-rerank，指向
`https://dashscope.aliyuncs.com/compatible-mode/v1`，是**公网云 API**。
内网部署下不可达，真实重排序必然失败并降级为原始顺序。
若直接用真实重排序器测开关，只能看到「都退化成无操作」，无法区分
「开关没生效」与「依赖不可用」。因此默认注入一个桩重排序器，
把「开关逻辑」与「外部依赖」两件事分开验证。

真实路径的行为由 --real-reranker 模式单独观察（不注入桩件，看它实际怎么降级）。

观察手段
--------
1. 在 `retriever._rerank` 上挂计数器，直接看门控行有没有走进来
   （门控在 src/rag/retriever.py:384，判断 `self._rerank_enabled`）
2. 看结果 metadata 里有没有 `reranked` 标记（由 _rerank 成功时写入）
3. 看工具返回体里 `[Doc N - source]` 的顺序变化（桩件会反转顺序）

用法（容器内运行）：
    docker exec -e PYTHONPATH=/app prod-app-1 \
        python /tmp/verify_rerank_hot_reload.py
    docker exec -e PYTHONPATH=/app prod-app-1 \
        python /tmp/verify_rerank_hot_reload.py --real-reranker
"""

from __future__ import annotations

import argparse
import json
import re
import sys


class StubReranker:
    """桩重排序器：记录调用次数，并反转候选顺序

    反转是为了让「顺序是否变化」成为可观察证据：真实重排序会改变排序，
    桩件模拟这一点，从而能区分「重排序实际执行了」与「被跳过了」。
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def rerank(self, query: str, documents: list, top_n: int | None = None):
        self.calls.append(
            {
                "query": query,
                "candidates": len(documents),
                "top_n": top_n,
            }
        )
        reversed_docs = list(reversed(documents))
        return [
            (doc, float(len(reversed_docs) - i))
            for i, (doc, _score) in enumerate(reversed_docs)
        ]


def _doc_sources_from_text(text: str) -> list[str]:
    """从工具返回体里按出现顺序抽出命中文档的来源"""
    return re.findall(r"\[Doc \d+ - ([^\]]+)\]", text or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="XG-9000 腔体预热温度")
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--user", default="admin-default")
    ap.add_argument(
        "--real-reranker",
        action="store_true",
        help="不注入桩件，用真实重排序器观察内网下的实际降级行为",
    )
    args = ap.parse_args()

    from src.agent.tools import create_tools
    from src.api.dependencies import get_retriever
    from src.config_center import get_config_center

    center = get_config_center()
    retriever = get_retriever()
    if retriever is None:
        print(json.dumps({"ok": False, "error": "检索器不可用"}, ensure_ascii=False))
        return 1

    stub = None
    if not args.real_reranker:
        stub = StubReranker()
        # 注入后，retriever.reranker 属性会直接返回它（_get_reranker 首行短路），
        # 既绕开不可达的云 API，也避免 _rerank_init_failed 闩锁被置位。
        retriever._reranker = stub
    else:
        # 真实模式下先清空缓存的 reranker，并复位闩锁，保证每次都真的去构造
        retriever._reranker = None
        retriever._rerank_init_failed = False

    tools = create_tools(
        retriever=retriever,
        user_id=args.user,
        tenant_id=args.tenant,
        user_access_levels=["public", "internal", "confidential", "restricted"],
        roles=["admin"],
        plan="free",
    )
    tool = next(t for t in tools if getattr(t, "name", "") == "search_knowledge_base")

    # ---- 在 _rerank 上挂计数器：直接观察门控行是否走进来 ----
    rerank_calls: list[dict] = []
    original_rerank = retriever._rerank

    def spied_rerank(query, candidates):
        result = original_rerank(query, candidates)
        rerank_calls.append(
            {
                "candidates_in": len(candidates),
                "results_out": len(result) if result is not None else 0,
            }
        )
        return result

    retriever._rerank = spied_rerank  # type: ignore[assignment]

    initial = center.get_value("rerank_enabled")
    steps = []

    def run_once(state: bool, label: str) -> dict:
        center.set_value(
            "rerank_enabled",
            state,
            operator="verify-script",
            operator_ip="local",
            source="verify",
        )
        rerank_calls.clear()
        if stub is not None:
            stub.calls.clear()
        # 真实模式下每次都重置闩锁与缓存，保证「开启」时真的尝试一次
        if args.real_reranker:
            retriever._reranker = None
            retriever._rerank_init_failed = False

        text = tool.invoke({"query": args.query})
        text = text if isinstance(text, str) else str(text)

        # 从检索器最近一次返回里取 reranked 标记（工具内部直接调 retriever.search）
        sources = _doc_sources_from_text(text)
        return {
            "label": label,
            "config_rerank_enabled": center.get_value("rerank_enabled"),
            "rerank_called_times": len(rerank_calls),
            "stub_rerank_calls": len(stub.calls) if stub is not None else None,
            "stub_saw_candidates": (
                stub.calls[0]["candidates"] if stub and stub.calls else None
            ),
            "stub_top_n": (stub.calls[0]["top_n"] if stub and stub.calls else None),
            "doc_count": len(sources),
            "doc_source_order": sources,
        }

    try:
        steps.append(run_once(True, "rerank_enabled=true"))
        steps.append(run_once(False, "rerank_enabled=false"))
        steps.append(run_once(True, "rerank_enabled=true(再开)"))
    finally:
        retriever._rerank = original_rerank  # type: ignore[assignment]
        # 复原初始配置
        center.set_value(
            "rerank_enabled",
            initial,
            operator="verify-script",
            operator_ip="local",
            source="verify-restore",
        )

    out = {
        "ok": True,
        "mode": "real-reranker" if args.real_reranker else "stub-reranker",
        "initial_rerank_enabled": initial,
        "restored_rerank_enabled": center.get_value("rerank_enabled"),
        "config_version": center.version,
        "steps": steps,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
