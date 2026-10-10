"""BM25 启动 warmup 与中文分词器的确定性单测。

不触网、不起真实 Embedding 模型：用 object.__new__ 绕过 HybridRetriever
的 __init__（它会构造 VectorStoreManager → Embedder），vector_store 注入
内存 FakeStore；句子通道开关的用例则整体替换 VectorStoreManager。

2026-10-09 审计背景：生产单例从不走灌库路径，BM25 长期为空；
sentence_store 因无参构造 collection_name=None 长期为 None。
本文件不加 requires_llm 标记，必须在离线门禁中真实运行。
"""

from langchain_core.documents import Document
from src.config import settings
from src.rag import retriever as retriever_mod
from src.rag.chunker import SentenceWindowSplitter
from src.rag.retriever import HybridRetriever, _bm25_preprocess

# ---------------------------------------------------------------------------
# 分词器
# ---------------------------------------------------------------------------


def test_preprocess_keeps_alnum_tokens_whole():
    """错误码/参数/型号必须整块保留，这是工业语料 BM25 的主收益通道。"""
    tokens = _bm25_preprocess("F02 故障，发射率 1mW，防护 IP40，误差 ±0.2")
    assert "f02" in tokens
    assert "1mw" in tokens
    assert "ip40" in tokens
    assert "0.2" in tokens


def test_preprocess_chinese_words_not_single_chars():
    """中文应切成词（快门/卡滞），不能退化成单字噪声（快/门/卡/滞）。"""
    tokens = _bm25_preprocess("快门卡滞")
    assert "快门" in tokens
    assert "卡滞" in tokens
    # 单字切词会产生这两个裸单字作为独立 token
    assert "快" not in tokens
    assert "门" not in tokens


def test_preprocess_number_with_chinese_unit():
    """7天 / 12个月 数字侧必须整块保留；中文单位切法依赖上下文，
    两侧共同信号（数字 + 保修词）存在即可，短语级损耗由向量路兜底，
    金标回归是最终裁判。"""
    q_tokens = _bm25_preprocess("保修多久，7天内可以退吗")
    d_tokens = _bm25_preprocess("整机保修12个月，7天无理由退货")
    assert "7" in q_tokens and "7" in d_tokens
    assert "保修" in q_tokens and "保修" in d_tokens
    assert "12" in d_tokens
    assert set(q_tokens) & set(d_tokens)  # 两侧必有共同 token


def test_preprocess_pure_punctuation_has_fallback_token():
    """纯标点文本不能返回空列表，否则 BM25Retriever 建索引时空词表报错。"""
    out = _bm25_preprocess("---、。，")
    assert len(out) == 1 and out[0]


# ---------------------------------------------------------------------------
# warmup
# ---------------------------------------------------------------------------


class _FakeVectorStore:
    """仅实现 warmup 依赖的 get_all_documents。"""

    def __init__(self, docs):
        self._docs = docs

    def get_all_documents(self):
        return list(self._docs)


def _bare_retriever(fake_store, backend="chroma"):
    """绕过 __init__ 构造一个只带 warmup 所需属性的检索器。"""
    r = object.__new__(HybridRetriever)
    r.backend = backend
    r.vector_store = fake_store
    r.bm25_retriever = None
    r._all_documents = []
    return r


def _sample_docs():
    return [
        Document(
            page_content="F02 快门卡滞故障：测温精度 ±0.2，发射率 1mW，防护等级 IP40",
            metadata={"doc_id": "f02"},
        ),
        Document(
            page_content="保修政策：整机保修 12 个月，7 天无理由退货",
            metadata={"doc_id": "warranty"},
        ),
        # 干扰文档：把语料从 N=2 抬到 N=4。rank_bm25 在 N=2 且每个词
        # 仅出现于 1 篇时 idf=log(1.5/1.5)=0，所有查询都是 0 分无法排序，
        # 这是小样本数学退化，生产 652 块不受影响。
        Document(
            page_content="设备安装步骤：先固定支架，再接通讯线缆，最后通电自检",
            metadata={"doc_id": "install"},
        ),
        Document(
            page_content="API 返回 200 表示成功，401 表示鉴权失败",
            metadata={"doc_id": "api"},
        ),
    ]


def test_warmup_builds_bm25_from_persisted_docs():
    """模拟生产启动：Chroma 已有落盘数据，warmup 后 BM25 可召回。"""
    r = _bare_retriever(_FakeVectorStore(_sample_docs()))

    n = r.warmup_bm25_from_store()

    assert n == 4
    assert r.bm25_retriever is not None
    assert len(r._all_documents) == 4

    # 契约断言：自定义分词器必须真正进入 BM25 语料。langchain 参数名是
    # preprocess_func（带 c），误写成 preprocess_fn 会被 pydantic 静默
    # 忽略、退回空格切词，中文整句粘成单 token，BM25 形同虚设。
    assert "快门" in r.bm25_retriever.vectorizer.doc_freqs[0]
    assert "f02" in r.bm25_retriever.vectorizer.doc_freqs[0]

    # 中文关键词必须走 BM25 精确命中 F02 块（向量路在此测试中不存在）
    hits = r.bm25_retriever.invoke("快门卡滞")
    assert hits
    assert hits[0].metadata["doc_id"] == "f02"

    # 错误码整块匹配同样命中
    hits_code = r.bm25_retriever.invoke("F02")
    assert hits_code
    assert hits_code[0].metadata["doc_id"] == "f02"


def test_warmup_empty_collection_keeps_bm25_none():
    """空集合 warmup 返回 0 且不建索引，调用方据此打 warning。"""
    r = _bare_retriever(_FakeVectorStore([]))

    n = r.warmup_bm25_from_store()

    assert n == 0
    assert r.bm25_retriever is None


def test_warmup_skipped_on_remote_backend():
    """remote 后端的 BM25 在上游服务，本地 warmup 必须显式跳过。"""
    called = []

    class _BoomStore(_FakeVectorStore):
        def get_all_documents(self):
            called.append(1)
            return super().get_all_documents()

    r = _bare_retriever(_BoomStore(_sample_docs()), backend="remote")

    assert r.warmup_bm25_from_store() == 0
    assert called == []
    assert r.bm25_retriever is None


# ---------------------------------------------------------------------------
# sentence_store 接线开关（整体替换 VectorStoreManager，杜绝真实 Embedder）
# ---------------------------------------------------------------------------


class _RecordingVSM:
    created: list = []

    def __init__(self, persist_directory=None, collection_name=None):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        _RecordingVSM.created.append(collection_name)


def test_sentence_channel_wired_when_collection_name_given(tmp_path, monkeypatch):
    """生产接线修复后：传入标准集合名才会派生 _sentences 集合管理器。"""
    _RecordingVSM.created = []
    monkeypatch.setattr(retriever_mod, "VectorStoreManager", _RecordingVSM)
    monkeypatch.setattr(settings, "rag_sentence_enabled", True)

    r = HybridRetriever(
        persist_directory=str(tmp_path),
        collection_name="knowledge_base",
    )

    assert r.sentence_store is not None
    assert r.sentence_store.collection_name == "knowledge_base_sentences"
    assert "knowledge_base" in _RecordingVSM.created


def test_sentence_channel_none_without_collection_name(tmp_path, monkeypatch):
    """无参构造（旧生产事故形态）下句子通道必须为 None。"""
    _RecordingVSM.created = []
    monkeypatch.setattr(retriever_mod, "VectorStoreManager", _RecordingVSM)

    r = HybridRetriever(persist_directory=str(tmp_path))

    assert r.sentence_store is None


def test_sentence_channel_disabled_by_switch(tmp_path, monkeypatch):
    """rag_sentence_enabled=False 时即便传了集合名也不建句子通道。"""
    _RecordingVSM.created = []
    monkeypatch.setattr(retriever_mod, "VectorStoreManager", _RecordingVSM)
    monkeypatch.setattr(settings, "rag_sentence_enabled", False)

    r = HybridRetriever(
        persist_directory=str(tmp_path),
        collection_name="knowledge_base",
    )

    assert r.sentence_store is None
    assert "knowledge_base_sentences" not in _RecordingVSM.created


# ---------------------------------------------------------------------------
# 句子块展开（expand_context 返回 str 的历史类型事故）
# ---------------------------------------------------------------------------


def _bare_retriever_with_splitter():
    r = _bare_retriever(_FakeVectorStore([]))
    r.sentence_splitter = SentenceWindowSplitter()
    return r


def test_expand_sentence_wraps_text_back_to_document():
    """expand_context 返回纯文本，编排层必须包回 Document，
    否则下游 doc.metadata 必崩（2026-10-09 生产首跑实证）。"""
    r = _bare_retriever_with_splitter()
    doc = Document(
        page_content="F02 快门卡滞",
        metadata={
            "_expanded_content": "前文上下文\nF02 快门卡滞\n后文上下文",
            "tenant_id": "default",
            "access_level": "public",
            "source": "manual.md",
        },
    )

    out = r._expand_sentence_results([(doc, 0.42)])

    assert len(out) == 1
    expanded_doc, score = out[0]
    assert isinstance(expanded_doc, Document)
    assert expanded_doc.page_content == "前文上下文\nF02 快门卡滞\n后文上下文"
    assert score == 0.42
    # 权限元数据必须随展开文本带走，否则越权
    assert expanded_doc.metadata["tenant_id"] == "default"
    assert expanded_doc.metadata["access_level"] == "public"
    assert expanded_doc.metadata["source"] == "manual.md"
    assert expanded_doc.metadata["sentence_expanded"] is True


def test_expand_sentence_keeps_doc_when_no_expansion():
    """无 _expanded_content 时返回原 Document，不做无意义重建。"""
    r = _bare_retriever_with_splitter()
    doc = Document(page_content="普通句子", metadata={"tenant_id": "default"})

    out = r._expand_sentence_results([(doc, 0.9)])

    assert out[0][0] is doc
    assert out[0][1] == 0.9


def test_expand_then_merge_does_not_crash_and_dedupes():
    """端到端契约：展开后的句子进入 merge 不崩，且与标准块同前缀时去重。"""
    r = _bare_retriever_with_splitter()
    sentence_doc = Document(
        page_content="F02 快门卡滞",
        metadata={
            "_expanded_content": "F02 快门卡滞故障处理指南" + "补充" * 50,
            "tenant_id": "default",
        },
    )
    standard_doc = Document(
        page_content="另一份完全不同的标准块内容，讨论保修政策与退货期限",
        metadata={"tenant_id": "default"},
    )

    expanded = r._expand_sentence_results([(sentence_doc, 0.3)])
    merged = r._merge_standard_and_sentence([(standard_doc, 0.8)], expanded, 5)

    assert len(merged) == 2
    assert all(isinstance(d, Document) for d, _ in merged)
