"""加载器插件包"""
from src.rag.loaders.base import BaseLoader, LoaderRegistry, register_loader

__all__ = ["BaseLoader", "LoaderRegistry", "register_loader"]
