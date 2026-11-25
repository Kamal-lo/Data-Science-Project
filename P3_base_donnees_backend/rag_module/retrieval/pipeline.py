"""
Pipeline RAG complet (T41) :
1. Pré-filtrage métadonnées Qdrant (isolation entreprise + filtres métier)
2. Recherche vectorielle dense (similarité cosinus)
3. Reclassement (reranking hybride ou Cross-Encoder)
4. Formatage des citations traçables et télémétrie d'exécution
"""

from __future__ import annotations

import time
from typing import List

from rag_module.config import RAGSettings
from rag_module.indexing.embeddings import EmbeddingProvider
from rag_module.indexing.qdrant_store import QdrantCorpusStore
from rag_module.retrieval.filters import build_qdrant_filter, summarize_filter
from rag_module.retrieval.reranker import BaseReranker, CandidateHit
from rag_module.schemas import (
    CorpusDocType,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalTrace,
    RetrievedChunk,
)


class RAGRetrievalPipeline:
    """Orchestrateur du pipeline RAG T41 sur Qdrant."""

    def __init__(
        self,
        settings: RAGSettings,
        embedding_provider: EmbeddingProvider,
        store: QdrantCorpusStore,
        reranker: BaseReranker,
    ) -> None:
        self.settings = settings
        self.embedding_provider = embedding_provider
        self.store = store
        self.reranker = reranker

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """Exécute le pipeline complet : filtre -> recherche vectorielle -> reclassement."""
        t_start = time.perf_counter()

        # Étape 1 : Construction du filtre métadonnées Qdrant
        t_filter_start = time.perf_counter()
        qdrant_filter = build_qdrant_filter(request.filters)
        applied_filters = summarize_filter(request.filters)
        filter_ms = (time.perf_counter() - t_filter_start) * 1000.0

        # Étape 2 : Encodage requête + recherche vectorielle Qdrant
        t_search_start = time.perf_counter()
        query_vector = self.embedding_provider.embed_query(request.query)
        search_limit = max(request.initial_top_k, request.final_top_k)
        scored_points = self.store.search(
            query_vector=query_vector,
            query_filter=qdrant_filter,
            limit=search_limit,
            score_threshold=request.score_threshold,
        )
        vector_search_ms = (time.perf_counter() - t_search_start) * 1000.0

        candidates: List[CandidateHit] = [
            CandidateHit(
                point_id=str(pt.id),
                vector_score=round(float(pt.score), 6),
                payload=dict(pt.payload or {}),
                rerank_score=round(float(pt.score), 6),
            )
            for pt in scored_points
        ]

        # Étape 3 : Reclassement (Reranking)
        t_rerank_start = time.perf_counter()
        if request.enable_reranking and candidates:
            ranked_hits = self.reranker.rerank(
                query=request.query,
                candidates=candidates,
                top_k=request.final_top_k,
                preferred_doc_types=request.preferred_doc_types,
            )
            reranker_used = self.reranker.name
        else:
            ranked_hits = candidates[: request.final_top_k]
            reranker_used = "disabled_vector_only"
        rerank_ms = (time.perf_counter() - t_rerank_start) * 1000.0

        # Étape 4 : Construction des chunks citables
        results: List[RetrievedChunk] = []
        for rank, hit in enumerate(ranked_hits, start=1):
            payload = hit.payload
            doc_type = CorpusDocType(payload.get("doc_type", CorpusDocType.MOYENS.value))
            source_file = str(payload.get("source_file", "inconnu"))
            page_or_section = str(payload.get("page_or_section", "Section principale"))
            citation_label = f"[SRC-{rank} | {doc_type.value} | {source_file} § {page_or_section}]"

            results.append(
                RetrievedChunk(
                    rank=rank,
                    point_id=hit.point_id,
                    chunk_id=str(payload.get("chunk_id", hit.point_id)),
                    doc_id=str(payload.get("doc_id", "unknown")),
                    doc_type=doc_type,
                    title=str(payload.get("title", "Document sans titre")),
                    source_file=source_file,
                    page_or_section=page_or_section,
                    text=str(payload.get("text", "")),
                    vector_score=hit.vector_score,
                    rerank_score=hit.rerank_score,
                    citation_label=citation_label,
                    metadata={
                        "company_id": payload.get("company_id"),
                        "sector": payload.get("sector"),
                        "year": payload.get("year"),
                        "language": payload.get("language"),
                        "client_type": payload.get("client_type"),
                        "amount_mad": payload.get("amount_mad"),
                        "tags": payload.get("tags", []),
                        "extra": payload.get("extra", {}),
                    },
                )
            )

        total_ms = (time.perf_counter() - t_start) * 1000.0
        trace = RetrievalTrace(
            filter_ms=round(filter_ms, 2),
            vector_search_ms=round(vector_search_ms, 2),
            rerank_ms=round(rerank_ms, 2),
            total_ms=round(total_ms, 2),
            candidates_found=len(candidates),
            returned_count=len(results),
            reranker_used=reranker_used,
            applied_filters=applied_filters,
        )
        return RetrievalResponse(query=request.query, results=results, trace=trace)
