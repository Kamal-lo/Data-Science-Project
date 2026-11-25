"""Sous-package T40 : chargement, découpage, embeddings multilingues et indexation Qdrant."""

from rag_module.indexing.chunking import TextChunker
from rag_module.indexing.embeddings import (
    EmbeddingProvider,
    HashFallbackEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    create_embedding_provider,
)
from rag_module.indexing.indexer import CorpusIndexer
from rag_module.indexing.loaders import (
    company_profile_to_documents,
    load_document_from_file,
)
from rag_module.indexing.qdrant_store import QdrantCorpusStore

__all__ = [
    "CorpusIndexer",
    "EmbeddingProvider",
    "HashFallbackEmbeddingProvider",
    "QdrantCorpusStore",
    "SentenceTransformerEmbeddingProvider",
    "TextChunker",
    "company_profile_to_documents",
    "create_embedding_provider",
    "load_document_from_file",
]
