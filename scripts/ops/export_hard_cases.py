#!/usr/bin/env python
"""低分评价难例导出（反馈闭环离线工具）。

把 satisfaction 中点踩（低分）评价关联会话问答，导出为 JSONL，
供金标题库评审使用。导出物不自动入金标库，必须经人工评审并走
scripts/golden/bank_lock.py 的冻结流程，符合题库四层锁纪律。

用法：
    python scripts/ops/export_hard_cases.py --tenant default \
        --out reports/hard_cases.jsonl
    python scripts/ops/export_hard_cases.py --threshold 1 \
        --limit 100 --only-candidates
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.evaluation.feedback_loop import export_jsonl, mine_hard_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Export low-score feedback hard cases")
    parser.add_argument("--tenant", default="default", help="租户 ID")
    parser.add_argument(
        "--threshold",
        type=int,
        default=2,
        help="低分阈值（评分≤该值）",
    )
    parser.add_argument("--limit", type=int, default=50, help="最多拉取的低分评价条数")
    parser.add_argument(
        "--only-candidates",
        action="store_true",
        help="只保留可进金标评审的 RAG 链路候选",
    )
    parser.add_argument("--out", required=True, help="JSONL 输出路径")
    args = parser.parse_args()

    cases = mine_hard_cases(
        tenant_id=args.tenant, score_threshold=args.threshold, limit=args.limit
    )
    if args.only_candidates:
        cases = [c for c in cases if c.golden_candidate]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(export_jsonl(cases), encoding="utf-8")

    golden = sum(1 for c in cases if c.golden_candidate)
    print(
        json.dumps(
            {
                "exported": len(cases),
                "golden_candidates": golden,
                "output": str(out_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
