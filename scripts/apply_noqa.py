#!/usr/bin/env python3
"""给指定文件按 ruff 诊断的真实行号批量补`# noqa`。

背景：
`# noqa` 必须标在 ruff 报告的那一行（诊断起始行），而不是「看起来相关」的
那一行。多行调用（`urllib.request.Request(` 的参数换行、`try/except` 块）
容易标错位置，反复试错很费时间。本脚本直接读 ruff 的 JSON 输出按行号回填。

用法：
    python scripts/apply_noqa.py <rule> --reason "豁免理由" file1.py [file2.py ...]
例：
    python scripts/apply_noqa.py S310 --reason "URL 为硬编码 localhost 常量" \\
        scripts/ws_rag_verify.py

关于 --ruff：
    pre-commit 的 ruff hook 用的是它自己缓存的固定版本（见 .pre-commit-config.yaml
    的 rev），可能与当前解释器里装的 ruff 版本不同，诊断结果会有差异
    （例如新版 ruff 不再报 S603，旧版仍报）。要复现 hook 的诊断，加--ruff 指定
    同一套可执行文件，例如：
        python scripts/apply_noqa.py S603 --ruff D:/Go/bin/ruff.exe \\
            --reason "命令硬编码" scripts/verify_e2e_chat.py

注意：
- 本脚本只做「按行号追加 noqa」，会先清掉该行已有的 noqa 再重写，
  避免重复叠加。
- 传入的规则代码必须与 ruff 报告的一致（例如 S310），否则不会有任何标注。
- 只处理 ruff check 当前能报出来的规则；已修好的错误自然不会被标注。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

#: 追加抑制注释时的模板，形如「两个空格 + 井号 + noqa + 冒号 + 规则 + 破折号 + 理由」
COMMENT_RE = re.compile(r"\s*#\s*noqa:.*$", re.IGNORECASE)


def collect_findings(
    files: list[str], rule: str, ruff_cmd: list[str]
) -> dict[str, dict[int, set[str]]]:
    """跑一次 ruff check --output-format=json，返回 {文件: {行号: {规则}}}。

    Args:
        files: 待检查的 Python 文件。
        rule: 只收集该规则的诊断。
        ruff_cmd: ruff 的调用前缀。默认 `[sys.executable, "-m", "ruff"]`；
            要与 pre-commit hook 的固定版本对齐时传入别的可执行文件路径。
    """
    proc = subprocess.run(  # noqa: S603,S607 —— 前缀由调用方指定且为固定工具，文件列表来自命令行
        [*ruff_cmd, "check", *files, "--output-format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    # ruff 遇到发现项时退出码为 1，属正常情况
    if proc.returncode not in (0, 1):
        print(f"[error] ruff 执行失败：\n{proc.stderr}", file=sys.stderr)
        raise SystemExit(2)

    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        print(f"[error] 无法解析 ruff JSON 输出：{exc}", file=sys.stderr)
        raise SystemExit(2)

    mapping: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for item in data:
        code = item.get("code") or ""
        rule_id = code or "UNKNOWN"
        if rule_id != rule:
            continue
        path = item.get("filename") or ""
        loc = item.get("location") or {}
        row = loc.get("row")
        if not path or not row:
            continue
        mapping[path][int(row)].add(rule_id)
    return mapping


def apply(files: list[str], rule: str, reason: str, ruff_cmd: list[str]) -> int:
    findings = collect_findings(files, rule, ruff_cmd)
    if not findings:
        print(f"[ok] 没有匹配 {rule} 的诊断，无需标注")
        return 0

    total = 0
    for path, rows in findings.items():
        target = Path(path)
        if not target.exists():
            print(f"[warn] 找不到文件，跳过：{path}")
            continue
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        for row in sorted(rows):
            if row < 1 or row > len(lines):
                print(f"[warn] {path}:{row} 行号越界，跳过")
                continue
            raw = lines[row - 1]
            eol = "\n" if raw.endswith("\n") else ""
            body = COMMENT_RE.sub("", raw.rstrip("\n"))
            lines[row - 1] = f"{body}  # noqa: {rule} —— {reason}{eol}"
            total += 1
            print(f"  {path}:{row}  {rule}")
        target.write_text("".join(lines), encoding="utf-8")
    print(f"[done] 共标注 {total} 处（规则 {rule}）")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rule", help="要标注的 ruff 规则代码，如 S310")
    parser.add_argument("files", nargs="+", help="目标 Python 文件")
    parser.add_argument(
        "--reason", default="风险不成立", help="豁免理由，写在行内注释里"
    )
    parser.add_argument(
        "--ruff",
        default=None,
        help=(
            "指定 ruff 可执行文件路径（如 pre-commit 缓存的版本）。"
            "省略则用当前解释器的 python -m ruff。"
        ),
    )
    args = parser.parse_args()
    ruff_cmd = [args.ruff] if args.ruff else [sys.executable, "-m", "ruff"]
    apply(args.files, args.rule, args.reason, ruff_cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
