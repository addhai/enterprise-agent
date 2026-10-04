# ruff: noqa: S607
# S607 豁免理由：本脚本通过 subprocess 调用 docker CLI 读取容器状态
# （如 `docker ps`、`docker inspect`、`docker exec`）。命令名与容器名
# 全部在本文件内硬编码，不来自任何外部输入，且以列表形式传参、
# 不经过 shell，故「部分可执行路径」的风险不成立。
"""端到端中文回归 + 并发显存压测脚本。

A. 中文漂移回归：5 类不同查询（测温范围/故障排查/保修/校准/操作步骤），
   逐用例校验：简体中文占比、无连续英文单词成句、首句为结论且不以问号结尾、
   无反问话术。完整打印每次问答。
B. 并发压测：3 路并发请求（OLLAMA_NUM_PARALLEL=1 时服务端串行处理），
   后台每秒采样 nvidia-smi 显存，输出基线/峰值，断言峰值 <= 7500 MiB。

用法：
  python scripts/verify_e2e_chat.py
环境变量：
  VERIFY_API_BASE   默认 http://localhost:8000
  GPU_LIMIT_MIB     默认 7500
"""

import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

API_BASE = os.getenv("VERIFY_API_BASE", "http://localhost:8000").rstrip("/")
GPU_LIMIT_MIB = int(os.getenv("GPU_LIMIT_MIB", "7500"))
TIMEOUT = 300

# (类型, 问题, 回答中期望出现的关键事实之一)
REGRESSION_CASES = [
    ("测温范围", "T100测温范围是多少？", ["-20", "550"]),
    ("故障排查", "激光定位灯不亮怎么处理？", ["激光"]),
    ("保修", "保修期是多久？", ["12个月", "12 个月", "一年", "12 月"]),
    ("校准", "校准对环境有什么要求？", ["20", "60", "30分钟", "30 分钟"]),
    ("操作步骤", "怎么切换温度单位？", ["℃", "℉", "单位", "菜单"]),
]
CONCURRENT_CASES = [
    "T100测温范围是多少？",
    "保修期是多久？",
    "激光定位灯不亮怎么处理？",
]

# 连续两个及以上英文单词（单字母/型号如 T100、RMA、USB 不拦截）
ENGLISH_SENTENCE_RE = re.compile(r"[A-Za-z]{2,}(?:[\s/]+[A-Za-z]{2,})+")
# 反问用户的话术（上一轮漂移事故的典型签名）
RHETORICAL_RE = re.compile(
    r"想了解哪|您想了解|您是想|请问您(具体)?想|您希望了解|您需要了解哪|"
    r"Would you like|Do you want|please tell me|let me know which|"
    r"您具体想|想了解什么方面|哪方面的内容|"
    # 以下为本轮回归事故签名：索要型号、追问如何继续、泛化要求补充信息
    r"您希望如何|如何继续|请提供更详细|提供更详细的信息|"
    r"提供.{0,10}型号|告诉我.{0,10}型号|请告知.{0,10}型号"
)
# 首句不得以问候语开场（必须结论先行）
GREETING_RE = re.compile(r"^\s*(您好|你好|在吗|您好啊|嗨|请问)")
CHINESE_RE = re.compile(r"[一-鿿]")
LATIN_RE = re.compile(r"[A-Za-z]")

fails = []


def chat(question: str, session_id: str) -> dict:
    body = json.dumps({"question": question, "session_id": session_id}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 —— URL 来自硬编码 localhost 常量，不接受外部输入
        f"{API_BASE}/api/chat",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 —— URL 来自硬编码 localhost 常量，不接受外部输入
        payload = json.loads(resp.read().decode("utf-8"))
    payload["_elapsed"] = round(time.time() - t0, 1)
    return payload


def evaluate_answer(answer: str, expect_facts: list) -> dict:
    """返回各项语言/结构指标。"""
    n_zh = len(CHINESE_RE.findall(answer))
    n_latin = len(LATIN_RE.findall(answer))
    zh_ratio = n_zh / max(1, n_zh + n_latin)
    eng_phrases = sorted({m.group(0) for m in ENGLISH_SENTENCE_RE.finditer(answer)})
    rhetorical = RHETORICAL_RE.findall(answer)
    # 首句：按句末标点/换行切，取第一个非空片段
    sentences = [s.strip() for s in re.split(r"[。！？\n]", answer) if s.strip()]
    first = sentences[0] if sentences else ""
    first_is_question = first.endswith("？") or first.endswith("?")
    fact_hits = [f for f in expect_facts if f in answer]
    return {
        "zh_ratio": round(zh_ratio, 3),
        "eng_phrases": eng_phrases,
        "rhetorical": rhetorical,
        "first_sentence": first,
        "first_is_question": first_is_question,
        "greeting_start": bool(GREETING_RE.search(first)),
        "fact_hits": fact_hits,
        "length": len(answer),
    }


def gpu_used_mib() -> int:
    out = subprocess.run(  # noqa: S603 —— 容器名与子命令均硬编码，列表传参不经 shell
        [
            "docker",
            "exec",
            "ollama",
            "nvidia-smi",
            "--query-gpu=memory.used",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return int(out.stdout.strip().splitlines()[-1].strip())


def section(title: str) -> None:
    print("=" * 72)
    print(title)
    print("=" * 72)


# ---------------- A. 中文漂移回归 ----------------
section("A. 中文漂移回归（5 类查询，端到端 /api/chat）")
for idx, (ctype, question, expect_facts) in enumerate(REGRESSION_CASES, start=1):
    print(f"\n----- 回归用例{idx} [{ctype}] -----")
    print(f"输入: {question}")
    print(
        f"预期: 全程简体中文；首句直接给结论；不以问号结尾；"
        f"无反问；含关键事实 {expect_facts}"
    )
    try:
        r = chat(question, f"regress-{idx}")
        answer = (r.get("answer") or "").strip()
        m = evaluate_answer(answer, expect_facts)
        cites = [c.get("source", "?") for c in r.get("citations", [])]
        checks = {
            "中文占比>=0.60": m["zh_ratio"] >= 0.60,
            "无连续英文成句": not m["eng_phrases"],
            "无反问/索要型号话术": not m["rhetorical"],
            "首句非疑问句": not m["first_is_question"],
            "首句非问候开场": not m["greeting_start"],
            "首句长度>=8字": len(m["first_sentence"]) >= 8,
            "命中关键事实": bool(m["fact_hits"]),
        }
        print(f"耗时: {r['_elapsed']}s | intent={r.get('intent')} | 引用={cites}")
        print(
            f"指标: 中文占比={m['zh_ratio']} 英文短语={m['eng_phrases']} "
            f"反问={m['rhetorical']} 问候开场={m['greeting_start']} "
            f"事实命中={m['fact_hits']} 长度={m['length']}"
        )
        print(f"首句: {m['first_sentence']}")
        print(f"完整回答:\n{answer}")
        for name, ok in checks.items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not all(checks.values()):
            fails.append(
                f"回归用例{idx}[{ctype}]: "
                + ",".join(n for n, ok in checks.items() if not ok)
            )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"  [FAIL] 请求异常: {exc}")
        fails.append(f"回归用例{idx}[{ctype}]: 请求异常 {exc}")

# ---------------- B. 并发压测 + 显存峰值 ----------------
section(f"B. 并发压测（3 路并发）与显存峰值（限值 {GPU_LIMIT_MIB} MiB）")
try:
    baseline = gpu_used_mib()
except Exception as exc:
    baseline = -1
    print(f"[WARN] 基线采样失败: {exc}")
print(f"压测前显存基线: {baseline} MiB")

samples = []
stop = threading.Event()


def sampler() -> None:
    while not stop.is_set():
        with contextlib.suppress(Exception):
            # 采样失败（容器瞬时不可用）不该终止采样线程
            samples.append((round(time.time(), 1), gpu_used_mib()))
        time.sleep(1.0)


t = threading.Thread(target=sampler, daemon=True)
t.start()
results = {}
t0 = time.time()
try:
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {
            pool.submit(chat, q, f"conc-{i}"): (i, q)
            for i, q in enumerate(CONCURRENT_CASES, start=1)
        }
        for fut in as_completed(futs):
            i, q = futs[fut]
            try:
                r = fut.result()
                results[i] = (
                    q,
                    r["_elapsed"],
                    len(r.get("answer") or ""),
                    (r.get("answer") or "")[:80].replace("\n", " "),
                )
            except Exception as exc:
                results[i] = (q, -1, 0, f"ERROR: {exc}")
finally:
    stop.set()
    t.join(timeout=5)
wall = round(time.time() - t0, 1)

for i in sorted(results):
    q, elapsed, alen, head = results[i]
    print(f"并发{i}: 「{q}」 耗时={elapsed}s 答案长度={alen} 开头={head}")
    if elapsed < 0:
        fails.append(f"并发{i}请求失败")

peak = max((v for _, v in samples), default=-1)
print(f"采样点数={len(samples)} 总墙钟={wall}s")
print(f"显存峰值: {peak} MiB（限值 {GPU_LIMIT_MIB} MiB）")
# 压测后确认容器未被 OOM 杀死
inspect = subprocess.run(  # noqa: S603 —— 容器名与子命令均硬编码，列表传参不经 shell
    [
        "docker",
        "inspect",
        "ollama",
        "--format",
        "{{.State.OOMKilled}} {{.State.Status}}",
    ],
    capture_output=True,
    text=True,
    timeout=20,
)
oom, status = inspect.stdout.strip().split()
print(f"ollama 容器: OOMKilled={oom} status={status}")
gpu_ok = 0 <= peak <= GPU_LIMIT_MIB
print(f"  [{'PASS' if gpu_ok else 'FAIL'}] 显存峰值 <= {GPU_LIMIT_MIB} MiB")
if not gpu_ok:
    fails.append(f"显存峰值 {peak} 超过限值 {GPU_LIMIT_MIB}")
if oom.lower() == "true" or status != "running":
    fails.append("ollama 容器 OOM 或非 running 状态")

print("=" * 72)
print(
    "RESULT:",
    "ALL PASS（5 回归用例 + 并发显存压测全部通过）"
    if not fails
    else f"FAILED: {fails}",
)
sys.exit(1 if fails else 0)
