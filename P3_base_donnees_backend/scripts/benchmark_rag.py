"""
Script CLI (T40/T41) : Compare les stratégies de chunking et l'impact du reclassement (Recall@k & MRR) sur Qdrant.

Usage :
    python scripts/benchmark_rag.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_module.config import RAGSettings
from rag_module.indexing.embeddings import create_embedding_provider
from rag_module.indexing.indexer import CorpusIndexer
from rag_module.indexing.loaders import load_document_from_file
from rag_module.indexing.qdrant_store import QdrantCorpusStore
from rag_module.retrieval.evaluation import EvalQuery, evaluate_retrieval_pipeline
from rag_module.retrieval.pipeline import RAGRetrievalPipeline
from rag_module.retrieval.reranker import HybridLexicalReranker
from rag_module.schemas import ChunkStrategy, ClientType, CorpusDocType, MetadataFilter


def run_benchmark() -> None:
    sample_dir = ROOT_DIR / "data" / "sample_corpus"
    profile_data = json.loads((sample_dir / "company_profile_sample.json").read_text(encoding="utf-8"))
    company_id = str(profile_data["id"])

    eval_queries = [
        EvalQuery(
            label="Méthodologie & phasage cloud",
            query="Phasage exécution plateforme cloud souveraine conteneurs Kubernetes recette et garantie 12 mois",
            filters=MetadataFilter(company_id=company_id),
            relevant_doc_ids=["memoire_cloud_add_2023"],
            preferred_doc_types=[CorpusDocType.MEMOIRE_GAGNE],
        ),
        EvalQuery(
            label="CV expert DevSecOps",
            query="Ingénieur DevSecOps certifié Kubernetes CKS Terraform intégration portail citoyen",
            filters=MetadataFilter(company_id=company_id, doc_types=[CorpusDocType.CV]),
            relevant_doc_ids=["cv_mehdi_tazi_devsecops"],
            preferred_doc_types=[CorpusDocType.CV],
        ),
        EvalQuery(
            label="Certifications ISO & DNSSI",
            query="Plan assurance qualité ISO 9001 IMANOR sécurité ISO 27001 DNSSI chiffrement AES-256 Loi 09-08",
            filters=MetadataFilter(company_id=company_id, doc_types=[CorpusDocType.MOYENS]),
            relevant_doc_ids=["paq_securite_dnssi_2024", f"{company_id}::profile_overview"],
            preferred_doc_types=[CorpusDocType.MOYENS],
        ),
        EvalQuery(
            label="Références publiques > 4M MAD",
            query="Référence similaire marché public plateforme cloud souveraine téléservices attestation bonne fin",
            filters=MetadataFilter(
                company_id=company_id,
                doc_types=[CorpusDocType.REFERENCE],
                client_types=[ClientType.PUBLIC],
                min_amount_mad=4000000.0,
            ),
            relevant_doc_ids=[f"{company_id}::ref::REF-2023-01", f"{company_id}::ref::REF-2022-02"],
            preferred_doc_types=[CorpusDocType.REFERENCE],
        ),
    ]

    for strategy in [ChunkStrategy.FIXED, ChunkStrategy.SENTENCE, ChunkStrategy.RECURSIVE_STRUCTURE]:
        settings = RAGSettings(
            qdrant_mode="memory",
            embedding_provider="hash",
            embedding_dimension=384,
            qdrant_collection_name=f"bench_{strategy.value}",
        )
        embedder = create_embedding_provider(settings)
        store = QdrantCorpusStore(settings=settings, vector_size=embedder.dimension)
        indexer = CorpusIndexer(settings=settings, embedding_provider=embedder, store=store)

        indexer.index_company_profile(profile_data, source_file="company_profile_sample.json", chunk_strategy=strategy)
        indexer.index_documents(
            [
                load_document_from_file(
                    sample_dir / "memoire_gagne_cloud_2023.md",
                    company_id=company_id,
                    doc_type=CorpusDocType.MEMOIRE_GAGNE,
                    doc_id="memoire_cloud_add_2023",
                    sector="Informatique et Télécommunications",
                    year=2023,
                    client_type=ClientType.PUBLIC,
                    amount_mad=5400000.0,
                    tags=["Cloud Souverain", "Kubernetes", "DNSSI"],
                ),
                load_document_from_file(
                    sample_dir / "cv_architecte_cloud.txt",
                    company_id=company_id,
                    doc_type=CorpusDocType.CV,
                    doc_id="cv_mehdi_tazi_devsecops",
                    sector="Informatique et Télécommunications",
                    year=2024,
                    tags=["DevSecOps", "Kubernetes", "CKS"],
                ),
                load_document_from_file(
                    sample_dir / "moyens_techniques_securite.md",
                    company_id=company_id,
                    doc_type=CorpusDocType.MOYENS,
                    doc_id="paq_securite_dnssi_2024",
                    sector="Informatique et Télécommunications",
                    year=2024,
                    tags=["ISO 9001:2015", "ISO 27001:2022", "DNSSI", "Loi 09-08"],
                ),
            ],
            chunk_strategy=strategy,
        )

        pipeline = RAGRetrievalPipeline(
            settings=settings,
            embedding_provider=embedder,
            store=store,
            reranker=HybridLexicalReranker(),
        )
        res_vec = evaluate_retrieval_pipeline(pipeline, eval_queries, ks=(1, 3, 5), enable_reranking=False)
        res_rerank = evaluate_retrieval_pipeline(pipeline, eval_queries, ks=(1, 3, 5), enable_reranking=True)
        print(f"=== Stratégie : {strategy.value} (points={store.count_points()}) ===")
        print(f"  Vector-only : {res_vec['recall_at_k']} | MRR={res_vec['mrr']} | latence={res_vec['mean_latency_ms']} ms")
        print(f"  + Reranking : {res_rerank['recall_at_k']} | MRR={res_rerank['mrr']} | latence={res_rerank['mean_latency_ms']} ms")


if __name__ == "__main__":
    run_benchmark()
