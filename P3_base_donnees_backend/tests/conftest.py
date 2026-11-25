"""Fixtures partagées pour les tests T40, T41, T42 sur Qdrant in-memory."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

P3_ROOT = Path(__file__).resolve().parents[1]
if str(P3_ROOT) not in sys.path:
    sys.path.insert(0, str(P3_ROOT))

from rag_module.config import RAGSettings
from rag_module.indexing.embeddings import HashFallbackEmbeddingProvider
from rag_module.indexing.indexer import CorpusIndexer
from rag_module.indexing.loaders import load_document_from_file
from rag_module.indexing.qdrant_store import QdrantCorpusStore
from rag_module.retrieval.pipeline import RAGRetrievalPipeline
from rag_module.retrieval.reranker import HybridLexicalReranker
from rag_module.schemas import ClientType, CorpusDocType, DCEContext


@pytest.fixture()
def sample_corpus_dir() -> Path:
    return P3_ROOT / "data" / "sample_corpus"


@pytest.fixture()
def sample_company_profile(sample_corpus_dir: Path) -> Dict[str, Any]:
    return json.loads((sample_corpus_dir / "company_profile_sample.json").read_text(encoding="utf-8"))


@pytest.fixture()
def sample_dce_context() -> DCEContext:
    return DCEContext(
        dce_id="DCE-2024-001",
        reference_ao="AO Ouvert N° 12/2024/CR-RSK",
        acheteur="Conseil Régional de Rabat-Salé-Kénitra",
        titre_marche_fr="Mise en place d'une plateforme régionale unifiée de services cloud et de dématérialisation",
        titre_marche_ar="إرساء منصة جهوية موحدة للخدمات السحابية ورقمنة المساطر",
        type_prestation="SERVICES",
        delai_execution_mois=10,
        estimation_mad=6500000.0,
        exigences_techniques=[
            "Agrément Domaine D14 ou Certificat BTP Secteur F Classe 2",
            "Deux références similaires supérieures à 3 000 000 MAD",
            "Conformité DNSSI et Loi n° 09-08 (CNDP)",
            "Support technique et garantie 24/7 pendant 12 mois",
        ],
        bareme_criteres=[
            {"critere": "Méthodologie d'exécution et architecture technique", "points_max": 35.0},
            {"critere": "Qualifications et expérience de l'équipe dédiée", "points_max": 35.0},
            {"critere": "Planning et cohérence des jalons", "points_max": 15.0},
            {"critere": "Qualité des références similaires présentées", "points_max": 15.0},
        ],
        contraintes_reglementaires=[
            "Décret n° 2-22-431 relatif aux marchés publics",
            "CCAG-EMO (Décret n° 2-14-394)",
            "Loi n° 09-08 (CNDP) et DNSSI (DGSSI)",
        ],
    )


@pytest.fixture()
def test_settings() -> RAGSettings:
    return RAGSettings(
        qdrant_mode="memory",
        qdrant_collection_name="test_entreprise_corpus",
        embedding_provider="hash",
        embedding_dimension=384,
        reranker_provider="hybrid",
    )


@pytest.fixture()
def rag_stack(test_settings: RAGSettings, sample_corpus_dir: Path, sample_company_profile: Dict[str, Any]):
    """Stack complète T40 + T41 pré-indexée avec le corpus d'exemple dans Qdrant in-memory."""
    embedder = HashFallbackEmbeddingProvider(dimension=test_settings.embedding_dimension)
    store = QdrantCorpusStore(settings=test_settings, vector_size=embedder.dimension)
    indexer = CorpusIndexer(settings=test_settings, embedding_provider=embedder, store=store)
    reranker = HybridLexicalReranker()
    pipeline = RAGRetrievalPipeline(
        settings=test_settings,
        embedding_provider=embedder,
        store=store,
        reranker=reranker,
    )

    company_id = str(sample_company_profile["id"])
    indexer.index_company_profile(sample_company_profile, source_file="company_profile_sample.json")
    indexer.index_documents(
        [
            load_document_from_file(
                sample_corpus_dir / "memoire_gagne_cloud_2023.md",
                company_id=company_id,
                doc_type=CorpusDocType.MEMOIRE_GAGNE,
                doc_id="memoire_cloud_add_2023",
                title="Mémoire Technique Gagné — Plateforme Cloud Souveraine ADD",
                sector="Informatique et Télécommunications",
                year=2023,
                client_type=ClientType.PUBLIC,
                amount_mad=5400000.0,
                tags=["Cloud Souverain", "Kubernetes", "Dématérialisation", "DNSSI"],
            ),
            load_document_from_file(
                sample_corpus_dir / "cv_architecte_cloud.txt",
                company_id=company_id,
                doc_type=CorpusDocType.CV,
                doc_id="cv_mehdi_tazi_devsecops",
                title="CV Mehdi Tazi — Lead DevSecOps",
                sector="Informatique et Télécommunications",
                year=2024,
                tags=["DevSecOps", "Kubernetes", "CKS", "Terraform"],
            ),
            load_document_from_file(
                sample_corpus_dir / "moyens_techniques_securite.md",
                company_id=company_id,
                doc_type=CorpusDocType.MOYENS,
                doc_id="paq_securite_dnssi_2024",
                title="PAQ ISO 9001, Sécurité ISO 27001 & DNSSI",
                sector="Informatique et Télécommunications",
                year=2024,
                tags=["ISO 9001:2015", "ISO 27001:2022", "DNSSI", "Loi 09-08"],
            ),
        ]
    )

    return {
        "settings": test_settings,
        "embedder": embedder,
        "store": store,
        "indexer": indexer,
        "reranker": reranker,
        "pipeline": pipeline,
        "company_id": company_id,
    }
