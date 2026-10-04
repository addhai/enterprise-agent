"""切块质量校验：章节完整性 / 悬空标题 / 关键节独立性（零网络、零模型）。

用途：切块策略变更后，验证「一节一块、表格不被切半、无悬空标题结尾」三条性质，
并打印关键节的归属块号。配合 docker_validation_report.md 第 9 章 D 条使用。

用法：python scripts/verify_chunking.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.chunker import HybridChunker  # noqa: E402
from src.rag.loader import DocumentLoader  # noqa: E402

TRAILING_HEADING_RE = re.compile(r"(?:\r?\n)+\s*\\*#{2,6}[ \t]*[^\n]*\s*$")

loader = DocumentLoader(enable_dedup=False)
chunker = HybridChunker(chunk_size=512, chunk_overlap=64)

docs_dir = Path("data/docs")
total_dangling = 0
total_chunks = 0

for path in sorted(docs_dir.glob("*.md")):
    documents = loader.load_file(str(path))
    chunks = chunker.split_standard(documents, source_file=path.name)
    dangling = [c for c in chunks if TRAILING_HEADING_RE.search(c.page_content or "")]
    total_dangling += len(dangling)
    total_chunks += len(chunks)
    lens = [len(c.page_content) for c in chunks]
    print(
        f"{path.name:36s} chunks={len(chunks):3d} "
        f"len[min/avg/max]={min(lens)}/{sum(lens) // len(lens)}/{max(lens)} "
        f"悬空标题结尾={len(dangling)}"
    )

print("=" * 76)
print(f"合计 {total_chunks} chunk，其中悬空标题结尾 {total_dangling} 个")

# 关键节独立性：这两个小节必须各自成块，且表格不得被切成两半
print("\n[关键节检查]")
for name, needles in [
    (
        "calibration_guide.md",
        ["3.1 环境条件", "20℃ ± 3℃", "≤60% RH", "3.2 温度平衡要求", "30分钟"],
    ),
    (
        "fault_troubleshooting_manual.md",
        ["故障3:激光定位灯不亮", "激光出光孔", "故障4:屏幕闪烁"],
    ),
]:
    documents = loader.load_file(str(docs_dir / name))
    chunks = chunker.split_standard(documents, source_file=name)
    print(f"\n{name}:")
    for needle in needles:
        where = [i for i, c in enumerate(chunks, 1) if needle in (c.page_content or "")]
        print(f"  {needle!r:26s} -> chunk {where}")
    # 打印含「环境条件」与「激光定位灯不亮」的块头尾
    for i, c in enumerate(chunks, 1):
        body = (c.page_content or "").replace("\n", " ")
        if "3.1 环境条件" in body or "故障3:激光定位灯不亮" in body:
            print(f"  chunk#{i} len={len(c.page_content)}")
            print(f"    头: {body[:70]}")
            print(f"    尾: {body[-70:]}")
