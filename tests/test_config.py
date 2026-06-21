import os
import pytest
from pathlib import Path


def test_settings_loads_from_env():
    """Settings 应该从环境变量读取配置"""
    os.environ["OPENAI_API_KEY"] = "test-key-123"
    os.environ["CHROMA_PERSIST_DIR"] = "./test_chroma"

    # 重新导入以触发新环境变量
    from src.config import Settings
    settings = Settings()

    assert settings.openai_api_key == "test-key-123"
    assert settings.chroma_persist_dir == "./test_chroma"


def test_settings_default_values():
    """Settings 应该有合理的默认值"""
    from src.config import Settings
    settings = Settings()

    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.max_reasoning_turns == 5
    assert settings.chunk_size == 512
    assert settings.retrieval_top_k == 5
