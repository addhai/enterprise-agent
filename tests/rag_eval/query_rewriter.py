# ruff: noqa: E501
"""P3-2 实验 1：查询改写模块（规则 + 同义词表，不依赖 LLM）

对 fault 类查询做同义扩展，提升 BM25 关键词匹配率。
例如：
    "激光定位灯不亮" → "激光灯 不亮 无法定位 指示灯 故障"
    "无法开机" → "无法开机 不能开机 电源键 无显示 不亮"

用法：
    from tests.rag_eval.query_rewriter import QueryRewriter
    rewriter = QueryRewriter()
    expanded = rewriter.rewrite("激光定位灯不亮")
    # "激光灯 不亮 无法定位 指示灯 故障 激光定位灯不亮"

E501 说明：下方 SYNONYM_RULES 是同义词数据表，每条「触发正则 + 扩展词列表」
本身就是一行完整语义，折行反而割裂可读性，也不影响任何行为，故豁免行宽检查。
"""

import re

# 同义词/扩展规则表
# 每条规则：(触发模式, 扩展词列表)
SYNONYM_RULES: list[tuple] = [
    # 故障排查类
    (
        r"激光.*不亮|不亮.*激光",
        ["激光灯", "不亮", "无法定位", "指示灯", "故障", "激光模组"],
    ),
    (
        r"无法开机|不能开机|开不了机",
        ["无法开机", "不能开机", "电源键", "无显示", "不亮", "电源"],
    ),
    (
        r"测温.*偏差|偏差.*大|读数.*不准|不准确",
        ["测温偏差", "读数", "不准确", "偏差", "校准", "发射率", "镜头"],
    ),
    (r"跌落|撞击|震动", ["跌落", "撞击", "震动", "校准", "停用"]),
    (r"触点.*氧化|氧化", ["触点", "氧化", "酒精", "清洁", "电池"]),
    # 操作流程类
    (
        r"切换.*温度|温度.*单位|摄氏|华氏",
        ["切换", "温度单位", "摄氏度", "华氏度", "MODE", "Unit"],
    ),
    (r"报警|高低温", ["报警", "高温", "低温", "Alarm", "阈值"]),
    (r"最大值|最小值|MAX|MIN", ["最大值", "最小值", "MAX", "MIN", "锁定"]),
    (r"校准.*前|放置.*时间|平衡", ["校准", "放置", "时间", "平衡", "30分钟", "温度"]),
    # 参数查询类
    (r"校准.*环境|环境.*温度|环境.*要求", ["校准", "环境", "温度", "湿度", "大气压力"]),
    (r"校准.*周期|校准.*频率", ["校准", "周期", "频率", "每年", "半年", "季度"]),
    (r"保修|质保", ["保修", "质保", "期限", "12个月", "6个月", "3个月"]),
    (r"发射率", ["发射率", "0.10", "1.00", "可调"]),
    (r"精度|准确度", ["精度", "准确度", "1.5", "误差"]),
    (r"距离系数|D:S", ["距离系数", "D:S", "50:1", "12:1"]),
    (r"响应时间", ["响应时间", "300ms", "快速"]),
    (r"存储|记录.*数", ["存储", "记录", "100组", "数据"]),
    # 未收录类（不扩展，保持原样）
]

# 故障码/型号识别：保持原样不扩展（交给 find_missing_identifiers 处理）
FAULT_CODE_RE = re.compile(r"^[A-Z][-_]?[0-9]{2,4}$", re.IGNORECASE)
MODEL_RE = re.compile(r"^T\d{3}([A-Z]?)$", re.IGNORECASE)


class QueryRewriter:
    """轻量查询改写器：规则 + 同义词表

    策略：
        1. 故障码/型号（E03、T200）不扩展，直接返回原文
        2. 匹配同义词规则 → 原文 + 扩展词拼接
        3. 无匹配 → 返回原文
    """

    def __init__(self, rules: list[tuple] | None = None):
        self.rules = rules or SYNONYM_RULES

    def rewrite(self, query: str) -> str:
        """改写查询，返回扩展后的查询字符串"""
        # 故障码/型号不扩展
        stripped = query.strip()
        if FAULT_CODE_RE.match(stripped) or MODEL_RE.match(stripped):
            return query

        # 收集所有匹配的扩展词
        expanded_words: list[str] = []
        for pattern, words in self.rules:
            if re.search(pattern, query, re.IGNORECASE):
                for w in words:
                    if w not in expanded_words and w not in query:
                        expanded_words.append(w)

        if not expanded_words:
            return query

        # 原文 + 扩展词拼接
        return query + " " + " ".join(expanded_words)

    def rewrite_batch(self, queries: list[str]) -> list[str]:
        """批量改写"""
        return [self.rewrite(q) for q in queries]


# 便捷函数
def rewrite_query(query: str) -> str:
    """单条查询改写"""
    return QueryRewriter().rewrite(query)
