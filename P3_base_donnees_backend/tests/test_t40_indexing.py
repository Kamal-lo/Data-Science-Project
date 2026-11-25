"""Tests unitaires et d'intégration pour T40 : Indexation du corpus entreprise dans Qdrant."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from rag_module.indexing.chunking import TextChunker
from rag_module.indexing.embeddings import HashFallbackEmbeddingProvider
from rag_module.indexing.indexer import CorpusIndexer
from rag_module.indexing.loaders import (
    company_profile_to_documents,
    detect_language_simple,
    load_document_from_file,
)
from rag_module.indexing.qdrant_store import QdrantCorpusStore
from rag_module.schemas import (
    ChunkStrategy,
    CorpusDocType,
    CorpusDocument,
    DocumentMetadata,
    LanguageCode,
)


def test_sample_company_profile_conforms_to_p3_pydantic_schema(sample_company_profile: Dict[str, Any]):
    """Vérifie la compatibilité totale avec le modèle existant `database/company_profile_model.py`."""
    pytest.importorskip("email_validator")
    from database.company_profile_model import EntrepriseProfile

    parsed = EntrepriseProfile.model_validate(sample_company_profile)
    assert parsed.identification_administrative.raison_sociale == "Atlas Cloud & Systèmes SARL"
    assert len(parsed.moyens_humains.personnel_cle_experts) == 2
    assert len(parsed.references_similaires) == 2


def test_company_profile_to_documents_produces_typed_corpus(sample_company_profile: Dict[str, Any]):
    docs = company_profile_to_documents(sample_company_profile, source_file="company_profile_sample.json")
    doc_types = [d.metadata.doc_type for d in docs]
    assert doc_types.count(CorpusDocType.MOYENS) == 2  # overview + parc matériel
    assert doc_types.count(CorpusDocType.CV) == 2
    assert doc_types.count(CorpusDocType.REFERENCE) == 2


def test_chunking_strategies_preserve_traceability(sample_corpus_dir: Path):
    doc = load_document_from_file(
        sample_corpus_dir / "memoire_gagne_cloud_2023.md",
        company_id="comp-1",
        doc_type=CorpusDocType.MEMOIRE_GAGNE,
        doc_id="memo-01",
    )
    assert doc.metadata.language in {LanguageCode.FR, LanguageCode.BILINGUAL}

    for strategy in [ChunkStrategy.RECURSIVE_STRUCTURE, ChunkStrategy.SENTENCE, ChunkStrategy.FIXED]:
        chunker = TextChunker(strategy=strategy, chunk_size=450, chunk_overlap=60)
        chunks = chunker.chunk_document(doc)
        assert len(chunks) >= 2
        assert all(c.total_chunks == len(chunks) for c in chunks)
        assert all(c.metadata.company_id == "comp-1" for c in chunks)
        assert all(len(c.content_hash) == 64 for c in chunks)

    # La stratégie structurelle doit extraire les titres de section
    struct_chunks = TextChunker(strategy=ChunkStrategy.RECURSIVE_STRUCTURE, chunk_size=450, chunk_overlap=60).chunk_document(doc)
    sections = {c.page_or_section for c in struct_chunks}
    assert any("Architecture" in s or "Approche" in s for s in sections)


def test_detect_language_fr_ar_bilingual():
    assert detect_language_simple("Déploiement d'une plateforme cloud souveraine au Maroc.") == LanguageCode.FR
    assert detect_language_simple("إرساء منصة جهوية موحدة للخدمات السحابية ورقمنة المساطر الإدارية") == LanguageCode.AR
    assert detect_language_simple("Plateforme Cloud — إرساء منصة جهوية موحدة للخدمات السحابية") == LanguageCode.BILINGUAL


def test_qdrant_indexing_is_idempotent_and_supports_delete(test_settings):
    embedder = HashFallbackEmbeddingProvider(dimension=test_settings.embedding_dimension)
    store = QdrantCorpusStore(settings=test_settings, vector_size=embedder.dimension)
    indexer = CorpusIndexer(settings=test_settings, embedding_provider=embedder, store=store)

    doc = CorpusDocument(
        content="# Section A\nMéthodologie de déploiement cloud souverain conforme à la DNSSI et au Décret 2-22-431.",
        metadata=DocumentMetadata(
            company_id="comp-a",
            doc_id="doc-unique-1",
            doc_type=CorpusDocType.MEMOIRE_GAGNE,
            title="Mémoire Cloud",
            source_file="memo.md",
            sector="SERVICES",
            year=2024,
            tags=["DNSSI", "Cloud"],
        ),
    )

    first = indexer.index_documents([doc], replace_existing=True)
    count_after_first = store.count_points(company_id="comp-a")
    assert first.chunks_indexed == count_after_first
    assert count_after_first >= 1

    # Ré-indexation du même document : aucun doublon créé
    second = indexer.index_documents([doc], replace_existing=True)
    assert store.count_points(company_id="comp-a") == count_after_first
    assert second.chunks_indexed == count_after_first

    # Suppression ciblée par doc_id
    store.delete_by_doc_id(doc_id="doc-unique-1", company_id="comp-a")
    assert store.count_points(company_id="comp-a") == 0
