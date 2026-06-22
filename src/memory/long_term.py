"""长期记忆管理：跨对话的向量化记忆存储"""
import json
from typing import List, Optional
from datetime import datetime


class LongTermMemory:
    """管理跨对话的长期记忆"""

    def __init__(self):
        # 生产环境用向量库 + PG。学习版用内存字典模拟。
        self._memories: dict = {}  # user_id -> list of memory entries

    def add_memory(
        self,
        user_id: str,
        topic: str,
        content: str,
        metadata: Optional[dict] = None
    ) -> None:
        """添加一条长期记忆"""
        if user_id not in self._memories:
            self._memories[user_id] = []

        entry = {
            "topic": topic,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(),
        }

        # Upsert：同 topic 的旧记忆标记为 superseded
        for old_entry in self._memories[user_id]:
            if old_entry["topic"] == topic and old_entry.get("status") != "superseded":
                old_entry["status"] = "superseded"

        self._memories[user_id].append(entry)

    def search(self, user_id: str, query: str, top_k: int = 5) -> List[dict]:
        """检索用户的长期记忆（学习版：关键词匹配）"""
        if user_id not in self._memories:
            return []

        active = [
            m for m in self._memories[user_id]
            if m.get("status") != "superseded"
        ]

        # 简单的关键词匹配（生产版用向量检索 + 时间衰减）
        query_lower = query.lower()
        scored = []
        for mem in active:
            score = 0
            content = (mem["topic"] + " " + mem["content"]).lower()
            for word in query_lower.split():
                if word in content:
                    score += 1

            # 时间衰减
            try:
                mem_date = datetime.fromisoformat(mem["timestamp"])
                days_ago = (datetime.now() - mem_date).days
                decay = max(0.1, 1.0 - days_ago / 90)  # 90 天线性衰减
                score *= decay
            except Exception:
                pass

            if score > 0:
                scored.append((mem, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, _ in scored[:top_k]]

    def get_recent(self, user_id: str, limit: int = 5) -> List[dict]:
        """获取用户最近的记忆"""
        if user_id not in self._memories:
            return []

        active = [
            m for m in self._memories[user_id]
            if m.get("status") != "superseded"
        ]
        active.sort(key=lambda x: x["timestamp"], reverse=True)
        return active[:limit]
