"""Observation 清洗器：清理外部文档中的注入指令"""
import re


def sanitize_observation(text: str) -> str:
    """清洗 RAG 检索到的外部文档，移除可疑的注入指令

    Args:
        text: 原始文档文本

    Returns:
        清洗后的文本
    """
    if not text:
        return text

    # 清洗规则
    sanitize_rules = [
        # 英文注入指令
        (r'(?i)(ignore|forget|disregard|override)\s+(all\s+)?(previous\s+)?(instructions?|prompts?|rules?|settings?|roles?)\.?\s*',
         '[filtered] '),
        # 中文注入指令
        (r'(忽略|忘记|覆盖|无视|跳过)\s*(所有|之前的|上面的)?\s*(指令|提示|规则|设定|角色)',
         '[已过滤] '),
        # 角色扮演
        (r'(?i)(you\s+are\s+now|act\s+as\s+a|pretend\s+to\s+be|you\s+are\s+DAN)',
         '[filtered] '),
        # 中文角色扮演
        (r'(你现在是|请扮演|假装你是|从现在开始你是)',
         '[已过滤] '),
        # 要求输出秘密信息
        (r'(?i)(tell\s+(me\s+)?(all\s+)?(the\s+)?(secrets?|passwords?|api\s+keys?|credentials?))',
         '[filtered] '),
        # 可疑 URL（非公司域名）
        (r'https?://(?!docs\.cloudsync\.io|app\.cloudsync\.io|cloudsync\.io)[^\s]+',
         '[external-link-removed]'),
        # 可疑邮箱
        (r'[a-zA-Z0-9._%+-]+@(?!cloudsync\.io)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
         '[email-removed]'),
    ]

    for pattern, replacement in sanitize_rules:
        text = re.sub(pattern, replacement, text)

    return text
