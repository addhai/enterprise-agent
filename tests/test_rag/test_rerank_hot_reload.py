"""rerank_enabled 热更新的进程内验证

测的是什么
----------
重排序的开关判断在 `src/rag/retriever.py:384`：

    if self._rerank_enabled and final:
        final = self._rerank(query, final)

而 `self._rerank_enabled` 是一个 property（同文件 734-738 行），每次访问都
重新读 `settings.rerank_enabled`。原实现是启动时把它拷进实例属性
（`self._rerank_enabled = settings.rerank_enabled`），属于「假热更新」：
配置改了检索行为不变。本测试锁死这个修复。

关键手法：**检索器只构造一次**，中途改配置，再检索。这样才能证明门控是
读取时取值，而不是构造时快照。若每次改配置都新建检索器，测不出任何东西。

为什么要注入桩重排序器
----------------------
本项目的 rerank_provider 是 dashscope / gte-rerank，指向公网云 API，
内网部署不可达（实测报 HTTP 404 后降级）。直接用真实依赖测，只会得到
「两种情况都没变化」，无法区分「开关失效」与「依赖不可用」。
因此这里注入桩件，专注验证开关逻辑本身；真实依赖的行为由
scripts/verify_rerank_hot_reload.py --real-reranker 单独验证。
"""

import pytest


class _FakeDoc:
    """最小化文档替身，补齐检索链会用到的属性"""

    def __init__(self, idx: int):
        self.page_content = f"第 {idx} 段内容：XG-9000 腔体预热温度 187 摄氏度。"
        self.metadata = {"source": f"doc_{idx}.md", "kb_id": "KBS-TEST"}


class _StubReranker:
    """桩重排序器：记录调用次数，并反转顺序（制造可观察的顺序变化）"""

    def __init__(self):
        self.calls = []

    def rerank(self, query, documents, top_n=None):
        self.calls.append({"candidates": len(documents), "top_n": top_n})
        reversed_docs = list(reversed(documents))
        return [
            (doc, float(len(reversed_docs) - i))
            for i, (doc, _s) in enumerate(reversed_docs)
        ]


def _build_retriever_with_fixed_candidates(candidate_count: int = 5):
    """构造真实 HybridRetriever，但把数据来源换成固定候选

    只替换「数据从哪来」，保留 RRF 融合、合并、重排序门控、权限过滤等全部真实逻辑，
    因此断言的是真实的门控行，而不是复刻出来的判断。
    """
    from src.rag.retriever import HybridRetriever

    r = HybridRetriever()
    docs = [_FakeDoc(i) for i in range(candidate_count)]
    # 只打桩数据源，其余链路走真实实现
    r._vector_search = lambda q, k, f: [(d, 1.0 - i * 0.1) for i, d in enumerate(docs)]
    r._bm25_search = lambda q, k, f: []
    r.sentence_store = None
    return r


@pytest.fixture(autouse=True)
def restore_rerank_flag():
    from src.config import settings

    original = settings.rerank_enabled
    yield
    settings.rerank_enabled = original


class TestRerankGateReadsConfigLive:
    def test_gate_reads_config_at_call_time_not_construction_time(self):
        """核心：检索器构造一次，中途改配置，门控必须实时跟随

        这是「假热更新」与「真热更新」的分界线：
        构造时的配置值是 False，若门控是构造时快照，后续改成 True 也不会重排序。
        """
        from src.config import settings

        settings.rerank_enabled = False
        r = _build_retriever_with_fixed_candidates()
        stub = _StubReranker()
        r._reranker = stub

        calls = []
        original_rerank = r._rerank

        def spy(query, candidates):
            result = original_rerank(query, candidates)
            calls.append({"candidates_in": len(candidates)})
            return result

        r._rerank = spy

        # ---- 构造时配置为 False，此处应为 0 次 ----
        r.search("XG-9000", top_k=5)
        assert len(calls) == 0, "开关为 false 时不应调用重排序"
        assert len(stub.calls) == 0, "开关为 false 时桩件也不应被调用"

        # ---- 构造之后改配置为 True，同一实例应立刻开始重排序 ----
        settings.rerank_enabled = True
        r.search("XG-9000", top_k=5)
        assert len(calls) == 1, (
            "构造之后把开关改成 true，同一实例应立即重排序；"
            "若仍为 0 次说明开关是构造时快照（假热更新）"
        )
        assert len(stub.calls) == 1, "桩重排序器应被调用一次"

        # ---- 再关掉，应立即停止 ----
        settings.rerank_enabled = False
        r.search("XG-9000", top_k=5)
        assert len(calls) == 1, "开关关掉后不应再增加重排序调用"

    def test_sequence_on_off_on(self):
        """连续 开→关→开，重排序调用次数应为 1、1、2（逐次累加）"""
        from src.config import settings

        settings.rerank_enabled = False
        r = _build_retriever_with_fixed_candidates()
        stub = _StubReranker()
        r._reranker = stub

        counts = []
        for state in [True, False, True]:
            settings.rerank_enabled = state
            stub.calls.clear()
            r.search("XG-9000", top_k=5)
            counts.append(len(stub.calls))

        assert counts == [1, 0, 1], (
            f"开/关/开 的重排序调用次数应为 [1,0,1]，实际 {counts}"
        )

    def test_result_order_changes_when_enabled(self):
        """开关打开时结果顺序应被重排序改变，关闭时保持原顺序"""
        from src.config import settings

        settings.rerank_enabled = False
        r = _build_retriever_with_fixed_candidates()
        r._reranker = _StubReranker()

        settings.rerank_enabled = False
        off_sources = [d.metadata["source"] for d in r.search("XG-9000", top_k=5)]

        settings.rerank_enabled = True
        on_docs = r.search("XG-9000", top_k=5)
        on_sources = [d.metadata["source"] for d in on_docs]

        assert on_sources == list(reversed(off_sources)), (
            f"桩件会反转顺序，预期 {list(reversed(off_sources))}，实际 {on_sources}"
        )
        assert on_sources != off_sources, "开关打开后顺序应当变化"

    def test_reranked_metadata_only_when_enabled(self):
        """结果上的 reranked 标记只在开关打开时出现（由 _rerank 成功时写入）"""
        from src.config import settings

        settings.rerank_enabled = False
        r = _build_retriever_with_fixed_candidates()
        r._reranker = _StubReranker()

        settings.rerank_enabled = False
        off_docs = r.search("XG-9000", top_k=5)
        assert all("reranked" not in d.metadata for d in off_docs), (
            "开关关闭时不应有 reranked 标记"
        )

        settings.rerank_enabled = True
        on_docs = r.search("XG-9000", top_k=5)
        assert on_docs and all(d.metadata.get("reranked") is True for d in on_docs), (
            "开关打开时每条结果都应带 reranked=True"
        )

    def test_rerank_top_n_follows_config(self):
        """rerank_top_n 同样应实时读取（同属启动时快照问题）"""
        from src.config import settings

        settings.rerank_enabled = True
        settings.rerank_top_n = 7
        r = _build_retriever_with_fixed_candidates()
        stub = _StubReranker()
        r._reranker = stub

        r.search("XG-9000", top_k=5)
        assert stub.calls[0]["top_n"] == 7, (
            f"rerank_top_n 应实时读配置，实际传下去的是 {stub.calls[0]['top_n']}"
        )

        settings.rerank_top_n = 2
        r.search("XG-9000", top_k=5)
        assert stub.calls[1]["top_n"] == 2, "改完 rerank_top_n 后应立即生效"


class TestRerankFailureLatch:
    """初始化失败闩锁的行为（有意为之，需明确其与热更新的相互作用）"""

    def test_init_failure_latches_off_even_if_config_is_true(self):
        """重排序器初始化失败后，即使配置为 true 也不再重排序

        这是刻意的保护：避免每次检索都白跑一次注定失败的初始化。
        但它意味着**一旦失败过，热更新改成 true 也不会恢复**，需重启进程。
        本测试把这个行为固定下来，避免日后被误当成 bug 改坏。
        """
        from src.config import settings

        settings.rerank_enabled = True
        r = _build_retriever_with_fixed_candidates()
        r._rerank_init_failed = True  # 模拟初始化失败后置位

        assert r._rerank_enabled is False, "闩锁置位后，开关应被视为关闭"

        calls = []
        original_rerank = r._rerank

        def spy(query, candidates):
            calls.append(1)
            return original_rerank(query, candidates)

        r._rerank = spy
        r.search("XG-9000", top_k=5)
        assert len(calls) == 0, "闩锁置位后不应再调用重排序"
