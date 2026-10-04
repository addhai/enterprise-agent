#!/usr/bin/env python
"""在服务端直接跑一次聊天工作流，验证「检索知识库 → 产出引用」这条契约

为什么需要这个脚本（而不是只靠 WebSocket 端到端）：
    内网 7B 模型在 CPU 上跑完整张 LangGraph 要 4~5 分钟，而 WS 客户端要在这个
    期间一直挂着连接。脚本化测试里连接容易被中间层或客户端自身超时打断，
    结果「没收到帧」并不能区分「没检索到」还是「连接断了」。
    本脚本绕过传输层，直接以 WS 处理器完全相同的初始 state 调用工作流，
    然后把事后被塞进 done 帧的 citations 打印出来，从而把问题定域清楚：
        - retrieved_docs 有内容 + citations 有内容 → 聊天侧的 RAG 契约成立
        - retrieved_docs 为空 → 问题在检索/租户过滤，不在传输

用法（在 app 容器内执行，因为要用镜像里的模块与配置）：
    docker exec prod-app-1 python /app/scripts/verify_chat_rag_citation.py \
        --question "XG-9000 的腔体预热温度是多少摄氏度，需要预热多久？" \
        --expect 187

退出码：0 表示 citations 非空且命中期望事实，1 表示未通过。
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--question",
        default="XG-9000 的腔体预热温度是多少摄氏度，需要预热多久？",
        help="要提问的内容",
    )
    ap.add_argument("--expect", default="", help="期望出现在引用内容里的关键事实")
    ap.add_argument("--tenant", default="default", help="租户 ID")
    ap.add_argument("--user", default="admin-default", help="用户 ID")
    ap.add_argument("--report", default="", help="把结果写入 JSON 文件")
    args = ap.parse_args()

    from langchain_core.messages import HumanMessage
    from src.api.dependencies import get_workflow

    # AgentState 由 src.api.routes 定义（WS 处理器也是从这里导入的），
    # 不要写成 src.graph.state，否则会拿不到同一份状态定义。
    from src.api.routes import AgentState
    from src.websocket.routes import _build_citations

    app = get_workflow()
    session_id = f"kb-verify-{int(time.time())}"

    # 与 src/websocket/routes.py 的 _handle_ai_chat 保持一致的初始状态
    state = AgentState(
        messages=[HumanMessage(content=args.question)],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
        user_id=args.user,
        session_id=session_id,
        tenant_id=args.tenant,
        user_access_levels=["public", "internal", "confidential", "restricted"],
        user_roles=[],
        user_plan="free",
        faq_match=None,
        effective_max_turns=5,
        has_reflected=False,
        memory_context="",
        quality_score=None,
        access_filtered=0,
        failed_attempts=0,
        suggest_human=False,
        awaiting_human=False,
        human_handoff_context=None,
        human_response=None,
        human_agent_id=None,
        human_handled=False,
    )

    print(f"[1/3] 调用工作流（question={args.question}）")
    t0 = time.perf_counter()
    result = app.invoke(state, {"configurable": {"thread_id": session_id}})
    elapsed = time.perf_counter() - t0
    print(f"      完成，耗时 {elapsed:.1f}s")

    retrieved = result.get("retrieved_docs") or []
    print(f"[2/3] retrieved_docs 条数 = {len(retrieved)}")
    for d in retrieved:
        meta = d.metadata or {}
        print(
            f"      - source={meta.get('source')} kb_id={meta.get('kb_id')} "
            f"doc_id={meta.get('doc_id')}"
        )

    # 这一行就是 WS done 帧里携带的 citations
    citations = _build_citations(retrieved)
    print(f"[3/3] citations 条数 = {len(citations)}")
    print(json.dumps(citations, ensure_ascii=False, indent=2)[:1600])

    answer = result.get("final_response") or ""
    print("\n--- final_response ---")
    print(answer[:800])

    ok_cites = len(citations) > 0
    joined = " ".join(
        (c.get("content") or "") + " " + (c.get("title") or "") for c in citations
    )
    ok_keyword = (args.expect in joined) if args.expect else True

    report = {
        "question": args.question,
        "elapsed_seconds": round(elapsed, 1),
        "retrieved_docs_count": len(retrieved),
        "retrieved_sources": [(d.metadata or {}).get("source") for d in retrieved],
        "citations_count": len(citations),
        "citations": citations,
        "answer": answer,
        "expect_keyword": args.expect,
        "keyword_found_in_citations": ok_keyword,
        "passed": bool(ok_cites and ok_keyword),
    }
    if args.report:
        from pathlib import Path

        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n报告已写入：{args.report}")

    print(f"\n结论：citations 非空={ok_cites} 期望事实命中={ok_keyword}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
