"""金标题库冻结锁：内容 hash 守卫。

题库 ``tests/golden/questions.yaml`` 于 2026-10-08 冻结（meta.frozen=true）。
锁文件 ``tests/golden/questions.lock.json`` 记录题库 questions 段的整体
SHA256 与每题 SHA256，任何字段改动都会失配：

- ``tests/test_golden/test_bank_frozen.py`` 在 pytest/CI 硬校验；
- ``run_e2e_eval.py`` / ``run_retrieval_eval.py`` 运行前运行时校验。

合法改题走 MR 评审，并在 MR 内执行 ``python scripts/golden/bank_lock.py
--refresh`` 重建锁，题目 diff 与锁 diff 同 MR 可见、可审。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_YAML = REPO_ROOT / "tests" / "golden" / "questions.yaml"
DEFAULT_LOCK = REPO_ROOT / "tests" / "golden" / "questions.lock.json"


def _canonical(obj: object) -> str:
    """稳定序列化：键排序、无空白、非 ASCII 原样，保证跨平台 hash 一致。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def question_hash(question: dict) -> str:
    return hashlib.sha256(_canonical(question).encode("utf-8")).hexdigest()


def load_bank(yaml_path: Path | str = DEFAULT_YAML) -> dict:
    return yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))


def build_lock(bank: dict) -> dict:
    """从题库生成锁内容（整体 hash + 逐题 hash）。"""
    questions = bank["questions"]
    per_question = [{"id": q["id"], "sha256": question_hash(q)} for q in questions]
    return {
        "frozen": True,
        "frozen_at": (bank.get("meta") or {}).get("frozen_at"),
        "source": "tests/golden/questions.yaml",
        "question_count": len(questions),
        "bank_sha256": hashlib.sha256(
            _canonical(questions).encode("utf-8")
        ).hexdigest(),
        "questions": per_question,
    }


def refresh_lock(
    yaml_path: Path | str = DEFAULT_YAML,
    lock_path: Path | str = DEFAULT_LOCK,
) -> dict:
    """重建锁文件，返回锁内容。"""
    bank = load_bank(yaml_path)
    if not (bank.get("meta") or {}).get("frozen"):
        raise SystemExit(
            "拒绝重建锁：meta.frozen 不是 true。冻结需先在 questions.yaml "
            "置 frozen=true 并补 frozen_at 等元信息。"
        )
    lock = build_lock(bank)
    Path(lock_path).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return lock


def verify_lock(
    yaml_path: Path | str = DEFAULT_YAML,
    lock_path: Path | str = DEFAULT_LOCK,
) -> list[str]:
    """校验题库与锁是否一致，返回错误消息列表，空列表表示通过。"""
    yaml_path, lock_path = Path(yaml_path), Path(lock_path)
    errors: list[str] = []

    if not yaml_path.exists():
        return [f"题库文件不存在：{yaml_path}"]
    bank = load_bank(yaml_path)
    meta = bank.get("meta") or {}
    if meta.get("frozen") is not True:
        errors.append("meta.frozen 不是 true，题库未处于冻结状态")

    if not lock_path.exists():
        errors.append(f"锁文件不存在：{lock_path.name}；冻结题库必须随附内容锁")
        return errors

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("frozen") is not True:
        errors.append("锁文件 frozen 不是 true")

    questions = bank.get("questions") or []
    if meta.get("question_count") not in (None, len(questions)):
        errors.append(
            f"meta.question_count={meta.get('question_count')} 与实际题数 "
            f"{len(questions)} 不一致"
        )
    if lock.get("question_count") != len(questions):
        errors.append(
            f"锁 question_count={lock.get('question_count')} 与实际题数 "
            f"{len(questions)} 不一致"
        )

    ids = [q.get("id") for q in questions]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        errors.append(f"题库存在重复 id：{dupes}")

    locked = lock.get("questions") or []
    locked_ids = [item.get("id") for item in locked]
    if locked_ids != ids:
        errors.append("题目 id 序列与锁不一致（增删/调序都须走 MR 并重建锁）")

    expect_bank = lock.get("bank_sha256")
    actual_bank = hashlib.sha256(_canonical(questions).encode("utf-8")).hexdigest()
    if expect_bank != actual_bank:
        locked_map = {item["id"]: item.get("sha256") for item in locked}
        changed = [
            q["id"] for q in questions if locked_map.get(q["id"]) != question_hash(q)
        ]
        errors.append(
            "题库内容 hash 与冻结锁失配，被改题目："
            f"{changed if changed else '(未定位到单题，检查题目顺序/数量)'}"
            "；合法变更须走 MR 并执行 "
            "`python scripts/golden/bank_lock.py --refresh` 重建锁"
        )

    return errors


def ensure_frozen_or_exit(
    yaml_path: Path | str = DEFAULT_YAML,
    lock_path: Path | str | None = None,
) -> None:
    """eval 脚本运行前守卫：失配直接退出，拒绝在被篡改的题库上评测。"""
    if lock_path is None:
        lock_path = Path(yaml_path).with_name("questions.lock.json")
    errors = verify_lock(yaml_path, lock_path)
    if errors:
        print("[题库冻结锁] 校验失败，评测中止：", file=sys.stderr)
        for msg in errors:
            print(f"  - {msg}", file=sys.stderr)
        raise SystemExit(2)


def main() -> int:
    ap = argparse.ArgumentParser(description="金标题库冻结锁")
    ap.add_argument("--refresh", action="store_true", help="重建锁文件")
    ap.add_argument("--questions", default=str(DEFAULT_YAML))
    ap.add_argument("--lock", default=str(DEFAULT_LOCK))
    args = ap.parse_args()

    if args.refresh:
        lock = refresh_lock(args.questions, args.lock)
        print(f"锁已重建：{args.lock}（{lock['question_count']} 题）")
        return 0

    errors = verify_lock(args.questions, args.lock)
    if errors:
        for msg in errors:
            print(f"FAIL {msg}")
        return 1
    bank = load_bank(args.questions)
    print(f"OK 题库冻结锁校验通过（{len(bank['questions'])} 题）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
