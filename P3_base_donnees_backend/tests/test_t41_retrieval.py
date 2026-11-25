"""Tests unitaires et d'intégration pour T41 : Pipeline RAG (filtre métadonnées, vectoriel, reclassement)."""

from __future__ import annotations

from rag_module.retrieval.evaluation import (
    EvalQuery,
    compute_mrr,
    compute_recall_at_k,
    evaluate_retrieval_pipeline,
)
from rag_module.schemas import (
    ClientType,
    CorpusDocType,
    CorpusDocument,
    DocumentMetadata,
    MetadataFilter,
    RetrievalRequest,
)


def test_tenant_isolation_prevents_cross_company_leakage(rag_stack):
    indexer = rag_stack["indexer"]
    pipeline = rag_stack["pipeline"]
    company_a = rag_stack["company_id"]

    # Indexe un document pour une entreprise concurrente B
    indexer.index_documents(
        [
            CorpusDocument(
                content="Secret Entreprise B : Méthodologie exclusive BTP ponts et chaussées Classe 1.",
                metadata=DocumentMetadata(
                    company_id="company-B-isolated",
                    doc_id="secret_b_doc",
                    doc_type=CorpusDocType.MEMOIRE_GAGNE,
                    title="Mémoire Secret B",
                    source_file="secret_b.md",
                    sector="TRAVAUX",
                    year=2024,
                ),
            )
        ]
    )

    res_a = pipeline.retrieve(
        RetrievalRequest(
            query="Secret Entreprise B ponts et chaussées",
            filters=MetadataFilter(company_id=company_a),
            final_top_k=10,
        )
    )
    assert all(r.metadata["company_id"] == company_a for r in res_a.results)
    assert all(r.doc_id != "secret_b_doc" for r in res_a.results)

    res_b = pipeline.retrieve(
        RetrievalRequest(
            query="ponts et chaussées Classe 1",
            filters=MetadataFilter(company_id="company-B-isolated"),
            final_top_k=5,
        )
    )
    assert len(res_b.results) == 1
    assert res_b.results[0].doc_id == "secret_b_doc"


def test_metadata_filters_by_doc_type_year_and_amount(rag_stack):
    pipeline = rag_stack["pipeline"]
    company_id = rag_stack["company_id"]

    # Filtre strict sur doc_type = CV
    cv_res = pipeline.retrieve(
        RetrievalRequest(
            query="Ingénieur DevSecOps Kubernetes Terraform sécurité",
            filters=MetadataFilter(company_id=company_id, doc_types=[CorpusDocType.CV]),
            final_top_k=5,
        )
    )
    assert len(cv_res.results) >= 1
    assert all(r.doc_type == CorpusDocType.CV for r in cv_res.results)
    assert cv_res.results[0].doc_id == "cv_mehdi_tazi_devsecops"
    assert cv_res.results[0].citation_label.startswith("[SRC-1 | cv |")

    # Filtre références publiques avec montant >= 5 000 000 MAD et année >= 2024
    ref_res = pipeline.retrieve(
        RetrievalRequest(
            query="plateforme cloud souveraine services numériques",
            filters=MetadataFilter(
                company_id=company_id,
                doc_types=[CorpusDocType.REFERENCE],
                client_types=[ClientType.PUBLIC],
                min_amount_mad=5000000.0,
                min_year=2024,
            ),
            final_top_k=5,
        )
    )
    assert len(ref_res.results) >= 1
    assert {r.doc_id for r in ref_res.results} == {f"{company_id}::ref::REF-2023-01"}
    assert all(r.metadata["amount_mad"] == 5400000.0 for r in ref_res.results)
    assert all(r.metadata["year"] >= 2024 for r in ref_res.results)


def test_reranking_and_telemetry_trace(rag_stack):
    pipeline = rag_stack["pipeline"]
    company_id = rag_stack["company_id"]

    req = RetrievalRequest(
        query="Conformité ISO 27001 DNSSI chiffrement AES-256 et Loi 09-08 CNDP",
        filters=MetadataFilter(company_id=company_id),
        initial_top_k=15,
        final_top_k=4,
        enable_reranking=True,
        preferred_doc_types=[CorpusDocType.MOYENS],
    )
    response = pipeline.retrieve(req)

    assert len(response.results) == 4
    assert response.trace.reranker_used == "hybrid_lexical_reranker"
    assert response.trace.total_ms >= 0.0
    assert response.trace.candidates_found >= 4
    # Le document PAQ/Sécurité DNSSI doit remonter en rang 1 ou 2
    top_ids = [r.doc_id for r in response.results[:2]]
    assert "paq_securite_dnssi_2024" in top_ids
    # Les scores rerank doivent être triés de manière décroissante
    scores = [r.rerank_score for r in response.results]
    assert scores == sorted(scores, reverse=True)


def test_recall_and_mrr_evaluation_metrics(rag_stack):
    assert compute_recall_at_k(["d1", "d2", "d3"], ["d2", "d4"], k=2) == 0.5
    assert compute_mrr(["d1", "d2", "d3"], ["d2"]) == 0.5
    assert compute_mrr(["d1", "d2"], ["d9"]) == 0.0

    pipeline = rag_stack["pipeline"]
    company_id = rag_stack["company_id"]
    queries = [
        EvalQuery(
            label="DevSecOps CV",
            query="Mehdi Tazi DevSecOps Kubernetes CKS Terraform",
            filters=MetadataFilter(company_id=company_id, doc_types=[CorpusDocType.CV]),
            relevant_doc_ids=["cv_mehdi_tazi_devsecops"],
        ),
        EvalQuery(
            label="Mémoire Cloud",
            query="Phasage exécution plateforme cloud souveraine garantie support 24/7",
            filters=MetadataFilter(company_id=company_id),
            relevant_doc_ids=["memoire_cloud_add_2023"],
            preferred_doc_types=[CorpusDocType.MEMOIRE_GAGNE],
        ),
    ]
    report = evaluate_retrieval_pipeline(pipeline, queries, ks=(1, 3), enable_reranking=True)
    assert report["num_queries"] == 2
    assert report["recall_at_k"]["recall@3"] == 1.0
    assert report["mrr"] >= 0.5
