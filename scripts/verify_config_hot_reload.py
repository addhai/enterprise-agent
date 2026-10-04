#!/usr/bin/env python
"""验证 retrieval_top_k 的热更新是否真正作用于检索路径

为什么不能用 hit_test 做这个验证
--------------------------------
`POST /api/v1/admin/knowledge/{kb_id}/hit_test` 的 top_k 取自请求体
（代码里是 `top_k=req.top_k`），完全不读配置中心。用它来测
retrieval_top_k 的热更新，结果只会跟随请求体里的数字变化，从而得出
「改了配置没效果」的错误结论。

真实的消费方是谁
----------------
运行时读 `settings.retrieval_top_k` 的检索路径只有 Agent 的
`search_knowledge_base` 工具（src/agent/tools.py）。本脚本就直接调用它，
并在检索器上挂一层探针，记录该工具**实际传下去的 top_k** 与**返回的文档条数**。

这样测的是真实代码路径，而不是脚本里另写一遍取配置的逻辑。

用法（在 app 容器内运行，保证与线上同一份代码和同一个检索器单例）：
    docker exec -e PYTHONPATH=/app prod-app-1 python /tmp/verify_config_hot_reload.py \
        --query "XG-9000 腔体预热温度" --label baseline

输出：一行 JSON，含 config_value / top_k_passed_to_retriever / docs_returned。
退出码 0 表示工具执行成功，1 表示失败。
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--query", default="XG-9000 腔体预热温度", help="检索词，需要能命中知识库文档"
    )
    ap.add_argument("--label", default="", help="本轮标签，仅用于输出标识")
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--user", default="admin-default")
    ap.add_argument(
        "--set-value",
        type=int,
        default=None,
        help=(
            "在本进程内直接把 retrieval_top_k 设为该值后再跑工具。"
            "注意：这只影响本进程，用来验证「工具是否真的在调用时读取配置」；"
            "验证 HTTP PUT 的跨进程传播请用接口 + 进程内测试，"
            "因为 docker exec 起的是独立进程，读不到 API 进程的内存。"
        ),
    )
    args = ap.parse_args()

    result = {"label": args.label, "query": args.query, "ok": False}

    # 先按需在**本进程内**设置配置（走配置中心，与线上同一套校验与版本号逻辑）
    if args.set_value is not None:
        try:
            from src.config_center import get_config_center

            center = get_config_center()
            before = center.get_value("retrieval_top_k")
            center.set_value(
                "retrieval_top_k",
                args.set_value,
                operator="verify-script",
                operator_ip="local",
                source="verify",
            )
            result["inprocess_set"] = {
                "from": before,
                "to": center.get_value("retrieval_top_k"),
            }
        except Exception as e:
            result["error"] = f"进程内设置失败: {type(e).__name__}: {e}"
            print(json.dumps(result, ensure_ascii=False))
            return 1

    try:
        from src.agent.tools import create_tools
        from src.api.dependencies import get_retriever
        from src.config import settings
    except Exception as e:
        result["error"] = f"import 失败: {type(e).__name__}: {e}"
        print(json.dumps(result, ensure_ascii=False))
        return 1

    # 记录配置中心当前值（读的是运行时 settings 对象）
    result["config_value"] = getattr(settings, "retrieval_top_k", None)
    result["config_version"] = None
    try:
        from src.config_center import get_config_center

        result["config_version"] = get_config_center().version
    except Exception as exc:  # noqa: S110 —— 配置中心不可用时降级为「版本未知」，不中断探针
        result["config_version_error"] = type(exc).__name__

    retriever = get_retriever()
    if retriever is None:
        result["error"] = "检索器不可用（get_retriever 返回 None）"
        print(json.dumps(result, ensure_ascii=False))
        return 1

    # 与图节点一致的入参构造（见 src/graph/nodes.py 里 create_tools 的调用）
    tools = create_tools(
        retriever=retriever,
        user_id=args.user,
        tenant_id=args.tenant,
        user_access_levels=["public", "internal", "confidential", "restricted"],
        roles=["admin"],
        plan="free",
    )
    target = next(
        (t for t in tools if getattr(t, "name", "") == "search_knowledge_base"), None
    )
    if target is None:
        result["error"] = "未找到 search_knowledge_base 工具"
        print(json.dumps(result, ensure_ascii=False))
        return 1

    # ---- 探针：记录工具实际传给检索器的 top_k 与返回条数 ----
    # 包在实例上而不是改类，避免影响其它调用方；脚本进程结束即失效。
    calls: list = []
    original_search = retriever.search

    def spied_search(query, top_k=None, *a, **kw):
        docs = original_search(query, top_k=top_k, *a, **kw)
        calls.append(
            {
                "top_k_passed": top_k,
                "docs_returned": len(docs) if docs is not None else 0,
            }
        )
        return docs

    retriever.search = spied_search  # type: ignore[assignment]

    try:
        text = target.invoke({"query": args.query})
    except Exception as e:
        result["error"] = f"工具执行失败: {type(e).__name__}: {e}"
        print(json.dumps(result, ensure_ascii=False))
        return 1
    finally:
        retriever.search = original_search  # type: ignore[assignment]

    text = text if isinstance(text, str) else str(text)
    result["tool_return_len"] = len(text)
    # 工具返回体用 "[Doc i - source]" 标记每条命中，可独立交叉核对条数
    result["doc_markers_in_text"] = text.count("[Doc ")
    result["retriever_calls"] = calls
    if calls:
        result["top_k_passed_to_retriever"] = calls[0]["top_k_passed"]
        result["docs_returned"] = calls[0]["docs_returned"]
        result["total_docs_returned"] = sum(c["docs_returned"] for c in calls)
    result["ok"] = True
    result["tool_text_head"] = text[:200]

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
