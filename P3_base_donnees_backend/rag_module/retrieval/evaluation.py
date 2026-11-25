"""
Utilitaires d'évaluation Recall@k et MRR pour comparer chunking, retrieval vectoriel et reclassement (T40/T41).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from rag_module.retrieval.pipeline import RAGRetrievalPipeline
from rag_module.schemas import CorpusDocType, MetadataFilter, RetrievalRequest


@dataclass
class EvalQuery:
    """Cas de test annoté pour mesurer recall@k et MRR."""

    query: str
    filters: MetadataFilter
    relevant_doc_ids: List[str]
    preferred_doc_types: Optional[List[CorpusDocType]] = None
    label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def compute_recall_at_k(
    retrieved_doc_ids: Sequence[str],
    relevant_doc_ids: Iterable[str],
    k: int,
) -> float:
    """Calcule le Recall@k au niveau document (dédupliqué dans le top-k)."""
    relevant_set = set(relevant_doc_ids)
    if not relevant_set:
        return 1.0
    seen: List[str] = []
    for doc_id in retrieved_doc_ids:
        if doc_id not in seen:
            seen.append(doc_id)
        if len(seen) >= k:
            break
    hits = len(relevant_set.intersection(seen))
    return hits / len(relevant_set)


def compute_mrr(
    retrieved_doc_ids: Sequence[str],
    relevant_doc_ids: Iterable[str],
) -> float:
    """Calcule le Mean Reciprocal Rank (MRR) au niveau document."""
    relevant_set = set(relevant_doc_ids)
    if not relevant_set:
        return 1.0
    seen = set()
    rank = 0
    for doc_id in retrieved_doc_ids:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        rank += 1
        if doc_id in relevant_set:
            return 1.0 / rank
    return 0.0


def evaluate_retrieval_pipeline(
    pipeline: RAGRetrievalPipeline,
    eval_queries: Sequence[EvalQuery],
    ks: Sequence[int] = (1, 3, 5),
    initial_top_k: int = 20,
    enable_reranking: bool = True,
) -> Dict[str, Any]:
    """Évalue un pipeline RAG sur un jeu de requêtes annotées (recall@k, MRR, latence)."""
    if not eval_queries:
        return {"num_queries": 0, "recall_at_k": {f"recall@{k}": 0.0 for k in ks}, "mrr": 0.0}

    max_k = max(ks)
    recall_sums = {k: 0.0 for k in ks}
    mrr_sum = 0.0
    latency_sum = 0.0
    per_query: List[Dict[str, Any]] = []

    for item in eval_queries:
        response = pipeline.retrieve(
            RetrievalRequest(
                query=item.query,
                filters=item.filters,
                initial_top_k=max(initial_top_k, max_k),
                final_top_k=max_k,
                enable_reranking=enable_reranking,
                preferred_doc_types=item.preferred_doc_types,
            )
        )
        doc_ids = [r.doc_id for r in response.results]
        q_recalls = {f"recall@{k}": round(compute_recall_at_k(doc_ids, item.relevant_doc_ids, k), 4) for k in ks}
        q_mrr = round(compute_mrr(doc_ids, item.relevant_doc_ids), 4)

        for k in ks:
            recall_sums[k] += compute_recall_at_k(doc_ids, item.relevant_doc_ids, k)
        mrr_sum += compute_mrr(doc_ids, item.relevant_doc_ids)
        latency_sum += response.trace.total_ms

        per_query.append(
            {
                "label": item.label or item.query[:50],
                "query": item.query,
                "expected_doc_ids": item.relevant_doc_ids,
                "retrieved_doc_ids": doc_ids,
                "mrr": q_mrr,
                **q_recalls,
                "latency_ms": response.trace.total_ms,
            }
        )

    n = len(eval_queries)
    return {
        "num_queries": n,
        "enable_reranking": enable_reranking,
        "recall_at_k": {f"recall@{k}": round(recall_sums[k] / n, 4) for k in ks},
        "mrr": round(mrr_sum / n, 4),
        "mean_latency_ms": round(latency_sum / n, 2),
        "per_query": per_query,
    }
