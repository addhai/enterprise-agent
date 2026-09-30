"""配置分类清单 —— 全项目单一来源

原先这份清单定义在 src/api/config.py。为了让配置中心服务层
（src/config_center/service.py）与接口层共用同一份定义、避免两处漂移，
现移到本模块，src/api/config.py 改为从这里导入。
对外的名字与结构完全不变，既有调用方与测试无需改动。

字段选择原则：
    只放「改了有用、且不应该需要重启」的运行时参数。
    连接串、端口、存储路径这类引导期配置不放进来（见 schema.READONLY_FIELDS）。
"""

from __future__ import annotations

from typing import Any

CONFIG_CATEGORIES: dict[str, dict[str, Any]] = {
    "llm": {
        "label": "LLM 模型",
        "description": "大语言模型推理参数",
        "fields": [
            "llm_model",
            "llm_complex_model",
            "llm_temperature",
            "llm_max_tokens",
            "llm_enable_thinking",
        ],
    },
    "retrieval": {
        "label": "检索配置",
        "description": "知识库检索参数（相似度阈值、top_k 等）",
        "fields": [
            "retrieval_top_k",
            "retrieval_rerank_top_n",
            "retrieval_min_tokens",
            "kb_similarity_threshold",
            "kb_call_mode",
            "kb_weights",
        ],
    },
    "rerank": {
        "label": "重排序",
        "description": "检索结果重排序（P1 功能）",
        "fields": ["rerank_enabled", "rerank_provider", "rerank_model", "rerank_top_n"],
    },
    "rag": {
        "label": "RAG/文档",
        "description": "文档分块与 DeepDoc 解析",
        "fields": [
            "chunk_size",
            "chunk_overlap",
            "deepdoc_enabled",
            "deepdoc_scan_threshold",
            "deepdoc_render_dpi",
        ],
    },
    "dedup": {
        "label": "去重",
        "description": "文档去重策略",
        "fields": [
            "dedup_exact_enabled",
            "dedup_simhash_enabled",
            "dedup_simhash_threshold",
            "dedup_simhash_window",
        ],
    },
    "guardrail": {
        "label": "安全护栏",
        "description": "输入安全检测（P2 功能）",
        "fields": [
            "guardrail_enabled",
            "guardrail_llm_jailbreak",
            "guardrail_llm_relevance",
        ],
    },
    "hitl": {
        "label": "人工审批",
        "description": "敏感操作人工审批（P2 功能）",
        "fields": [
            "humanloop_enabled",
            "humanloop_timeout",
            "humanloop_notify_channel",
        ],
    },
    "memory": {
        "label": "记忆",
        "description": "短期/长期记忆参数",
        "fields": [
            "memory_context_max_docs",
            "context_rounds",
            "short_term_ttl",
            "short_term_max_window",
        ],
    },
    "evaluation": {
        "label": "评估",
        "description": "质量评估配置（P5 功能）",
        "fields": [
            "eval_llm_judge_enabled",
            "eval_online_sampling_rate",
            "eval_hallucination_check_enabled",
        ],
    },
    "vision": {
        "label": "视觉/OCR",
        "description": "图像理解与 OCR 引擎",
        "fields": [
            "vision_engine_name",
            "vision_model",
            "vision_timeout",
            "ocr_engine_name",
            "fallback_ocr_name",
        ],
    },
    "agent": {
        "label": "Agent",
        "description": "Agent 推理轮次",
        "fields": [
            "max_reasoning_turns",
            "max_turns_faq",
            "max_turns_technical",
            "max_turns_complex",
        ],
    },
    "outline": {
        "label": "大纲/章节",
        "description": "文档大纲元数据",
        "fields": ["outline_store_full_json"],
    },
}
