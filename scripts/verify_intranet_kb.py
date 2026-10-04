"""离线向量库验收脚本：核对双集合条数、向量维度（bge-m3=1024）、来源覆盖、抽样语义检索。

每个用例均打印：输入 / 预期 / 实际 / PASS|FAIL。
用例1~5 纯本地校验（零网络）；用例6~8 实时调用 bge-m3 生成 query 向量；
用例9 为端到端防幻觉负面用例（需业务容器 /api/chat 在线，默认 http://localhost:8000）。
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings  # noqa: E402
from src.rag.vector_store import VectorStoreManager  # noqa: E402

EXPECTED_DIM = 1024
# 标准集合条数：切块策略升级后由 151 → 301。
# 原切块器的标题分隔符写的是字面量 "\n### "，而 loader 会把标题转义成 "\n\\### "，
# 分隔符永不命中 → 退化成按长度硬切 → 表格被切半、答案行落在块尾、块尾粘上下
# 一节标题。改为章节感知切块（一节一块 + 丢弃空标题 + 丢弃水平线）后，块数增加
# 但块内语义纯度显著提升（校准 §3.1 环境表、故障3 排查表各自完整成块）。
EXPECTED_STD = 301
EXPECTED_SENT = 956

# (用例输入, top1 来源文件名必须包含的关键字)
# 注：知识库 7 篇文档经全文核实不含任何「E03」类错误码（故障手册以
# 「故障1/故障3」命名），故检索用例只选文档真实覆盖的主题。
RETRIEVAL_CASES = [
    ("T100 测温范围", "product_spec_manual"),
    ("激光定位灯不亮怎么处理", "fault_troubleshooting_manual"),
    ("保修期限多久", "after_sales_policy"),
]

fails = []


def report(case_id: str, given: str, expected: str, actual: str, ok: bool) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] 用例{case_id}")
    print(f"        输入: {given}")
    print(f"        预期: {expected}")
    print(f"        实际: {actual}")
    if not ok:
        fails.append(f"用例{case_id} {given}")


print("=" * 72)
print("内网离线向量库验收 (bge-m3 / 1024d)")
print(f"  embedding_provider = {settings.embedding_provider}")
print(f"  embedding_model    = {settings.embedding_model}")
print(f"  embedding_dims     = {settings.embedding_dimensions}")
print(f"  openai_api_base    = {settings.openai_api_base}")
print(f"  chroma_dir         = {settings.chroma_persist_dir}")
print(f"  collection(std)    = {settings.chroma_collection_name}")
print(f"  collection(sent)   = {settings.chroma_collection_name}_sentences")
print("=" * 72)

std = VectorStoreManager()
sent = VectorStoreManager(
    collection_name=f"{settings.chroma_collection_name}_sentences"
)

std_col = std.store._collection
sent_col = sent.store._collection

# ---- 用例1：标准集合条数 ----
n_std = std_col.count()
report(
    "1",
    "标准集合文档分片条数",
    f"{EXPECTED_STD} 条",
    f"{n_std} 条",
    n_std == EXPECTED_STD,
)

# ---- 用例2：句子集合条数 ----
n_sent = sent_col.count()
report(
    "2",
    "句子集合分片条数",
    f"{EXPECTED_SENT} 条",
    f"{n_sent} 条",
    n_sent == EXPECTED_SENT,
)

# ---- 用例3：标准向量维度 ----
peek = std_col.peek(limit=5)
dims = sorted({len(v) for v in peek["embeddings"]})
report(
    "3",
    "标准集合向量维度(bge-m3)",
    f"全部为 {EXPECTED_DIM} 维",
    f"抽样{len(peek['embeddings'])}条维度集合={dims}",
    dims == [EXPECTED_DIM],
)

# ---- 用例4：句子向量维度 ----
peek_s = sent_col.peek(limit=5)
dims_s = sorted({len(v) for v in peek_s["embeddings"]})
report(
    "4",
    "句子集合向量维度(bge-m3)",
    f"全部为 {EXPECTED_DIM} 维",
    f"抽样{len(peek_s['embeddings'])}条维度集合={dims_s}",
    dims_s == [EXPECTED_DIM],
)

# ---- 用例5：来源文档覆盖 ----
data = std_col.get(include=["metadatas"])
sources = sorted({(m or {}).get("source", "?") for m in data["metadatas"]})
report(
    "5",
    "知识库来源文档覆盖",
    "7 篇文档",
    f"{len(sources)} 篇: {sources}",
    len(sources) == 7,
)

# ---- 用例6~8：bge-m3 实时语义检索 ----
print("-" * 72)
print("语义检索用例（实时调用 bge-m3 生成 query 向量，top_k=3）")
for idx, (query, expect_kw) in enumerate(RETRIEVAL_CASES, start=6):
    hits = std.search(query, top_k=3)
    top3 = [
        (h.metadata.get("source", "?"), h.metadata.get("chapter", "")) for h in hits
    ]
    top1 = top3[0][0] if top3 else "(无结果)"
    top1_snippet = (
        (hits[0].page_content[:60].replace("\n", " ") + "...") if hits else ""
    )
    ok = bool(hits) and expect_kw in top1
    actual_txt = f"top1={top1} | top3={[s for s, _ in top3]}"
    if hits:
        actual_txt += f"\n        片段: {top1_snippet}"
    report(
        str(idx),
        f"语义检索 query=「{query}」",
        f"top1 来源包含 {expect_kw}",
        actual_txt,
        ok,
    )

# ---- 用例9：E03 防幻觉负面用例（端到端，走业务容器真实链路）----
print("-" * 72)
print("端到端防幻觉负面用例（POST /api/chat，qwen2.5:7b 真实生成）")
API_BASE = os.getenv("VERIFY_API_BASE", "http://localhost:8000").rstrip("/")
e2e_question = "E03报错怎么处理？"
e2e_expected = (
    "明确告知知识库未收录 E03 且建议转人工/技术支持；"
    "不得断言 E03 含义，不得编造排查步骤"
)
# 必须命中的「拒答」信号；必须不出现的「编造」信号
REFUSE_RE = (
    r"(未收录|没有收录|未查询到|未找到|暂无[^。]{0,8}(相关|信息|记录|资料)|"
    r"知识库[^。]{0,12}(没有|无|未).{0,6}(E03|该错误码|此错误码|错误码))"
)
HUMAN_RE = r"(人工|技术支持|售后)"
FABRICATION_RE = (
    r"(通常表示|一般表示|一般是指|意味着|较为严重|严重的硬件故障|"
    r"清洁镜头|检查电源|鼓包)"
)

try:
    req_body = json.dumps(
        {"question": e2e_question, "session_id": "verify-negative-e03"}
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 - 本机容器地址，非用户输入
        f"{API_BASE}/api/chat",
        data=req_body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(  # noqa: S310 - 本机容器地址，非用户输入
        req, timeout=300
    ) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    answer = (payload.get("answer") or "").strip()
    cites = [c.get("source", "?") for c in payload.get("citations", [])]

    import re as _re

    refused = bool(_re.search(REFUSE_RE, answer))
    offered_human = bool(_re.search(HUMAN_RE, answer))
    fabricated = bool(_re.search(FABRICATION_RE, answer))
    e2e_ok = refused and offered_human and not fabricated

    actual_lines = [
        f"拒答信号={'有' if refused else '无'} | "
        f"转人工建议={'有' if offered_human else '无'} | "
        f"编造信号={'有(失败)' if fabricated else '无'}",
        f"引用来源: {cites}",
        f"完整回答: {answer}",
    ]
    report(
        "9",
        f"端到端 query=「{e2e_question}」(知识库中不存在 E03)",
        e2e_expected,
        "\n        ".join(actual_lines),
        e2e_ok,
    )
except (urllib.error.URLError, OSError) as exc:
    report(
        "9",
        f"端到端 query=「{e2e_question}」",
        e2e_expected,
        f"SKIP: 业务接口不可用 ({API_BASE}): {exc}",
        False,
    )

print("=" * 72)
TOTAL = 9
print(
    "RESULT:",
    f"ALL PASS ({TOTAL}/{TOTAL})"
    if not fails
    else f"FAILED ({TOTAL - len(fails)}/{TOTAL}): {fails}",
)
sys.exit(1 if fails else 0)
