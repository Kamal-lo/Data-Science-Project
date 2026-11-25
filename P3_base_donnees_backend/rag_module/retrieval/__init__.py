"""Sous-package T41 : filtrage métadonnées Qdrant, recherche vectorielle, reclassement et évaluation."""

from rag_module.retrieval.evaluation import (
    EvalQuery,
    compute_mrr,
    compute_recall_at_k,
    evaluate_retrieval_pipeline,
)
from rag_module.retrieval.filters import build_qdrant_filter, summarize_filter
from rag_module.retrieval.pipeline import RAGRetrievalPipeline
from rag_module.retrieval.reranker import (
    BaseReranker,
    CrossEncoderReranker,
    HybridLexicalReranker,
    create_reranker,
)

__all__ = [
    "BaseReranker",
    "CrossEncoderReranker",
    "EvalQuery",
    "HybridLexicalReranker",
    "RAGRetrievalPipeline",
    "build_qdrant_filter",
    "compute_mrr",
    "compute_recall_at_k",
    "create_reranker",
    "evaluate_retrieval_pipeline",
    "summarize_filter",
]
