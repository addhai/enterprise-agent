"""全局配置管理

从 config.yaml 加载默认值，支持环境变量覆盖，支持热更新。

环境变量命名规则：
    YAML_CONFIG_PREFIX 前缀 + 层级路径大写 + 字段名
    例：MODEL_OPENAI_API_KEY, CHROMA_PERSIST_DIR, AGENT_MAX_REASONING_TURNS

Usage::

    from src.config import settings

    # 读取配置
    print(settings.model.openai_api_key)

    # 热更新（重新从 YAML 加载）
    settings.reload()

    # 环境变量覆盖
    import os
    os.environ["MODEL_LLM_MODEL"] = "gpt-4"
    settings.reload()  # 新值生效
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置根目录
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# 环境变量前缀
ENV_PREFIX = "YAML_CONFIG_"


# ---------------------------------------------------------------------------
# 配置数据类（扁平化 + 层级）
# ---------------------------------------------------------------------------


@dataclass
class _ModelConfig:
    openai_api_key: str = ""
    openai_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int = 1024
    llm_model: str = "qwen-plus"
    llm_complex_model: str = "qwen-max"
    llm_temperature: float = 0.0


@dataclass
class _LangSmithConfig:
    api_key: str = ""
    project: str = "enterprise-agent"
    tracing: bool = True


@dataclass
class _ChromaConfig:
    persist_dir: str = "./chroma_data"
    collection_name: str = "knowledge_base"
    long_term_collection: str = "long_term_memory"


@dataclass
class _RetrievalConfig:
    top_k: int = 5
    rerank_top_n: int = 3
    min_tokens: int = 200
    context_window: int = 3
    rrf_fusion_k: int = 60
    bm25_score_decay: float = 0.05
    access_levels: list = field(default_factory=lambda: [
        "public", "internal", "confidential", "restricted"
    ])


@dataclass
class _ChunkingConfig:
    chunk_size: int = 512
    chunk_overlap: int = 64
    min_sentence_length: int = 10
    separators: list = field(default_factory=lambda: [
        "\n## ", "\n### ", "\n#### ", "\n---PAGE-BREAK---",
        "\n", " ", ""
    ])


@dataclass
class _AgentConfig:
    max_reasoning_turns: int = 5
    max_turns_faq: int = 1
    max_turns_technical: int = 5
    max_turns_complex: int = 8


@dataclass
class _MemoryConfig:
    redis_url: str = "redis://localhost:6379"
    short_term_ttl: int = 3600
    short_term_max_window: int = 20
    database_url: str = "postgresql://localhost:5432/agent"
    long_term_max_per_user: int = 1000
    context_max_docs: int = 3
    summary_model: str = ""


@dataclass
class _ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000


@dataclass
class _EvaluationConfig:
    llm_judge_enabled: bool = False
    online_sampling_rate: float = 0.0
    hallucination_check_enabled: bool = True
    hallucination_threshold: float = 0.5


@dataclass
class _SafetyConfig:
    pii_detection_enabled: bool = True
    pii_masking_enabled: bool = False
    compliance_local_enabled: bool = True
    compliance_cloud_enabled: bool = False
    compliance_api_key: str = ""
    compliance_auto_block: bool = True


@dataclass
class _VersionHistoryConfig:
    enabled: bool = True
    storage_backend: str = "json"  # json | sqlite
    max_versions_per_file: int = 10
    store_content_preview: bool = True
    store_full_content: bool = False


@dataclass
class _VisionConfig:
    engine_name: str = "qwen"
    model: str = "qwen-vl-plus"
    timeout: float = 10.0
    ocr_engine_name: str = "paddle"
    fallback_ocr_name: str = "tesseract"
    ocr_max_image_size: int = 1024
    circuit_threshold: int = 5
    circuit_reset_seconds: int = 60


@dataclass
class _DedupConfig:
    exact_enabled: bool = True
    simhash_enabled: bool = True
    simhash_threshold: float = 0.95
    simhash_window: int = 500
    semantic_enabled: bool = False
    semantic_threshold: float = 0.90


@dataclass
class _OutlineConfig:
    store_full_json: bool = False


@dataclass
class _DLQConfig:
    db_path: str = "./chroma_data/.dead_letter.db"
    max_retries: int = 3
    retry_delay_base: float = 1.0
    auto_retry_network: bool = True


@dataclass
class _ConcurrencyConfig:
    loader_concurrent: bool = True
    loader_max_workers: int = 4
    rate_limit_qps: float = 10.0
    rate_limit_burst: int = 20
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery: int = 60
    ocr_rate_limit: float = 20.0
    safety_rate_limit: float = 5.0


@dataclass
class _LoaderA2AConfig:
    delegate_timeout: int = 30
    port: int = 9001


@dataclass
class _LoaderConfig:
    encoding: str = "utf-8"
    enable_dedup: bool = True
    dedup_window: int = 200
    default_tenant_id: str = ""
    enforce_quality: bool = True
    max_days_outdated: int = 180
    current_version: int = 302
    quality_score_min_threshold: float = 0.3
    a2a: _LoaderA2AConfig = field(default_factory=_LoaderA2AConfig)


@dataclass
class _ObservabilityConfig:
    metrics_enabled: bool = True
    prometheus_enabled: bool = False
    prometheus_port: int = 9090
    tracing_enabled: bool = True
    tracing_file_enabled: bool = True


@dataclass
# Settings — 扁平化访问 + 层级访问
# ---------------------------------------------------------------------------


class Settings:
    """全局配置管理器

    支持两种访问方式：
        # 层级访问（推荐）
        settings.model.openai_api_key
        settings.chroma.persist_dir
        settings.retrieval.top_k

        # 扁平访问（向后兼容）
        settings.openai_api_key
        settings.chroma_persist_dir
        settings.retrieval_top_k
    """

    def __init__(self) -> None:
        self.model = _ModelConfig()
        self.langsmith = _LangSmithConfig()
        self.chroma = _ChromaConfig()
        self.retrieval = _RetrievalConfig()
        self.chunking = _ChunkingConfig()
        self.agent = _AgentConfig()
        self.memory = _MemoryConfig()
        self.server = _ServerConfig()
        self.evaluation = _EvaluationConfig()
        self.vision = _VisionConfig()
        self.dedup = _DedupConfig()
        self.outline = _OutlineConfig()
        self.dlq = _DLQConfig()
        self.concurrency = _ConcurrencyConfig()
        self.loader = _LoaderConfig()
        self.observability = _ObservabilityConfig()
        self.safety = _SafetyConfig()
        self.version_history = _VersionHistoryConfig()

        # 扁平化别名（向后兼容）
        self._aliases: Dict[str, str] = {
            # Model
            "openai_api_key": "model.openai_api_key",
            "openai_api_base": "model.openai_api_base",
            "embedding_model": "model.embedding_model",
            "embedding_dimensions": "model.embedding_dimensions",
            "llm_model": "model.llm_model",
            "llm_complex_model": "model.llm_complex_model",
            # Chroma
            "chroma_persist_dir": "chroma.persist_dir",
            "chroma_collection_name": "chroma.collection_name",
            # Retrieval
            "retrieval_top_k": "retrieval.top_k",
            "retrieval_rerank_top_n": "retrieval.rerank_top_n",
            "retrieval_min_tokens": "retrieval.min_tokens",
            # Agent
            "max_reasoning_turns": "agent.max_reasoning_turns",
            "max_turns_faq": "agent.max_turns_faq",
            "max_turns_technical": "agent.max_turns_technical",
            "max_turns_complex": "agent.max_turns_complex",
            # Memory
            "redis_url": "memory.redis_url",
            "short_term_ttl": "memory.short_term_ttl",
            "short_term_max_window": "memory.short_term_max_window",
            "database_url": "memory.database_url",
            "long_term_max_per_user": "memory.long_term_max_per_user",
            "memory_context_max_docs": "memory.context_max_docs",
            "memory_summary_model": "memory.summary_model",
            # Server
            "host": "server.host",
            "port": "server.port",
            # Evaluation
            "eval_llm_judge_enabled": "evaluation.llm_judge_enabled",
            "eval_online_sampling_rate": "evaluation.online_sampling_rate",
            "eval_hallucination_check_enabled": "evaluation.hallucination_check_enabled",
            # Vision
            "vision_engine_name": "vision.engine_name",
            "vision_model": "vision.model",
            "vision_timeout": "vision.timeout",
            "ocr_engine_name": "vision.ocr_engine_name",
            "fallback_ocr_name": "vision.fallback_ocr_name",
            "ocr_max_image_size": "vision.ocr_max_image_size",
            "vision_circuit_threshold": "vision.circuit_threshold",
            "vision_circuit_reset_seconds": "vision.circuit_reset_seconds",
            # Dedup
            "dedup_exact_enabled": "dedup.exact_enabled",
            "dedup_simhash_enabled": "dedup.simhash_enabled",
            "dedup_simhash_threshold": "dedup.simhash_threshold",
            "dedup_simhash_window": "dedup.simhash_window",
            "dedup_semantic_enabled": "dedup.semantic_enabled",
            "dedup_semantic_threshold": "dedup.semantic_threshold",
            # Outline
            "outline_store_full_json": "outline.store_full_json",
            # DLQ
            "dlq_db_path": "dlq.db_path",
            "dlq_max_retries": "dlq.max_retries",
            "dlq_retry_delay_base": "dlq.retry_delay_base",
            "dlq_auto_retry_network": "dlq.auto_retry_network",
            # Concurrency
            "loader_concurrent": "concurrency.loader_concurrent",
            "loader_max_workers": "concurrency.loader_max_workers",
            "rate_limit_qps": "concurrency.rate_limit_qps",
            "rate_limit_burst": "concurrency.rate_limit_burst",
            "circuit_breaker_threshold": "concurrency.circuit_breaker_threshold",
            "circuit_breaker_recovery": "concurrency.circuit_breaker_recovery",
            # Loader
            "dedup_window": "loader.dedup_window",
            "max_days_outdated": "loader.max_days_outdated",
            "current_version": "loader.current_version",
            # Observability
            "observability_metrics_enabled": "observability.metrics_enabled",
            "observability_prometheus_enabled": "observability.prometheus_enabled",
            "observability_tracing_enabled": "observability.tracing_enabled",
            "observability_tracing_file_enabled": "observability.tracing_file_enabled",
            # Safety
            "safety_pii_detection_enabled": "safety.pii_detection_enabled",
            "safety_pii_masking_enabled": "safety.pii_masking_enabled",
            "safety_compliance_local_enabled": "safety.compliance_local_enabled",
            "safety_compliance_cloud_enabled": "safety.compliance_cloud_enabled",
            "safety_compliance_auto_block": "safety.compliance_auto_block",
            "safety_compliance_api_key": "safety.compliance_api_key",
            # Version History
            "version_history_enabled": "version_history.enabled",
            "version_history_storage_backend": "version_history.storage_backend",
            "version_history_max_versions": "version_history.max_versions_per_file",
        }

    def _get_nested(self, dotted_path: str) -> Any:
        """通过点号路径获取嵌套属性值"""
        parts = dotted_path.split(".")
        obj = self
        for part in parts:
            obj = getattr(obj, part)
        return obj

    def _set_nested(self, dotted_path: str, value: Any) -> None:
        """通过点号路径设置嵌套属性值"""
        parts = dotted_path.split(".")
        obj = self
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], value)

    def __getattr__(self, name: str) -> Any:
        # 避免递归：检查是否正在初始化
        if name.startswith('_'):
            raise AttributeError(f"'Settings' object has no attribute '{name}'")
        # 先检查是否是扁平化别名
        if name in self._aliases:
            return self._get_nested(self._aliases[name])
        raise AttributeError(f"'Settings' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        # 特殊属性直接设置（包括 _aliases 和所有配置段）
        if name in ("model", "langsmith", "chroma", "retrieval",
                     "chunking", "agent", "memory", "server",
                     "evaluation", "vision", "dedup", "outline",
                    "dlq", "concurrency", "loader", "observability",
                     "safety", "version_history",
                     "_aliases"):
            super().__setattr__(name, value)
        elif name.startswith('_'):
            super().__setattr__(name, value)
        elif hasattr(self, '_aliases') and name in self._aliases:
            self._set_nested(self._aliases[name], value)
        elif name in ("model", "langsmith", "chroma", "retrieval",
                     "chunking", "agent", "memory", "server",
                     "evaluation", "vision", "dedup", "outline",
                     "dlq", "concurrency", "loader", "observability",
                     "safety", "version_history",
                     "_aliases"):
            super().__setattr__(name, value)
        else:
            raise AttributeError(f"Cannot set unknown config: {name}")

    def reload(self) -> None:
        """从 YAML 文件重新加载配置（热更新）"""
        logger.info("Reloading config from %s", CONFIG_PATH)
        data = self._load_yaml(CONFIG_PATH)
        self._apply_config(data)
        # 环境变量覆盖（在 YAML 之后，优先级更高）
        self._apply_env_overrides(data)

    def _load_yaml(self, path: Path) -> Dict:
        """加载 YAML 配置文件"""
        if not path.exists():
            logger.warning("Config file not found: %s, using defaults", path)
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            logger.info("Loaded config from %s", path)
            return data or {}
        except Exception as e:
            logger.error("Failed to load config: %s", e)
            return {}

    def _apply_config(self, data: Dict) -> None:
        """将配置数据应用到 Settings 对象"""
        for section_name, section_data in data.items():
            if not isinstance(section_data, dict):
                continue
            section_obj = getattr(self, section_name, None)
            if section_obj is None:
                logger.warning("Unknown config section: %s", section_name)
                continue

            for key, value in section_data.items():
                if hasattr(section_obj, key):
                    # 嵌套对象（如 loader.a2a）
                    if isinstance(value, dict):
                        sub_obj = getattr(section_obj, key, None)
                        if sub_obj is not None and hasattr(sub_obj, '__dataclass_fields__'):
                            for sk, sv in value.items():
                                if hasattr(sub_obj, sk):
                                    setattr(sub_obj, sk, sv)
                        else:
                            setattr(section_obj, key, value)
                    else:
                        setattr(section_obj, key, value)

    def _apply_env_overrides(self, yaml_data: Dict) -> None:
        """应用环境变量覆盖（优先级最高）"""
        for env_key, env_value in os.environ.items():
            if not env_key.startswith(ENV_PREFIX):
                continue

            # 去掉前缀，转为小写
            raw = env_key[len(ENV_PREFIX):].lower()

            # 智能拆分：尝试多种可能的嵌套路径
            # 策略：尝试所有可能的 "." 插入位置
            candidates = [raw]  # 扁平路径

            # 尝试在已知 section 名前拆分
            sections = ["model", "langsmith", "chroma", "retrieval", "chunking",
                        "agent", "memory", "server", "evaluation", "vision",
                        "dedup", "outline", "dlq", "concurrency", "loader"]
            for sec in sections:
                if raw.startswith(sec + "_"):
                    rest = raw[len(sec) + 1:]
                    # 尝试按单词边界拆分（LLM_MODEL → llm_model）
                    # 简单策略：在已知子 section 名前拆分
                    for sub_sec in ["a2a"]:
                        if sub_sec in rest:
                            candidates.append(f"{sec}.{sub_sec}.{rest.replace(sub_sec, '')}")
                    # 单层嵌套
                    candidates.append(f"{sec}.{rest}")
                    break

            # 解析值类型
            parsed_value = self._parse_env_value(env_value, raw)

            # 尝试所有候选路径
            applied = False
            for dotted_path in candidates:
                try:
                    self._set_nested(dotted_path, parsed_value)
                    applied = True
                    break
                except (AttributeError, KeyError):
                    continue

            if not applied:
                logger.debug(
                    "Env override skipped: %s=%s (no valid path found)",
                    env_key, env_value,
                )

    @staticmethod
    def _parse_env_value(value: str, path: str) -> Any:
        """将环境变量字符串解析为正确类型"""
        # 布尔值
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        # 数字
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass
        # JSON 数组/对象
        if value.startswith("[") or value.startswith("{"):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        # 字符串
        return value


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

settings = Settings()
settings.reload()
