"""短期记忆管理：滑动窗口 + 对话摘要"""
from typing import List


class ShortTermMemory:
    """管理单次对话的短期记忆"""

    def __init__(self, max_window_size: int = 10):
        self.max_window_size = max_window_size
        self._full_history: List[dict] = []
        self._summary: str = ""

    def add_message(self, role: str, content: str) -> None:
        """添加消息到历史"""
        self._full_history.append({"role": role, "content": content})

    def get_window(self) -> List[dict]:
        """获取滑动窗口内的最近消息"""
        return self._full_history[-self.max_window_size:]

    def get_summary(self) -> str:
        """获取早期对话的摘要"""
        if not self._summary and len(self._full_history) > self.max_window_size:
            self._summary = self._generate_summary()
        return self._summary

    def get_full_context(self) -> List[dict]:
        """获取完整上下文：摘要 + 最近消息"""
        context = []
        summary = self.get_summary()
        if summary:
            context.append({"role": "system", "content": f"[对话前情摘要]\n{summary}"})
        context.extend(self.get_window())
        return context

    def _generate_summary(self) -> str:
        """生成早期对话的摘要"""
        early = self._full_history[:-self.max_window_size]
        if not early:
            return ""

        # 提取关键信息
        key_points = []
        for msg in early:
            content = msg.get("content", "")
            # 简单的关键信息提取（生产环境用 LLM）
            if any(kw in content.lower() for kw in
                   ["api key", "sso", "version", "sdk", "error", "403", "domain"]):
                key_points.append(f"- {msg['role']}: {content[:100]}")

        if key_points:
            return "用户在此对话中提到了以下关键信息：\n" + "\n".join(key_points[:10])
        return ""
