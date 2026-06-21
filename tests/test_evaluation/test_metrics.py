from src.evaluation.metrics import evaluate_retrieval, mean_reciprocal_rank


def test_perfect_retrieval():
    """完美检索应得满分"""
    result = evaluate_retrieval(
        retrieved_ids=["doc1", "doc2", "doc3"],
        expected_ids=["doc1", "doc2", "doc3"]
    )
    assert result["recall"] == 1.0
    assert result["precision"] == 1.0
    assert result["mrr"] == 1.0


def test_partial_retrieval():
    """部分检索应得部分分"""
    result = evaluate_retrieval(
        retrieved_ids=["doc1", "doc4", "doc5"],
        expected_ids=["doc1", "doc2", "doc3"]
    )
    assert round(result["recall"], 4) == round(1 / 3, 4)  # 只召回了 1/3 的相关文档
    assert round(result["precision"], 4) == round(1 / 3, 4)  # 3 条结果中 1 条相关
    assert result["mrr"] == 1.0  # 第一个结果就跟相关


def test_mrr_with_second_rank():
    """第一个相关结果在第二位"""
    result = evaluate_retrieval(
        retrieved_ids=["doc4", "doc2", "doc5"],
        expected_ids=["doc1", "doc2", "doc3"]
    )
    assert result["mrr"] == 0.5  # 1/2 = 0.5


def test_empty_expected():
    """无期望结果时"""
    result = evaluate_retrieval(
        retrieved_ids=["doc1"],
        expected_ids=[]
    )
    assert result["recall"] == 1.0  # 没有要召回的，默认满分
