"""Orchestrateur principal d'indexation du corpus entreprise dans Qdrant (T40)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from rag_module.config import RAGSettings
from rag_module.indexing.chunking import TextChunker
from rag_module.indexing.embeddings import EmbeddingProvider
from rag_module.indexing.loaders import company_profile_to_documents
from rag_module.indexing.qdrant_store import QdrantCorpusStore
from rag_module.schemas import ChunkRecord, ChunkStrategy, CorpusDocument, IndexingSummary


class CorpusIndexer:
    """
    Pipeline complet T40 :
    Document(s) -> Découpage traçable (TextChunker) -> Embeddings multilingues -> Upsert Qdrant.
    """

    def __init__(
        self,
        settings: RAGSettings,
        embedding_provider: EmbeddingProvider,
        store: QdrantCorpusStore,
    ) -> None:
        self.settings = settings
        self.embedding_provider = embedding_provider
        self.store = store

    def index_documents(
        self,
        documents: Sequence[CorpusDocument],
        chunk_strategy: Optional[ChunkStrategy] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        replace_existing: bool = True,
    ) -> IndexingSummary:
        """Indexe une liste de `CorpusDocument` (mémoires gagnés, CV, moyens, références)."""
        t0 = time.perf_counter()
        strategy = chunk_strategy or ChunkStrategy(self.settings.default_chunk_strategy)
        size = chunk_size or self.settings.default_chunk_size
        overlap = self.settings.default_chunk_overlap if chunk_overlap is None else chunk_overlap

        chunker = TextChunker(strategy=strategy, chunk_size=size, chunk_overlap=overlap)
        all_chunks: List[ChunkRecord] = []
        doc_ids: List[str] = []

        for doc in documents:
            doc_ids.append(doc.metadata.doc_id)
            if replace_existing:
                self.store.delete_by_doc_id(
                    doc_id=doc.metadata.doc_id,
                    company_id=doc.metadata.company_id,
                )
            chunks = chunker.chunk_document(doc)
            all_chunks.extend(chunks)

        if all_chunks:
            vectors = self.embedding_provider.embed_passages([c.text for c in all_chunks])
            self.store.upsert_chunks(all_chunks, vectors)

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return IndexingSummary(
            collection_name=self.store.collection_name,
            documents_processed=len(documents),
            chunks_indexed=len(all_chunks),
            doc_ids=doc_ids,
            chunk_strategy=strategy,
            embedding_model=self.embedding_provider.model_name,
            elapsed_ms=elapsed_ms,
        )

    def index_company_profile(
        self,
        profile_data: Dict[str, Any],
        source_file: str = "company_profile.json",
        company_id_override: Optional[str] = None,
        chunk_strategy: Optional[ChunkStrategy] = None,
        replace_existing: bool = True,
    ) -> IndexingSummary:
        """Convertit un profil `EntrepriseProfile` (P3/T02) et l'indexe dans Qdrant."""
        documents = company_profile_to_documents(
            profile=profile_data,
            source_file=source_file,
            company_id_override=company_id_override,
        )
        return self.index_documents(
            documents=documents,
            chunk_strategy=chunk_strategy,
            replace_existing=replace_existing,
        )
