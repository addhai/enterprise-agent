"""金标题库冻结守卫。

2026-10-08 起 50 题金标题库冻结（meta.frozen=true）。任何未经 MR 的题目
增删改都会让 tests/golden/questions.lock.json 的内容 hash 失配，本文件
在 pytest/CI 立即红灯；评测脚本侧另由 scripts/golden/bank_lock.py 做
运行时守卫。合法改题路径：MR 评审 + 同 MR 执行
``python scripts/golden/bank_lock.py --refresh`` 重建锁。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.golden import bank_lock  # noqa: E402

YAML_PATH = PROJECT_ROOT / "tests" / "golden" / "questions.yaml"
LOCK_PATH = PROJECT_ROOT / "tests" / "golden" / "questions.lock.json"


@pytest.fixture(scope="module")
def bank() -> dict:
    return bank_lock.load_bank(YAML_PATH)


def test_meta_declares_frozen(bank: dict) -> None:
    meta = bank["meta"]
    assert meta["frozen"] is True
    assert meta.get("frozen_at"), "frozen_at 必须登记冻结日期"
    assert meta.get("question_count") == 50


def test_lock_file_present_and_matches(bank: dict) -> None:
    assert LOCK_PATH.exists(), "冻结题库必须随附 questions.lock.json"
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["frozen"] is True
    assert lock["question_count"] == 50
    assert bank_lock.verify_lock(YAML_PATH, LOCK_PATH) == []


def test_question_count_ids_and_type_distribution(bank: dict) -> None:
    questions = bank["questions"]
    assert len(questions) == 50
    ids = [q["id"] for q in questions]
    assert len(set(ids)) == 50, "题库 id 必须唯一"
    # 题目排列顺序由锁的 id 序列与 bank hash 共同锁定，这里不重复要求字典序

    counts: dict[str, int] = {}
    for q in questions:
        counts[q["type"]] = counts.get(q["type"], 0) + 1
    assert counts == {
        "fact": 20,
        "synthesis": 15,
        "procedure": 10,
        "refusal": 5,
    }


def test_each_question_has_evidence_gold(bank: dict) -> None:
    """冻结基线质量门：每题必须带可回指语料的 gold，禁止无证据题入库。"""
    for q in bank["questions"]:
        if q["type"] == "refusal":
            # 拒答题判据是 refusal.topic_any/hedge_any 双信号
            refusal = q.get("refusal") or {}
            # hedge_any 必需；topic_any 库外收口题（GR05）允许为空
            assert "hedge_any" in refusal, f"{q['id']} 缺少 refusal.hedge_any"
            assert refusal["hedge_any"], f"{q['id']} refusal.hedge_any 为空"
            continue
        assert q.get("gold", {}).get("docs"), f"{q['id']} 缺少 gold.docs"
        groups = q.get("answer", {}).get("keyword_groups")
        assert groups, f"{q['id']} 缺少 answer.keyword_groups 判据"


def test_tampered_question_is_detected(tmp_path: Path) -> None:
    """锁必须真的抓得住改动：改一个字、加一题、删一题都要报错。"""
    bank = bank_lock.load_bank(YAML_PATH)
    yaml_path = tmp_path / "questions.yaml"
    lock_path = tmp_path / "questions.lock.json"

    def write_pair(mutated: dict) -> list[str]:
        yaml_path.write_text(
            yaml.safe_dump(mutated, allow_unicode=True), encoding="utf-8"
        )
        lock = bank_lock.build_lock(bank)  # 锁对应「未篡改」版本
        lock_path.write_text(json.dumps(lock, ensure_ascii=False), encoding="utf-8")
        return bank_lock.verify_lock(yaml_path, lock_path)

    # 改一个字：GF01 的问题文本被悄悄修改
    changed = copy.deepcopy(bank)
    changed["questions"][0]["question"] += "（被篡改）"
    errors = write_pair(changed)
    assert errors, "篡改题目文本后锁校验必须失败"
    assert "GF01" in errors[-1]

    # 删一题：数量与 id 序列失配
    deleted = copy.deepcopy(bank)
    deleted["questions"].pop()
    assert write_pair(deleted)

    # meta 解冻声明也必须被拦
    unfrozen = copy.deepcopy(bank)
    unfrozen["meta"]["frozen"] = False
    assert any("frozen" in e for e in write_pair(unfrozen))


def test_runtime_guard_aborts_on_tamper(tmp_path: Path) -> None:
    """评测入口守卫：锁失配时 SystemExit 拒绝评测，不产出污染报告。"""
    bank = bank_lock.load_bank(YAML_PATH)
    yaml_path = tmp_path / "questions.yaml"
    lock_path = tmp_path / "questions.lock.json"
    yaml_path.write_text(yaml.safe_dump(bank, allow_unicode=True), encoding="utf-8")
    lock_path.write_text(
        json.dumps(bank_lock.build_lock(bank), ensure_ascii=False),
        encoding="utf-8",
    )
    bank_lock.ensure_frozen_or_exit(yaml_path, lock_path)  # 未篡改不抛

    tampered = copy.deepcopy(bank)
    tampered["questions"][3]["question"] += "x"
    yaml_path.write_text(yaml.safe_dump(tampered, allow_unicode=True), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        bank_lock.ensure_frozen_or_exit(yaml_path, lock_path)
    assert exc.value.code == 2
