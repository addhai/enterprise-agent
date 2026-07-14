from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，从 .env 和环境变量读取"""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI-compatible (阿里云百炼)
    openai_api_key: str = ""
    openai_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int = 1024  # text-embedding-v4 默认 1024 维
    llm_model: str = "qwen-plus"
    llm_complex_model: str = "qwen-max"

    # LangSmith
    langsmith_api_key: str = ""
    langsmith_project: str = "enterprise-agent"
    langsmith_tracing: bool = True

    # Chroma
    chroma_persist_dir: str = "./chroma_data"
    chroma_collection_name: str = "knowledge_base"

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_name: str = "knowledge_chunks"
    vector_store_backend: str = "chroma"        # "chroma" | "milvus" | "auto" | "remote"

    # MinIO / S3
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_docs: str = "agent-docs"       # 文档存储桶
    minio_bucket_logs: str = "agent-logs"       # 日志归档桶
    minio_bucket_models: str = "agent-models"   # 模型权重桶
    minio_use_ssl: bool = False

    # RabbitMQ
    rabbitmq_url: str = "amqp://agent:agent@localhost:5672"
    rabbitmq_exchange: str = "agent.tasks"
    rabbitmq_inference_queue: str = "agent.inference.queue"
    rabbitmq_persist_queue: str = "memory.persist.queue"
    rabbitmq_index_queue: str = "rag.index.queue"
    rabbitmq_notify_queue: str = "notify.push.queue"

    # RAG Service (远程调用)
    rag_service_url: str = "http://localhost:8001"
    rag_service_timeout: float = 10.0           # HTTP 调用超时 (秒)

    # Retrieval
    chunk_size: int = 512
    chunk_overlap: int = 64
    retrieval_top_k: int = 5
    retrieval_rerank_top_n: int = 3
    retrieval_min_tokens: int = 200  # 最小检索 token 数，低于此值标记低置信度

    # Agent
    max_reasoning_turns: int = 5
    max_turns_faq: int = 1
    max_turns_technical: int = 5
    max_turns_complex: int = 8

    # Redis
    redis_url: str = "redis://localhost:6379"
    short_term_ttl: int = 3600          # 短期记忆过期时间（秒），默认 1 小时
    short_term_max_window: int = 20     # 滑动窗口最大消息数

    # PostgreSQL
    database_url: str = "postgresql://localhost:5432/agent"
    long_term_max_per_user: int = 1000  # 每用户长期记忆上限

    # Memory
    memory_context_max_docs: int = 3    # 注入上下文的长期记忆条数
    memory_summary_model: str = ""      # 摘要 LLM 型号，空字符串使用 llm_model

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Evaluation
    eval_llm_judge_enabled: bool = False       # 是否启用 LLM-as-Judge（增加推理成本）
    eval_online_sampling_rate: float = 0.0     # 在线抽样率 (0.0 ~ 1.0)，0 关闭
    eval_hallucination_check_enabled: bool = True  # 幻觉引用检测（依赖检索文档）

    # Vision / OCR
    vision_engine_name: str = "qwen"            # 视觉引擎：qwen / openai
    vision_model: str = "qwen-vl-plus"          # 视觉模型名
    vision_timeout: float = 10.0                # 视觉 API 超时秒数
    ocr_engine_name: str = "paddle"             # 主 OCR：paddle / tesseract
    fallback_ocr_name: str = "tesseract"        # 降级 OCR
    ocr_max_image_size: int = 1024              # OCR 大图缩放阈值
    vision_circuit_threshold: int = 5           # 熔断阈值（连续失败 N 次）
    vision_circuit_reset_seconds: int = 60      # 熔断恢复时间（秒）
    dedup_exact_enabled: bool = True           # 一级：精确去重（整文档哈希）
    dedup_simhash_enabled: bool = True         # 二级：SimHash 近重去重
    dedup_simhash_threshold: float = 0.95      # SimHash 相似度阈值
    dedup_simhash_window: int = 500            # SimHash 计算的文本窗口长度
    dedup_semantic_enabled: bool = False       # 三级：语义去重（预留，默认关闭）
    dedup_semantic_threshold: float = 0.90     # 语义相似度阈值（预留）

    # Outline / Chapter metadata
    outline_store_full_json: bool = False      # 是否在 chunk metadata 中存储完整大纲 JSON
    # False: 仅存 chapter_path + heading_level + heading_text（默认，节省存储）
    # True: 额外存储 outline 完整树 JSON（支持按章节路由，增加存储开销）


settings = Settings()
