"""处理管道包"""
from src.rag.processors.base import (
    BaseBatchProcessor,
    BaseProcessor,
    IngestionPipeline,
    ProcessingContext,
)
from src.rag.processors.deduplicate import DeduplicateProcessor
from src.rag.processors.metadata_enrich import MetadataEnrichProcessor
from src.rag.processors.normalize import NormalizeTextProcessor
from src.rag.processors.noise_filter import NoiseFilterProcessor
from src.rag.processors.quality_check import QualityCheckProcessor
from src.rag.processors.structure_detect import StructureDetectProcessor

__all__ = [
    "BaseProcessor",
    "BaseBatchProcessor",
    "ProcessingContext",
    "IngestionPipeline",
    "NormalizeTextProcessor",
    "NoiseFilterProcessor",
    "StructureDetectProcessor",
    "MetadataEnrichProcessor",
    "QualityCheckProcessor",
    "DeduplicateProcessor",
]
