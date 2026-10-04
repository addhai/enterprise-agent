"""系统功能六维度验收测试：通过 /api/chat 接口验证回答准确性与引用来源

用法（需先启动 main.py 后端，端口 8000）：
    python scripts/acceptance_test.py
结果同时输出到控制台与 acceptance_report.md
"""

import re
import sys
import uuid
from pathlib import Path

import requests

BASE = "http://localhost:8000"


def chat(question: str, session_id: str) -> dict:
    resp = requests.post(
        f"{BASE}/api/chat",
        json={"question": question, "session_id": session_id},
        timeout=240,
    )
    resp.raise_for_status()
    return resp.json()


def fmt_citations(citations: list) -> str:
    if not citations:
        return "  （无引用）"
    lines = []
    for i, c in enumerate(citations, 1):
        chapter = f" | 章节: {c['chapter']}" if c.get("chapter") else ""
        lines.append(
            f"  [{i}] {c['source']}{chapter}\n      片段: {c['snippet'][:120]}..."
        )
    return "\n".join(lines)


def md_case(heading: str, question: str, result: dict, extra: str = "") -> str:
    """把一次验收结果渲染成报告 markdown 段落。

    抽出这个函数是为了让 5 个测试用例的报告行格式保持一致，
    同时避免每处都手写一条超长 f-string。
    """
    sources = [c["source"] for c in result.get("citations", [])]
    lines = [
        f"## {heading}",
        f"- 问题: {question}",
        f"- 回答: {result.get('answer', '')}",
    ]
    if extra:
        lines.append(extra)
    lines.append(f"- 引用: {sources}")
    return "\n".join(lines) + "\n"


def run_case(
    title: str, question: str, session_id: str | None = None
) -> tuple[str, dict]:
    sid = session_id or f"test-{uuid.uuid4().hex[:8]}"
    print(f"\n{'=' * 60}\n【{title}】\nQ: {question}", flush=True)
    try:
        r = chat(question, sid)
        answer, citations = r.get("answer", ""), r.get("citations", [])
        print(
            f"A: {answer}\n"
            f"引用来源:\n{fmt_citations(citations)}\n"
            f"needs_human={r.get('needs_human')} intent={r.get('intent')}",
            flush=True,
        )
        return sid, r
    except Exception as e:
        print(f"!! 调用失败: {e}", flush=True)
        return sid, {"error": str(e)}


def main():
    report = ["# 系统功能验收测试报告\n"]

    # 确认后端在线
    try:
        h = requests.get(f"{BASE}/api/health", timeout=5)
        print(f"后端健康检查: {h.json()}")
    except Exception as e:
        print(f"后端不可用: {e}")
        sys.exit(1)

    # ---- 测试1：基础参数问答 ----
    _, r1 = run_case("测试1 基础参数问答", "T100 测温范围是多少？")
    report.append(md_case("测试1 基础参数问答", "T100 测温范围是多少？", r1))

    # ---- 测试2：故障排查 ----
    _, r2 = run_case("测试2 故障排查", "报 E03 错误怎么处理？")
    report.append(md_case("测试2 故障排查", "报 E03 错误怎么处理？", r2))

    # ---- 测试3：专业场景 ----
    _, r3 = run_case("测试3 专业场景", "怎么自己校验设备准不准？")
    report.append(md_case("测试3 专业场景", "怎么自己校验设备准不准？", r3))

    # ---- 测试4：多轮对话连贯性（同一 session_id）----
    sid4 = f"test-multi-{uuid.uuid4().hex[:8]}"
    sid4, r4a = run_case("测试4a 多轮-第1轮", "怎么清洁镜头", session_id=sid4)
    _, r4b = run_case("测试4b 多轮-追问", "用什么布", session_id=sid4)
    report.append(
        f"## 测试4 多轮对话\n"
        f"- Q1: 怎么清洁镜头 → {r4a.get('answer', '')[:200]}\n"
        f"- Q2: 用什么布 → {r4b.get('answer', '')}\n"
        f"- 引用: {[c['source'] for c in r4b.get('citations', [])]}\n"
    )

    # ---- 测试5：转人工触发 ----
    _, r5 = run_case("测试5 转人工触发", "设备摔了屏幕碎了怎么办")
    report.append(
        md_case(
            "测试5 转人工触发",
            "设备摔了屏幕碎了怎么办",
            r5,
            extra=(
                f"- needs_human: {r5.get('needs_human')}\n- intent: {r5.get('intent')}"
            ),
        )
    )

    # ---- 测试6：知识库安全（静态核查）----
    print(f"\n{'=' * 60}\n【测试6 知识库安全验证】")
    st_src = Path("streamlit_app.py").read_text(encoding="utf-8")
    forbidden = [
        "chroma",
        "vector",
        "VectorStore",
        "data/docs",
        "load_directory",
        "Chroma",
        "ingest",
    ]
    hits = [w for w in forbidden if w in st_src]
    api_only = "/api/chat" in st_src and "/api/health" in st_src
    # 引用片段是否真做了截断：去 src/ 里找snippet 的切片逻辑，
    # 不能写死 True——那只是让报告好看，测不出任何东西。
    snippet_limited = False
    src_root = Path("src")
    for py in src_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if re.search(r"snippet\s*\[\s*:\s*\d+\s*\]", text):
            snippet_limited = True
            break
    kw_scan = f"命中 {hits}" if hits else "未命中（无向量库/知识库直接访问）"
    print(f"  前端代码敏感关键词扫描: {kw_scan}")
    print(f"  前端仅调用 /api/chat 与 /api/health: {api_only}")
    print(f"  后端引用片段截断: {snippet_limited}")
    report.append(
        "## 测试6 知识库安全\n"
        f"- 前端敏感关键词命中: {hits or '无'}\n"
        f"- 前端仅走 API: {api_only}\n"
        f"- 引用片段截断: {snippet_limited}\n"
    )

    Path("acceptance_report.md").write_text("\n".join(report), encoding="utf-8")
    print("\n报告已写入 acceptance_report.md")


if __name__ == "__main__":
    main()
