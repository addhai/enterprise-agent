"""BaseLoader 抽象基类 + LoaderRegistry 注册表"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional, Type

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc
else:
    _Doc = "Document"

from src.rag.data_sources import FileInfo


# ---------------------------------------------------------------------------
# BaseLoader
# ---------------------------------------------------------------------------


class BaseLoader(ABC):
    """格式加载器抽象基类

    所有格式加载器必须实现 ``load()`` 方法，返回 LangChain Document 列表。
    统一返回类型是关键约束——确保下游管道处理逻辑不需要做类型判断。
    """

    @abstractmethod
    def load(self, info: FileInfo, base_meta: dict) -> List[_Doc]:
        """加载单个文件并返回 Document 列表

        Args:
            info: 文件信息（由数据源提供）
            base_meta: 基础元数据（来源文件、类别、编码等）

        Returns:
            LangChain Document 列表（可能为空）
        """
        ...


# ---------------------------------------------------------------------------
# LoaderRegistry
# ---------------------------------------------------------------------------


class LoaderRegistry:
    """加载器注册表

    通过 ``@register_loader(".ext")`` 装饰器将扩展名映射到加载器类。
    新增格式只需写一个 Loader 类 + 注册，无需修改主流程。
    """

    _registry: Dict[str, Type[BaseLoader]] = {}

    @classmethod
    def register(cls, ext: str) -> None:
        """手动注册一个加载器类

        Args:
            ext: 文件扩展名（如 ".pdf"），用于查找时匹配
        """
        # 由 @register_loader 装饰器调用，不应直接使用
        raise RuntimeError("Use @register_loader decorator instead of calling register() directly")

    @classmethod
    def get(cls, ext: str) -> Optional[Type[BaseLoader]]:
        """根据扩展名查找对应的加载器类"""
        return cls._registry.get(ext)

    @classmethod
    def list_supported(cls) -> List[str]:
        """列出所有已注册的扩展名"""
        return sorted(cls._registry.keys())


def register_loader(ext: str):
    """装饰器：将加载器类注册到 LoaderRegistry

    Usage::

        @register_loader(".pdf")
        class PdfLoader(BaseLoader):
            def load(self, info, base_meta):
                ...

    Args:
        ext: 文件扩展名（如 ".pdf", ".md"）
    """

    def decorator(cls: Type[BaseLoader]) -> Type[BaseLoader]:
        LoaderRegistry._registry[ext] = cls
        return cls

    return decorator
