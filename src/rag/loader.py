from pathlib import Path
from typing import List
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_core.documents import Document


class DocumentLoader:
    """从本地文件系统加载文档"""

    def load_directory(self, dir_path: str) -> List[Document]:
        """加载目录下的所有 .md 文件"""
        loader = DirectoryLoader(
            dir_path,
            glob="**/*.md",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
            show_progress=False,
            use_multithreading=True,
        )
        documents = loader.load()
        return self._clean_metadata(documents)

    def load_file(self, file_path: str) -> List[Document]:
        """加载单个文件"""
        loader = TextLoader(file_path, encoding="utf-8")
        documents = loader.load()
        return self._clean_metadata(documents)

    def _clean_metadata(self, documents: List[Document]) -> List[Document]:
        """清理元数据，只保留 source 字段"""
        for doc in documents:
            # 保留原始 source，去掉多余的元数据
            doc.metadata = {
                "source": Path(doc.metadata.get("source", "")).name
            }
        return documents
