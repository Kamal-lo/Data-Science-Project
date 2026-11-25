"""
Script CLI (T40) : Indexe le corpus exemple de l'entreprise dans Qdrant.

Usage :
    python scripts/seed_sample_corpus.py
    QDRANT_MODE=memory EMBEDDING_PROVIDER=hash python scripts/seed_sample_corpus.py
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
from rag_module.schemas import ClientType, CorpusDocType


def main() -> None:
    settings = RAGSettings()
    embedder = create_embedding_provider(settings)
    store = QdrantCorpusStore(settings=settings, vector_size=embedder.dimension)
    indexer = CorpusIndexer(settings=settings, embedding_provider=embedder, store=store)

    sample_dir = ROOT_DIR / "data" / "sample_corpus"
    profile_path = sample_dir / "company_profile_sample.json"
    profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
    company_id = str(profile_data["id"])

    # 1. Indexation du profil entreprise (qualifications, CVs, parc matériel, références)
    summary_profile = indexer.index_company_profile(
        profile_data=profile_data,
        source_file=profile_path.name,
    )
    print(f"[T40] Profil entreprise indexé : {summary_profile.model_dump()}")

    # 2. Indexation des documents complémentaires (mémoire gagné, CV détaillé, PAQ/DNSSI)
    extra_docs = [
        load_document_from_file(
            sample_dir / "memoire_gagne_cloud_2023.md",
            company_id=company_id,
            doc_type=CorpusDocType.MEMOIRE_GAGNE,
            doc_id="memoire_cloud_add_2023",
            title="Mémoire Technique Gagné — Plateforme Cloud Souveraine ADD (2023)",
            sector="Informatique et Télécommunications",
            year=2023,
            client_type=ClientType.PUBLIC,
            amount_mad=5400000.0,
            tags=["Cloud Souverain", "Kubernetes", "Dématérialisation", "DNSSI", "Support 24/7"],
        ),
        load_document_from_file(
            sample_dir / "cv_architecte_cloud.txt",
            company_id=company_id,
            doc_type=CorpusDocType.CV,
            doc_id="cv_mehdi_tazi_devsecops",
            title="CV Mehdi Tazi — Lead Ingénieur DevSecOps",
            sector="Informatique et Télécommunications",
            year=2024,
            tags=["DevSecOps", "Kubernetes", "CKS", "Terraform", "FastAPI", "DNSSI"],
        ),
        load_document_from_file(
            sample_dir / "moyens_techniques_securite.md",
            company_id=company_id,
            doc_type=CorpusDocType.MOYENS,
            doc_id="paq_securite_dnssi_2024",
            title="Plan d'Assurance Qualité (ISO 9001), Sécurité DNSSI & Support 24/7",
            sector="Informatique et Télécommunications",
            year=2024,
            tags=["ISO 9001:2015", "ISO 27001:2022", "DNSSI", "Loi 09-08", "PAQ", "Support 24/7"],
        ),
    ]

    summary_docs = indexer.index_documents(extra_docs)
    print(f"[T40] Documents complémentaires indexés : {summary_docs.model_dump()}")
    print(f"[T40] Statistiques Qdrant : {store.get_stats(company_id=company_id)}")


if __name__ == "__main__":
    main()
