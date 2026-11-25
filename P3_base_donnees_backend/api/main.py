"""
Service FastAPI pour les tâches P3 : T40 (Indexation Qdrant), T41 (Pipeline RAG) et T42 (Gabarits 6 sections).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from rag_module.config import RAGSettings, get_settings
from rag_module.indexing.embeddings import EmbeddingProvider, create_embedding_provider
from rag_module.indexing.indexer import CorpusIndexer
from rag_module.indexing.qdrant_store import QdrantCorpusStore
from rag_module.retrieval.pipeline import RAGRetrievalPipeline
from rag_module.retrieval.reranker import BaseReranker, create_reranker
from rag_module.schemas import (
    BuildPromptRequest,
    ChunkStrategy,
    CorpusDocument,
    IndexingSummary,
    RenderedSectionPrompt,
    RetrievalRequest,
    RetrievalResponse,
    SectionId,
    SectionTemplate,
)
from rag_module.templates.prompt_builder import PromptBuilder
from rag_module.templates.sections import get_all_section_templates, get_section_template


class IndexDocumentsRequest(BaseModel):
    """Payload d'indexation d'un lot de documents entreprise (T40)."""

    documents: List[CorpusDocument] = Field(..., min_length=1)
    chunk_strategy: Optional[ChunkStrategy] = None
    chunk_size: Optional[int] = Field(default=None, ge=100, le=4000)
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=1000)
    replace_existing: bool = True


class IndexCompanyProfileRequest(BaseModel):
    """Payload d'indexation directe d'un profil conforme à `EntrepriseProfile` (T40)."""

    profile: Dict[str, Any]
    source_file: str = "company_profile.json"
    company_id_override: Optional[str] = None
    chunk_strategy: Optional[ChunkStrategy] = None
    replace_existing: bool = True


class BuildPromptResponse(BaseModel):
    """Sortie combinée T41 + T42 : prompt prêt à l'emploi + trace de retrieval."""

    prompt: RenderedSectionPrompt
    retrieval: RetrievalResponse


@dataclass
class RAGServices:
    """Conteneur des services injectés dans l'application FastAPI."""

    settings: RAGSettings
    embedding_provider: EmbeddingProvider
    store: QdrantCorpusStore
    indexer: CorpusIndexer
    reranker: BaseReranker
    pipeline: RAGRetrievalPipeline
    prompt_builder: PromptBuilder


def build_services(settings: Optional[RAGSettings] = None) -> RAGServices:
    """Instancie l'ensemble des composants T40/T41/T42 autour de Qdrant."""
    cfg = settings or get_settings()
    embedder = create_embedding_provider(cfg)
    store = QdrantCorpusStore(settings=cfg, vector_size=embedder.dimension)
    indexer = CorpusIndexer(settings=cfg, embedding_provider=embedder, store=store)
    reranker = create_reranker(cfg)
    pipeline = RAGRetrievalPipeline(
        settings=cfg,
        embedding_provider=embedder,
        store=store,
        reranker=reranker,
    )
    prompt_builder = PromptBuilder()
    return RAGServices(
        settings=cfg,
        embedding_provider=embedder,
        store=store,
        indexer=indexer,
        reranker=reranker,
        pipeline=pipeline,
        prompt_builder=prompt_builder,
    )


def create_app(services: Optional[RAGServices] = None) -> FastAPI:
    """Fabrique l'application FastAPI (facilite l'injection de dépendances en tests)."""
    settings = services.settings if services else get_settings()
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=(
            "API du Module C (P3 — Rida Mellouki) couvrant exclusivement les tâches "
            "T40 (Indexation Qdrant), T41 (Pipeline RAG avec filtre & reclassement) "
            "et T42 (Gabarits & prompts des 6 sections du mémoire technique)."
        ),
    )

    state: Dict[str, Optional[RAGServices]] = {"services": services}

    def get_rag_services() -> RAGServices:
        if state["services"] is None:
            state["services"] = build_services()
        return state["services"]

    # ------------------------------------------------------------------
    # Santé & Diagnostic Qdrant
    # ------------------------------------------------------------------
    @app.get("/health", tags=["Health"])
    def health(svc: RAGServices = Depends(get_rag_services)) -> Dict[str, Any]:
        try:
            qdrant_info = svc.store.health_check()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Qdrant indisponible : {exc}") from exc
        return {
            "status": "ok",
            "module": "P3_Module_C_T40_T42",
            "embedding_model": svc.embedding_provider.model_name,
            "embedding_dimension": svc.embedding_provider.dimension,
            "reranker": svc.reranker.name,
            "qdrant": qdrant_info,
        }

    # ------------------------------------------------------------------
    # T40 — Indexation du corpus entreprise dans Qdrant
    # ------------------------------------------------------------------
    @app.post("/api/v1/corpus/documents", response_model=IndexingSummary, tags=["T40 - Indexation Corpus"])
    def index_documents(
        payload: IndexDocumentsRequest,
        svc: RAGServices = Depends(get_rag_services),
    ) -> IndexingSummary:
        return svc.indexer.index_documents(
            documents=payload.documents,
            chunk_strategy=payload.chunk_strategy,
            chunk_size=payload.chunk_size,
            chunk_overlap=payload.chunk_overlap,
            replace_existing=payload.replace_existing,
        )

    @app.post("/api/v1/corpus/company-profile", response_model=IndexingSummary, tags=["T40 - Indexation Corpus"])
    def index_company_profile(
        payload: IndexCompanyProfileRequest,
        svc: RAGServices = Depends(get_rag_services),
    ) -> IndexingSummary:
        return svc.indexer.index_company_profile(
            profile_data=payload.profile,
            source_file=payload.source_file,
            company_id_override=payload.company_id_override,
            chunk_strategy=payload.chunk_strategy,
            replace_existing=payload.replace_existing,
        )

    @app.get("/api/v1/corpus/stats", tags=["T40 - Indexation Corpus"])
    def corpus_stats(
        company_id: Optional[str] = Query(default=None, description="Filtrer les statistiques par entreprise."),
        svc: RAGServices = Depends(get_rag_services),
    ) -> Dict[str, Any]:
        return svc.store.get_stats(company_id=company_id)

    @app.delete("/api/v1/corpus/documents/{doc_id}", tags=["T40 - Indexation Corpus"])
    def delete_document(
        doc_id: str,
        company_id: Optional[str] = Query(default=None, description="Identifiant entreprise (recommandé)."),
        svc: RAGServices = Depends(get_rag_services),
    ) -> Dict[str, Any]:
        svc.store.delete_by_doc_id(doc_id=doc_id, company_id=company_id)
        return {"deleted": True, "doc_id": doc_id, "company_id": company_id}

    # ------------------------------------------------------------------
    # T41 — Pipeline RAG (filtre métadonnées, recherche vectorielle, reclassement)
    # ------------------------------------------------------------------
    @app.post("/api/v1/rag/retrieve", response_model=RetrievalResponse, tags=["T41 - Pipeline RAG"])
    def retrieve_chunks(
        request: RetrievalRequest,
        svc: RAGServices = Depends(get_rag_services),
    ) -> RetrievalResponse:
        return svc.pipeline.retrieve(request)

    # ------------------------------------------------------------------
    # T42 — Gabarits et prompts des 6 sections du mémoire technique
    # ------------------------------------------------------------------
    @app.get("/api/v1/templates/sections", response_model=List[SectionTemplate], tags=["T42 - Gabarits & Prompts"])
    def list_section_templates() -> List[SectionTemplate]:
        return get_all_section_templates()

    @app.get("/api/v1/templates/sections/{section_id}", response_model=SectionTemplate, tags=["T42 - Gabarits & Prompts"])
    def get_single_section_template(section_id: SectionId) -> SectionTemplate:
        return get_section_template(section_id)

    @app.post(
        "/api/v1/templates/sections/{section_id}/build-prompt",
        response_model=BuildPromptResponse,
        tags=["T42 - Gabarits & Prompts"],
    )
    def build_section_prompt(
        section_id: SectionId,
        request: BuildPromptRequest,
        svc: RAGServices = Depends(get_rag_services),
    ) -> BuildPromptResponse:
        rendered, retrieval_res = svc.prompt_builder.retrieve_and_build_prompt(
            pipeline=svc.pipeline,
            section_id=section_id,
            request=request,
        )
        return BuildPromptResponse(prompt=rendered, retrieval=retrieval_res)

    return app


app = create_app()
