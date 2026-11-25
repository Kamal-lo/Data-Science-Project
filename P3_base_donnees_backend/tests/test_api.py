"""Tests d'intégration de l'API FastAPI P3 (T40, T41, T42)."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from api.main import RAGServices, create_app
from rag_module.templates.prompt_builder import PromptBuilder


def test_fastapi_endpoints_t40_t41_t42(rag_stack, sample_dce_context):
    services = RAGServices(
        settings=rag_stack["settings"],
        embedding_provider=rag_stack["embedder"],
        store=rag_stack["store"],
        indexer=rag_stack["indexer"],
        reranker=rag_stack["reranker"],
        pipeline=rag_stack["pipeline"],
        prompt_builder=PromptBuilder(),
    )
    app = create_app(services=services)
    client = TestClient(app)

    # 1. Health
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["qdrant"]["status"] == "ok"

    # 2. T40 — Stats & Indexation
    company_id = rag_stack["company_id"]
    stats = client.get(f"/api/v1/corpus/stats?company_id={company_id}")
    assert stats.status_code == 200
    assert stats.json()["filtered_points"] > 0

    # 3. T41 — Retrieval
    ret = client.post(
        "/api/v1/rag/retrieve",
        json={
            "query": "Architecte Cloud Souverain DNSSI Kubernetes",
            "filters": {"company_id": company_id, "doc_types": ["cv", "memoire_gagne"]},
            "final_top_k": 3,
        },
    )
    assert ret.status_code == 200
    body = ret.json()
    assert len(body["results"]) == 3
    assert body["trace"]["reranker_used"] == "hybrid_lexical_reranker"

    # 4. T42 — Liste des 6 sections & construction d'un prompt ancré
    sections = client.get("/api/v1/templates/sections")
    assert sections.status_code == 200
    assert len(sections.json()) == 6

    built = client.post(
        "/api/v1/templates/sections/section_4_moyens_humains/build-prompt",
        json={
            "company_id": company_id,
            "company_name": "Atlas Cloud & Systèmes SARL",
            "dce_context": sample_dce_context.model_dump(),
            "language": "fr",
            "top_k": 4,
            "strict_doc_type_filter": True,
        },
    )
    assert built.status_code == 200
    built_body = built.json()
    assert built_body["prompt"]["section_order"] == 4
    assert len(built_body["prompt"]["sources"]) >= 1
    assert all(s["doc_type"] in {"cv", "moyens"} for s in built_body["prompt"]["sources"])
