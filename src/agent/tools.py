from typing import Optional, List
from langchain_core.tools import tool
from src.rag.retriever import HybridRetriever


# 简单的内存 FAQ 存储（用于 search_faq 工具）
_FAQ_STORE = {
    "reset password": "To reset your password: Go to Login > Forgot Password. Enter your email. Check your inbox for a reset link valid for 30 minutes.",
    "change plan": "To change your plan: Go to Settings > Billing > Change Plan. Upgrade takes effect immediately. Downgrade at end of billing cycle.",
    "cancel subscription": "To cancel: Go to Settings > Billing > Cancel Subscription. You retain access until the end of the billing period.",
    "api key": "To get an API Key: Go to Console > Developer Settings > API Keys > Generate New Key. Copy immediately — it won't be shown again.",
    "403 error": "403 errors mean access denied. Common causes: 1) Invalid/expired API Key, 2) Domain not whitelisted, 3) CORS configuration missing.",
    "sso": "CloudSync supports SSO via Okta, Azure AD, Google Workspace, and custom SAML 2.0. Go to Settings > SSO to configure.",
    "encryption": "CloudSync encrypts data in transit (TLS 1.3) and at rest (AES-256). Enterprise plans include customer-managed encryption keys.",
    "two factor": "Enable 2FA at Settings > Security > Two-Factor Authentication. Choose authenticator app or SMS.",
    "sync not working": "Check: 1) Providers are authenticated, 2) Available storage, 3) Files not locked by another process.",
    "pricing": "Plans: Free (5GB, 2 providers), Pro ($15/mo, 100GB, 5 providers), Enterprise ($50/user/mo, unlimited).",
}


def _faq_search(query: str) -> Optional[str]:
    """简单的 FAQ 关键词匹配"""
    query_lower = query.lower()
    for keyword, answer in _FAQ_STORE.items():
        if keyword in query_lower:
            return answer
    return None


def create_tools(retriever: HybridRetriever = None, user_id: str = ""):
    """创建客服 Agent 的工具列表

    Args:
        retriever: 混合检索器实例（None 时 search_knowledge_base 返回空）
        user_id: 当前用户 ID（用于日志/审计）
    """

    @tool
    def search_knowledge_base(query: str) -> str:
        """search 搜索产品知识库获取技术文档和配置指南。

        当用户询问关于 API、SSO、配置、错误排查等需要产品文档的问题时使用。
        输入应是一个简洁的搜索查询，如 "SSO Okta 配置" 或 "403 错误排查"。

        Args:
            query: 搜索关键词（使用技术术语，不是完整句子）
        """
        if retriever is None:
            return "知识库当前不可用。请转人工客服。"

        try:
            results = retriever.search(query, top_k=3)
            if not results:
                return "未找到相关文档。建议转人工客服获取帮助。"

            parts = []
            for i, doc in enumerate(results, 1):
                source = doc.metadata.get("source", "unknown")
                content = doc.page_content[:500]
                parts.append(f"[Doc {i} - {source}]\n{content}")

            return "\n\n---\n\n".join(parts)
        except Exception as e:
            return f"知识库搜索出错: {str(e)}。请尝试其他关键词或转人工。"

    @tool
    def search_faq(query: str) -> str:
        """FAQ 搜索常见问题库获取精确匹配的答案。

        当用户询问简单事实性问题（如密码重置、套餐变更、取消订阅等）时优先使用。

        Args:
            query: 问题的关键词，如 "reset password" 或 "change plan"
        """
        result = _faq_search(query)
        if result:
            return f"[FAQ Match] {result}"
        return "FAQ 中未找到匹配项。请尝试 search_knowledge_base 在完整知识库中搜索。"

    @tool
    def escalate_to_human(reason: str) -> str:
        """将当前对话转接人工客服。

        当以下情况时调用此工具：
        1. 用户明确要求转人工
        2. 问题超出知识库覆盖范围
        3. 需要账号操作（退款、删除数据等）
        4. 已进行 2 轮搜索仍未解决

        Args:
            reason: 转接原因，供人工客服参考
        """
        return f"[Escalated to Human] 已为您转接人工客服。转接原因：{reason}。请稍候，客服专员将很快为您服务。"

    return [search_knowledge_base, search_faq, escalate_to_human]
