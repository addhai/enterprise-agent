from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，从 .env 和环境变量读取"""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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

    # Retrieval
    chunk_size: int = 512
    chunk_overlap: int = 64
    retrieval_top_k: int = 5
    retrieval_rerank_top_n: int = 3

    # Agent
    max_reasoning_turns: int = 5

    # Redis
    redis_url: str = "redis://localhost:6379"

    # PostgreSQL
    database_url: str = "postgresql://localhost:5432/agent"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
