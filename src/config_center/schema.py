"""配置中心的字段规格层 —— 约束、只读标记、热更新能力

为什么需要这一层：
    原有配置中心只有「白名单 + 类型转换」，缺三样东西：
      1. 取值范围与枚举校验（int 字段能塞进 -999，float 阈值能塞进 5.0）
      2. 只读标记（数据库连接串这类字段被改会被静默 skip，调用方看不出原因）
      3. 热更新能力标记（白名单里的字段并非都能真的热更，见下）

关于「热更新能力」的重要事实（2026-09-15 实测）：
    字段是否真的能热更新，取决于**消费方是调用时读还是启动时缓存**，
    而不取决于它是否在白名单里。实测发现三类：
      - 调用时读（改完即生效）：kb_similarity_threshold / rewrite_enabled /
        guardrail_enabled / retrieval_vector_only / reflect_enabled
      - 启动时缓存（改了没用）：rerank_enabled、llm_temperature、llm_max_tokens
      - 根本没人读（纯死配置）：retrieval_top_k 曾属于此类，
        三处检索调用都写死了 top_k，配置项形同虚设
    本模块把「能否热更」显式标注出来，并把前两类在第 3 步里改造成真正可热更。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# 启动时只读的字段：改动需要重启进程才能生效
# ---------------------------------------------------------------------------
# 这些是连接串、存储位置、监听端口一类的引导期配置。
# 改了不重启只会造成「内存里是一套、实际连接是另一套」的错位，
# 所以直接拒绝并明确告知需要重启，而不是静默忽略。
READONLY_FIELDS: dict[str, str] = {
    "database_url": "数据库连接串，连接池在启动时建立",
    "redis_url": "Redis 连接串，连接在启动时建立",
    "storage_backend": "存储后端选择，启动时决定使用哪套仓储实现",
    "chroma_persist_dir": "向量库持久化路径，客户端句柄启动时已打开",
    "milvus_host": "Milvus 地址，客户端启动时建立",
    "milvus_port": "Milvus 端口，客户端启动时建立",
    "rabbitmq_url": "消息队列连接串，连接启动时建立",
    "minio_endpoint": "对象存储地址，客户端启动时建立",
    "host": "服务监听地址，进程启动时绑定",
    "port": "服务监听端口，进程启动时绑定",
    "mcp_pg_host": "MCP 数据库主机，连接启动时建立",
    "mcp_pg_port": "MCP 数据库端口，连接启动时建立",
    "mcp_email_smtp_host": "SMTP 主机，连接启动时建立",
    "mcp_email_smtp_port": "SMTP 端口，连接启动时建立",
    "embedding_dimensions": "向量维度，与已入库向量强绑定，改动会导致检索全面失配",
    "vector_store_backend": "向量库后端选择，启动时决定实例化哪个客户端",
}


# ---------------------------------------------------------------------------
# 取值约束：min / max / enum
# ---------------------------------------------------------------------------
# 只列需要约束的字段，未列出的走纯类型校验。
# 每条都是「改错了会真的坏事」的字段，例如 top_k 设 0 会让检索恒空，
# 相似度阈值设 5.0 会让一切结果被过滤掉。
@dataclass
class FieldSpec:
    """单个字段的规格"""

    min_value: float | None = None
    max_value: float | None = None
    enum: tuple[Any, ...] | None = None
    unit: str = ""
    note: str = ""

    def describe(self) -> dict[str, Any]:
        """给前端/API 用的约束描述（无约束时返回空 dict）"""
        out: dict[str, Any] = {}
        if self.min_value is not None:
            out["min"] = self.min_value
        if self.max_value is not None:
            out["max"] = self.max_value
        if self.enum is not None:
            out["enum"] = list(self.enum)
        if self.unit:
            out["unit"] = self.unit
        if self.note:
            out["note"] = self.note
        return out


CONSTRAINTS: dict[str, FieldSpec] = {
    # ---- 检索 ----
    "retrieval_top_k": FieldSpec(1, 50, note="召回条数，设 0 会导致检索恒空"),
    "retrieval_rerank_top_n": FieldSpec(1, 20, note="重排后保留条数，不应大于 top_k"),
    "retrieval_min_tokens": FieldSpec(0, 10000),
    "retrieval_source_cap": FieldSpec(0, 20, note="同一来源最多保留条数，0 表示不限"),
    "kb_similarity_threshold": FieldSpec(
        0.0, 1.0, note="低于该相似度的结果被过滤，1.0 会过滤掉全部结果"
    ),
    # ---- 模型 ----
    "llm_temperature": FieldSpec(0.0, 2.0, note="0 最确定，越高越随机"),
    "llm_max_tokens": FieldSpec(1, 32768),
    # ---- 分块 ----
    "chunk_size": FieldSpec(64, 8192, unit="字符"),
    "chunk_overlap": FieldSpec(0, 4096, unit="字符", note="不应大于 chunk_size"),
    # ---- Agent ----
    "max_reasoning_turns": FieldSpec(1, 20),
    "max_turns_faq": FieldSpec(1, 20),
    "max_turns_technical": FieldSpec(1, 20),
    "max_turns_complex": FieldSpec(1, 20),
    # ---- 记忆 ----
    "memory_context_max_docs": FieldSpec(0, 50),
    "context_rounds": FieldSpec(0, 50, note="携带的历史轮数，0 表示不带历史"),
    "short_term_ttl": FieldSpec(60, 604800, unit="秒", note="下限 60 秒，上限 7 天"),
    "short_term_max_window": FieldSpec(1, 200),
    # ---- 评估 ----
    "eval_online_sampling_rate": FieldSpec(0.0, 1.0, note="线上抽样比例"),
    # ---- 去重 ----
    "dedup_simhash_threshold": FieldSpec(0.0, 1.0),
    "dedup_simhash_window": FieldSpec(1, 64),
    # ---- 视觉/OCR ----
    "vision_timeout": FieldSpec(0.1, 300.0, unit="秒"),
    "deepdoc_render_dpi": FieldSpec(36, 600, unit="DPI"),
    # ---- 安全/会话 ----
    "access_token_expire_hours": FieldSpec(1, 720, unit="小时"),
    "humanloop_timeout": FieldSpec(10, 86400, unit="秒"),
    # ---- 服务调用 ----
    "rag_service_timeout": FieldSpec(0.1, 300.0, unit="秒"),
    # ---- 枚举型 ----
    # Phase3 离线改造：枚举与 src/config.py 的 kb_call_mode 注释统一
    # 取值 always / smart / never（原为 auto/always/never，
    # auto 无实现且与 smart 语义重叠）
    "kb_call_mode": FieldSpec(enum=("always", "smart", "never")),
    "vector_store_backend": FieldSpec(enum=("chroma", "milvus", "auto", "remote")),
    "embedding_provider": FieldSpec(enum=("openai", "dashscope", "local")),
    "ocr_engine_name": FieldSpec(enum=("paddle", "tesseract")),
    "fallback_ocr_name": FieldSpec(enum=("paddle", "tesseract")),
    "vision_engine_name": FieldSpec(enum=("qwen", "openai")),
}


# ---------------------------------------------------------------------------
# 热更新分类（验收要求「至少 5 类配置支持热更新」）
# ---------------------------------------------------------------------------
# 每类给出「代表字段」，这些字段经过第 3 步改造后必须做到改完即生效。
HOT_CATEGORY_FIELDS: dict[str, tuple[str, ...]] = {
    "rag": (
        "retrieval_top_k",
        "chunk_size",
        "kb_similarity_threshold",
        "retrieval_vector_only",
        "rerank_enabled",
    ),
    "model": ("llm_temperature", "llm_max_tokens", "llm_enable_thinking"),
    "feature_flag": (
        "reflect_enabled",
        "rewrite_enabled",
        "guardrail_enabled",
        "rerank_enabled",
    ),
    "safety": ("guardrail_enabled", "access_token_expire_hours", "humanloop_timeout"),
    "other": (
        "max_reasoning_turns",
        "memory_context_max_docs",
        "context_rounds",
        "eval_online_sampling_rate",
    ),
}


def get_spec(field_name: str) -> FieldSpec:
    """取字段约束（无约束返回空规格）"""
    return CONSTRAINTS.get(field_name, FieldSpec())


# ---------------------------------------------------------------------------
# 敏感字段判定（全项目唯一实现）
# ---------------------------------------------------------------------------
# 判据：按 `_` 切词后做**整词**匹配，而不是子串匹配。
#
# 为什么改（实测缺陷 2026-09-15）：
#   原先用子串匹配，`llm_max_tokens` 与 `retrieval_min_tokens` 因为名字里含
#   "token" 子串被判为敏感。它们是生成/检索参数（int，默认 2048 / 200），
#   不是凭据。误判的后果很实际：
#     - GET 读不到值（value 被置空，只剩 configured 标记）
#     - PUT 直接被拒（400「属敏感配置，不提供在线修改接口」）
#   也就是配置中心对这两个字段形同虚设，而它们恰恰是常见的调参对象。
#
# 整词匹配保住了真正的凭据：
#   openai_api_key  -> [openai, api, key]   -> key 命中
#   jwt_secret      -> [jwt, secret]        -> secret 命中
#   access_token    -> [access, token]      -> token 命中
#   minio_secret_key-> [minio, secret, key] -> 命中
#   llm_max_tokens  -> [llm, max, tokens]   -> tokens 是复数计数，不命中
#
# 改动前核对过影响面：只有上述两个字段从「敏感」变为「非敏感」，
# 没有任何字段从「非敏感」变为「敏感」，不存在安全回退。
SENSITIVE_KEYWORDS: tuple = ("key", "secret", "password", "token", "credential")


def is_sensitive(name: str) -> bool:
    """字段名是否敏感（需要脱敏、且不允许在线改写）"""
    return any(part in SENSITIVE_KEYWORDS for part in str(name).lower().split("_"))


def is_readonly(field_name: str) -> bool:
    return field_name in READONLY_FIELDS


def readonly_reason(field_name: str) -> str:
    return READONLY_FIELDS.get(field_name, "")


def hot_categories() -> dict[str, list]:
    """返回可热更新分类的完整结构（供 API 暴露）"""
    return {k: list(v) for k, v in HOT_CATEGORY_FIELDS.items()}
