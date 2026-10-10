#!/usr/bin/env python3
"""检索存储完整性定期巡检（BM25 索引 + 双 Chroma 集合）。

背景（2026-10-09 审计实证的两个静默事故）：
  1. BM25Retriever 纯内存无持久化，生产单例从不走灌库路径，
     上线以来 BM25 通道恒为空，混合检索只有向量一路。
  2. 依赖注入无参构造 collection_name=None，sentence_store 恒 None，
     knowledge_base_sentences（2834 条）建库后从未被查询。
本脚本把这两条通道的「活着」状态变成可定期断言的事实，
建议接入 cron / 运维巡检，每次发版后必跑一次。

在生产容器内运行：
    docker exec -w /app -e PYTHONPATH=/app prod-app-1 \
        python scripts/ops/check_rag_integrity.py \
        --expect-standard 652 --expect-sentences 2834

仅计数与 BM25 warmup 时不请求 Ollama；加 --probe 才做一次真实检索。

退出码：
    0 全部健康（或仅有 warning）
    1 存在致命缺陷：集合缺失/为空、BM25 未建成、计数与基线不符
    2 用法或环境错误
"""

from __future__ import annotations

import argparse
import json
import logging

# 容器内以脚本方式运行时把项目根目录加进 sys.path
# （docker exec 已带 -e PYTHONPATH=/app，此处兜底保险）
import os
import sys
import time

if os.path.isdir("/app") and "/app" not in sys.path:
    sys.path.insert(0, "/app")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("rag-integrity")


def _ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def check(
    expect_standard: int | None, expect_sentences: int | None
) -> tuple[bool, dict]:
    # 延迟导入，保证 --help 在缺依赖环境也能用
    from src.config import settings
    from src.rag.retriever import HybridRetriever

    fatal = False
    report: dict = {}

    standard_name = settings.chroma_collection_name
    sentence_name = f"{standard_name}_sentences"
    report["collections"] = {"standard": standard_name, "sentence": sentence_name}
    report["switches"] = {
        "rag_sentence_enabled": settings.rag_sentence_enabled,
        "rag_bm25_warmup_enabled": settings.rag_bm25_warmup_enabled,
    }

    # 构造生产同款检索器（显式传集合名，复刻 dependencies._init_retriever）
    retriever = HybridRetriever(collection_name=standard_name)

    # ---- 1. 标准集合计数 ----
    n_standard = retriever.vector_store.count()
    report["collections"]["standard_count"] = n_standard
    if n_standard <= 0:
        _fail(f"标准集合 {standard_name} 为空，检索无数据可用")
        fatal = True
    else:
        _ok(f"标准集合 {standard_name} 共 {n_standard} 块")
    if expect_standard is not None and n_standard != expect_standard:
        _fail(f"标准块数 {n_standard} 与基线 {expect_standard} 不符，疑似重建/丢数据")
        fatal = True

    # ---- 2. 句子集合计数 ----
    n_sentences = 0
    if settings.rag_sentence_enabled:
        if retriever.sentence_store is None:
            _fail("开关已开但 sentence_store 仍为 None，句子通道接线断裂")
            fatal = True
        else:
            n_sentences = retriever.sentence_store.count()
            report["collections"]["sentence_count"] = n_sentences
            if n_sentences <= 0:
                _fail(f"句子集合 {sentence_name} 为空，FAQ/错误码精确匹配退化")
                fatal = True
            else:
                _ok(f"句子集合 {sentence_name} 共 {n_sentences} 条")
            if expect_sentences is not None and n_sentences != expect_sentences:
                _fail(f"句子条数 {n_sentences} 与基线 {expect_sentences} 不符")
                fatal = True
            # 比例健康只告警不判死：句子切分粒度随 chunker 版本会变化
            if n_standard and n_sentences:
                ratio = n_sentences / n_standard
                if ratio < 1.5:
                    _warn(f"句子/标准块比例仅 {ratio:.2f}，细切索引可能不完整")
    else:
        _warn("RAG_SENTENCE_ENABLED 关闭，本次不检查句子通道")

    # ---- 3. BM25 warmup ----
    if settings.rag_bm25_warmup_enabled:
        t0 = time.time()
        try:
            n_bm25 = retriever.warmup_bm25_from_store()
        except Exception as exc:  # noqa: BLE001 巡检要兜住所有异常转成报告
            _fail(f"BM25 warmup 抛异常: {exc}")
            return True, report
        elapsed = time.time() - t0
        report["bm25"] = {"docs": n_bm25, "warmup_seconds": round(elapsed, 2)}
        if retriever.bm25_retriever is None or n_bm25 <= 0:
            _fail("BM25 未建成，生产混合检索将退化为向量单路")
            fatal = True
        elif n_standard and n_bm25 != n_standard:
            _fail(f"BM25 语料 {n_bm25} 块与标准集合 {n_standard} 块不一致")
            fatal = True
        else:
            _ok(f"BM25 内存索引 {n_bm25} 块，warmup 耗时 {elapsed:.2f}s")
        # 分词器生效契约：抽样首文档的词频表必须含中文词，而非整句单 token
        if retriever.bm25_retriever is not None:
            first_freqs = retriever.bm25_retriever.vectorizer.doc_freqs[0]
            has_cjk_word = any(
                any("\u4e00" <= ch <= "\u9fff" for ch in term) for term in first_freqs
            )
            if not has_cjk_word:
                _fail(
                    "BM25 词表无中文词，jieba 分词器未生效"
                    "（检查 preprocess_func 参数名是否拼错）"
                )
                fatal = True
    else:
        _warn("RAG_BM25_WARMUP_ENABLED 关闭，本次不检查 BM25")

    report["healthy"] = not fatal
    return fatal, report


def check_ollama() -> bool:
    """检查容器内 Ollama 推理 API 与模型驻留状态（2026-10-09 双驻留档位）。

    只在 API 不可达时判死；空闲期模型被 keep_alive 正常卸载不判死。
    MAX_LOADED_MODELS=2 是允许同驻的上限，常驻模型数随负载变化属正常。
    """
    import json
    import urllib.request

    base = "http://127.0.0.1:11434"
    fatal = False
    try:
        # base 硬编码本机 Ollama，无外部输入拼接；nosec B310 为 bandit 白名单
        with urllib.request.urlopen(f"{base}/api/tags", timeout=10) as resp:  # noqa: S310  # nosec B310
            tags = json.loads(resp.read().decode("utf-8"))
        installed = [m.get("name", "?") for m in tags.get("models", [])]
        _ok(f"Ollama API 可达，已安装模型 {len(installed)} 个：{','.join(installed)}")
    except Exception as exc:  # noqa: BLE001
        _fail(f"Ollama API 不可达，推理服务异常: {exc}")
        return True

    try:
        # 同上，仅访问本机固定地址  # nosec B310
        with urllib.request.urlopen(f"{base}/api/ps", timeout=10) as resp:  # noqa: S310
            ps = json.loads(resp.read().decode("utf-8"))
        loaded = ps.get("models", [])
        if loaded:
            for m in loaded:
                size_gb = (m.get("size_vram", 0) or m.get("size", 0)) / 1e9
                _ok(f"驻留模型：{m.get('name')} 约 {size_gb:.1f}GB")
        else:
            _warn("当前无模型驻留（空闲卸载属正常，首次请求会冷加载）")
    except Exception as exc:  # noqa: BLE001
        _warn(f"Ollama /api/ps 查询失败（不判死）: {exc}")

    max_loaded = os.environ.get("OLLAMA_MAX_LOADED_MODELS", "未设置")
    mem_limit = os.environ.get("OLLAMA_NUM_PARALLEL", "未设置")
    print(
        f"[INFO] OLLAMA_MAX_LOADED_MODELS={max_loaded} OLLAMA_NUM_PARALLEL={mem_limit}"
    )
    return fatal


def probe(retriever_query: str, top_k: int) -> bool:
    """真实检索抽样，需 Ollama embedding 在线。"""
    from src.config import settings
    from src.rag.retriever import HybridRetriever

    retriever = HybridRetriever(collection_name=settings.chroma_collection_name)
    retriever.warmup_bm25_from_store()
    try:
        results = retriever.search(retriever_query, top_k=top_k, tenant_id="default")
    except Exception as exc:  # noqa: BLE001
        _fail(f"抽样检索异常: {exc}")
        return True
    if not results:
        _fail(f"抽样检索「{retriever_query}」0 结果，检索链路不可用")
        return True
    _ok(f"抽样检索「{retriever_query}」返回 {len(results)} 条，top1 前 80 字：")
    print("       " + results[0].page_content[:80].replace("\n", " "))
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 检索存储完整性巡检")
    parser.add_argument(
        "--expect-standard", type=int, default=None, help="标准块基线计数，不符则判死"
    )
    parser.add_argument(
        "--expect-sentences", type=int, default=None, help="句子条基线计数，不符则判死"
    )
    parser.add_argument(
        "--probe",
        type=str,
        default=None,
        help="可选真实检索查询词（会请求 Ollama embedding）",
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument(
        "--no-ollama",
        action="store_true",
        help="跳过 Ollama 驻留检查（默认检查，仅本地 HTTP，不产生推理）",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args()

    try:
        fatal, report = check(args.expect_standard, args.expect_sentences)
        if not args.no_ollama:
            fatal = check_ollama() or fatal
        if args.probe:
            fatal = probe(args.probe, args.top_k) or fatal
    except ImportError as exc:
        _fail(f"依赖缺失: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001
        _fail(f"巡检自身异常: {exc}")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    print("RESULT: " + ("HEALTHY" if not fatal else "UNHEALTHY"))
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
