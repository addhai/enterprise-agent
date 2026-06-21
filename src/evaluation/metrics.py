"""RAG 检索层评估指标"""
from typing import List


def evaluate_retrieval(
    retrieved_ids: List[str],
    expected_ids: List[str]
) -> dict:
    """评估检索结果

    Args:
        retrieved_ids: 检索到的文档 ID 列表（有序）
        expected_ids: 期望的相关文档 ID 列表

    Returns:
        dict: {recall, precision, mrr, f1}
    """
    retrieved_set = set(retrieved_ids)
    expected_set = set(expected_ids)

    if not expected_set:
        return {"recall": 1.0, "precision": 1.0, "mrr": 1.0, "f1": 1.0}

    # 召回的相关文档数
    relevant_retrieved = retrieved_set & expected_set

    # Recall = 召回了多少相关文档 / 总共多少相关文档
    recall = len(relevant_retrieved) / len(expected_set) if expected_set else 0.0

    # Precision = 召回的文档中有多少是相关的
    precision = len(relevant_retrieved) / len(retrieved_set) if retrieved_set else 0.0

    # MRR = 第一个相关文档排名的倒数的均值
    mrr = mean_reciprocal_rank([retrieved_ids], expected_set)

    # F1 = 2 * (precision * recall) / (precision + recall)
    if precision + recall > 0:
        f1 = 2 * (precision * recall) / (precision + recall)
    else:
        f1 = 0.0

    return {
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "mrr": round(mrr, 4),
        "f1": round(f1, 4),
    }


def mean_reciprocal_rank(
    result_lists: List[List[str]],
    expected_set: set
) -> float:
    """计算 MRR（Mean Reciprocal Rank）"""
    if not result_lists:
        return 0.0

    reciprocal_ranks = []
    for result_list in result_lists:
        for rank, doc_id in enumerate(result_list, 1):
            if doc_id in expected_set:
                reciprocal_ranks.append(1.0 / rank)
                break
        else:
            reciprocal_ranks.append(0.0)

    return sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
