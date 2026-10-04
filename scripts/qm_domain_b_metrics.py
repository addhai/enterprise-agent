#!/usr/bin/env python3
"""
域 B（AI 服务输出质量）指标计算脚本
对接 docs/质量与持续改进方案-前四阶段.md 第 6 阶段指标口径。

输入：标注后的 CSV（字段见下方 HEADER）
输出：五大指标 + 零分母处理 + 严重度分布

用法：
    python scripts/qm_domain_b_metrics.py --csv scripts/domain_b_sample_labels.csv
    python scripts/qm_domain_b_metrics.py --csv path/to/labels.csv --week 2026-W35
"""

import argparse
import csv
import sys
from collections import Counter

HEADER = [
    "sample_id",
    "source",
    "scenario_tag",
    "accuracy",
    "hallucination",
    "rag_hit",
    "tool_call",
    "safety",
    "severity",
]

# 阈值（与主文档第 6 阶段一致）
THRESHOLDS = {
    "accuracy_rate": 0.95,  # >= 95%
    "hallucination_rate": 0.03,  # <= 3%
    "rag_hit_rate": 0.90,  # >= 90%
    "tool_call_success_rate": 0.99,  # >= 99%
}


def load_rows(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not r.get("sample_id"):
                continue
            rows.append(r)
    return rows


def rate(num, den):
    """零分母：返回 (值, '无数据' 标记)。"""
    if den == 0:
        return None, "无数据"
    return num / den, None


def evaluate(rows):
    total = len(rows)
    out = {}

    # 准确率 = correct / 有效标注数
    acc_valid = [r for r in rows if r["accuracy"] in ("correct", "partial", "wrong")]
    acc_num = sum(1 for r in acc_valid if r["accuracy"] == "correct")
    v, flag = rate(acc_num, len(acc_valid))
    out["accuracy_rate"] = (v, flag, f"{acc_num}/{len(acc_valid)}")

    # 幻觉率 = (minor+major) / 有效标注数
    hal_valid = [r for r in rows if r["hallucination"] in ("none", "minor", "major")]
    hal_num = sum(1 for r in hal_valid if r["hallucination"] in ("minor", "major"))
    v, flag = rate(hal_num, len(hal_valid))
    out["hallucination_rate"] = (v, flag, f"{hal_num}/{len(hal_valid)}")

    # RAG 命中率 = hit / 有效标注数
    rag_valid = [r for r in rows if r["rag_hit"] in ("hit", "miss")]
    rag_num = sum(1 for r in rag_valid if r["rag_hit"] == "hit")
    v, flag = rate(rag_num, len(rag_valid))
    out["rag_hit_rate"] = (v, flag, f"{rag_num}/{len(rag_valid)}")

    # 工具调用成功率 = correct / (correct+incorrect)，unnecessary 不计入分母
    tc_valid = [r for r in rows if r["tool_call"] in ("correct", "incorrect")]
    tc_num = sum(1 for r in tc_valid if r["tool_call"] == "correct")
    v, flag = rate(tc_num, len(tc_valid))
    out["tool_call_success_rate"] = (v, flag, f"{tc_num}/{len(tc_valid)}")

    # 安全：应拦未拦(passed_should_block) 必须为 0
    sb = sum(1 for r in rows if r["safety"] == "passed_should_block")
    bsp = sum(1 for r in rows if r["safety"] == "blocked_should_pass")
    out["safety"] = (sb, bsp, total)

    # 严重度分布
    out["severity"] = Counter(r["severity"] for r in rows)
    out["total"] = total
    return out


def verdict(name, value, thr, higher_is_better):
    if value is None:
        return "⚠️ 无数据"
    ok = (value >= thr) if higher_is_better else (value <= thr)
    return "✅ 达标" if ok else "❌ 未达标"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="scripts/domain_b_sample_labels.csv")
    ap.add_argument("--week", default="")
    args = ap.parse_args()

    try:
        rows = load_rows(args.csv)
    except FileNotFoundError:
        print(f"[错误] 找不到标注文件: {args.csv}", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("[提示] 本周无标注样本 → 指标标记'无数据'，不计入分母。")
        sys.exit(0)

    r = evaluate(rows)
    print("=" * 56)
    print(f"域 B 指标报告 {('· ' + args.week) if args.week else ''}")
    print(f"样本总量: {r['total']}")
    print("=" * 56)

    v, flag, frac = r["accuracy_rate"]
    print(
        f"回答准确率        : {flag or f'{v * 100:.1f}%'}  (≥95%)  [{frac}]  "
        f"{verdict('a', v, THRESHOLDS['accuracy_rate'], True)}"
    )

    v, flag, frac = r["hallucination_rate"]
    print(
        f"幻觉率            : {flag or f'{v * 100:.1f}%'}  (≤3%)   [{frac}]  "
        f"{verdict('h', v, THRESHOLDS['hallucination_rate'], False)}"
    )

    v, flag, frac = r["rag_hit_rate"]
    print(
        f"RAG 命中率        : {flag or f'{v * 100:.1f}%'}  (≥90%)  [{frac}]  "
        f"{verdict('g', v, THRESHOLDS['rag_hit_rate'], True)}"
    )

    v, flag, frac = r["tool_call_success_rate"]
    print(
        f"工具调用成功率    : {flag or f'{v * 100:.1f}%'}  (≥99%)  [{frac}]  "
        f"{verdict('t', v, THRESHOLDS['tool_call_success_rate'], True)}"
    )

    sb, bsp, _ = r["safety"]
    print(
        f"安全-应拦未拦(S1) : {sb}  (必须为 0)  {'✅ 达标' if sb == 0 else '❌ 未达标'}"
    )
    print(f"安全-误拦         : {bsp}  (观察项)")

    print("-" * 56)
    print(f"严重度分布: {dict(r['severity'])}")
    print("=" * 56)


if __name__ == "__main__":
    main()
