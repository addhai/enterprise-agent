import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    """全局配置，从 .env 和环境变量读取"""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # OpenAI
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"
    llm_complex_model: str = "gpt-4o"

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
