"""Schémas Pydantic V2 partagés pour T40 (Indexation), T41 (Pipeline RAG) et T42 (Gabarits 6 sections)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class CorpusDocType(str, Enum):
    """Catégories officielles du corpus entreprise (T40)."""

    MEMOIRE_GAGNE = "memoire_gagne"
    CV = "cv"
    MOYENS = "moyens"
    REFERENCE = "reference"


class ChunkStrategy(str, Enum):
    """Stratégies de découpage supportées pour la comparaison (T40/T41)."""

    RECURSIVE_STRUCTURE = "recursive_structure"
    SENTENCE = "sentence"
    FIXED = "fixed"


class LanguageCode(str, Enum):
    """Langues prises en charge pour les marchés publics marocains."""

    FR = "fr"
    AR = "ar"
    BILINGUAL = "bilingual"


class ClientType(str, Enum):
    """Type de maître d'ouvrage / client pour les références."""

    PUBLIC = "PUBLIC"
    SEMI_PUBLIC = "SEMI_PUBLIC"
    PRIVE = "PRIVE"


# ==============================================================================
# T40 — Schémas d'indexation du corpus entreprise
# ==============================================================================


class DocumentMetadata(BaseModel):
    """Métadonnées riches attachées à chaque document et propagées dans le payload Qdrant."""

    company_id: str = Field(..., min_length=1, description="Identifiant unique de l'entreprise (isolation multi-tenant).")
    doc_id: str = Field(..., min_length=1, description="Identifiant stable du document source.")
    doc_type: CorpusDocType = Field(..., description="Type de pièce : memoire_gagne, cv, moyens ou reference.")
    title: str = Field(..., min_length=1, description="Titre lisible du document.")
    source_file: str = Field(..., min_length=1, description="Nom ou chemin relatif du fichier source (traçabilité).")
    language: LanguageCode = Field(default=LanguageCode.FR, description="Langue dominante du document.")
    sector: Optional[str] = Field(
        default=None,
        description="Secteur ou type de prestation (ex: SERVICES, TRAVAUX, IT_CLOUD, BTP, ETUDES).",
    )
    year: Optional[int] = Field(
        default=None,
        ge=1990,
        le=2050,
        description="Année du mémoire gagné, de la référence ou de mise à jour du CV/matériel.",
    )
    client_type: Optional[ClientType] = Field(
        default=None,
        description="Type de client (PUBLIC, SEMI_PUBLIC, PRIVE) si applicable.",
    )
    amount_mad: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Montant du marché en MAD (pertinent pour mémoires gagnés et références).",
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Mots-clés techniques, certifications, normes (ex: ['ISO 27001', 'DNSSI', 'Cloud']).",
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        description="Champs additionnels spécifiques (ex: role_titre pour un CV, categorie pour matériel).",
    )

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: List[str]) -> List[str]:
        cleaned: List[str] = []
        seen = set()
        for item in values:
            token = item.strip()
            if token and token.lower() not in seen:
                seen.add(token.lower())
                cleaned.append(token)
        return cleaned


class CorpusDocument(BaseModel):
    """Document brut prêt à être découpé et indexé dans Qdrant."""

    content: str = Field(..., min_length=10, description="Contenu textuel du document.")
    metadata: DocumentMetadata


class ChunkRecord(BaseModel):
    """Unité élémentaire indexée dans Qdrant avec traçabilité complète."""

    point_id: str = Field(..., description="UUID déterministe du point Qdrant.")
    chunk_id: str = Field(..., description="Identifiant humain du chunk (ex: doc_001::chunk_0).")
    text: str = Field(..., min_length=1, description="Texte du fragment.")
    page_or_section: str = Field(
        default="Section principale",
        description="En-tête de section ou numéro de page d'origine (traçabilité).",
    )
    chunk_index: int = Field(..., ge=0)
    total_chunks: int = Field(..., ge=1)
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., ge=0)
    content_hash: str = Field(..., description="Empreinte SHA-256 du contenu normalisé.")
    indexed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Horodatage UTC ISO-8601 de l'indexation.",
    )
    metadata: DocumentMetadata

    def to_qdrant_payload(self) -> Dict[str, Any]:
        """Sérialise le chunk en payload plat optimisé pour le filtrage Qdrant."""
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "page_or_section": self.page_or_section,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "content_hash": self.content_hash,
            "indexed_at": self.indexed_at,
            "company_id": self.metadata.company_id,
            "doc_id": self.metadata.doc_id,
            "doc_type": self.metadata.doc_type.value,
            "title": self.metadata.title,
            "source_file": self.metadata.source_file,
            "language": self.metadata.language.value,
            "sector": self.metadata.sector,
            "year": self.metadata.year,
            "client_type": self.metadata.client_type.value if self.metadata.client_type else None,
            "amount_mad": self.metadata.amount_mad,
            "tags": self.metadata.tags,
            "extra": self.metadata.extra,
        }


class IndexingSummary(BaseModel):
    """Rapport structuré retourné après l'indexation d'un lot de documents (T40)."""

    collection_name: str
    documents_processed: int
    chunks_indexed: int
    doc_ids: List[str]
    chunk_strategy: ChunkStrategy
    embedding_model: str
    elapsed_ms: float


# ==============================================================================
# T41 — Schémas du pipeline RAG (filtre, recherche vectorielle, reclassement)
# ==============================================================================


class MetadataFilter(BaseModel):
    """Critères de pré-filtrage Qdrant avant recherche vectorielle."""

    company_id: str = Field(..., min_length=1, description="Isolation stricte par entreprise.")
    doc_types: Optional[List[CorpusDocType]] = Field(
        default=None,
        description="Restreindre à certains types (ex: ['cv', 'moyens']).",
    )
    sectors: Optional[List[str]] = Field(
        default=None,
        description="Restreindre à un ou plusieurs secteurs d'activité.",
    )
    language: Optional[LanguageCode] = Field(
        default=None,
        description="Filtrer par langue (fr, ar, bilingual).",
    )
    min_year: Optional[int] = Field(default=None, ge=1990, le=2050)
    max_year: Optional[int] = Field(default=None, ge=1990, le=2050)
    client_types: Optional[List[ClientType]] = Field(default=None)
    min_amount_mad: Optional[float] = Field(default=None, ge=0.0)
    tags_any: Optional[List[str]] = Field(
        default=None,
        description="Au moins un de ces tags doit être présent.",
    )
    doc_ids: Optional[List[str]] = Field(
        default=None,
        description="Restreindre la recherche à des doc_id spécifiques.",
    )


class RetrievalRequest(BaseModel):
    """Requête d'entrée du pipeline RAG (T41)."""

    query: str = Field(..., min_length=2, description="Requête ou exigence issue du DCE.")
    filters: MetadataFilter
    initial_top_k: int = Field(default=20, ge=1, le=100, description="Candidats vectoriels initiaux.")
    final_top_k: int = Field(default=6, ge=1, le=50, description="Nombre de résultats après reclassement.")
    score_threshold: Optional[float] = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="Seuil minimal de similarité cosinus sur Qdrant.",
    )
    enable_reranking: bool = Field(default=True, description="Activer l'étape de reclassement.")
    preferred_doc_types: Optional[List[CorpusDocType]] = Field(
        default=None,
        description="Types de documents privilégiés pour le boost de reclassement (sans exclure les autres).",
    )


class RetrievedChunk(BaseModel):
    """Résultat individuel du pipeline RAG avec scores détaillés et citation prête à l'emploi."""

    rank: int = Field(..., ge=1)
    point_id: str
    chunk_id: str
    doc_id: str
    doc_type: CorpusDocType
    title: str
    source_file: str
    page_or_section: str
    text: str
    vector_score: float
    rerank_score: float
    citation_label: str = Field(
        ...,
        description="Étiquette normalisée de citation traçable (ex: [SRC-1 | memoire_gagne | fichier § section]).",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalTrace(BaseModel):
    """Télémétrie détaillée du pipeline RAG pour observabilité et benchmarks."""

    filter_ms: float
    vector_search_ms: float
    rerank_ms: float
    total_ms: float
    candidates_found: int
    returned_count: int
    reranker_used: str
    applied_filters: Dict[str, Any]


class RetrievalResponse(BaseModel):
    """Sortie complète du pipeline RAG (T41)."""

    query: str
    results: List[RetrievedChunk]
    trace: RetrievalTrace


# ==============================================================================
# T42 — Schémas des gabarits et prompts des 6 sections du mémoire technique
# ==============================================================================


class SectionId(str, Enum):
    """Identifiants canoniques des 6 sections du mémoire technique."""

    PRESENTATION_ENTREPRISE = "section_1_presentation_entreprise"
    COMPREHENSION_ENJEUX = "section_2_comprehension_enjeux"
    METHODOLOGIE_TECHNIQUE = "section_3_methodologie_technique"
    MOYENS_HUMAINS = "section_4_moyens_humains"
    MOYENS_MATERIELS_QUALITE = "section_5_moyens_materiels_qualite"
    PLANNING_REFERENCES = "section_6_planning_references"


class DCEContext(BaseModel):
    """Contexte structuré du DCE (issu du module B2 / P6) injecté dans les prompts T42."""

    dce_id: str = Field(..., description="Identifiant du DCE (ex: DCE-2024-001).")
    reference_ao: str = Field(..., description="Référence officielle de l'appel d'offres.")
    acheteur: str = Field(..., description="Maître d'ouvrage / acheteur public.")
    titre_marche_fr: str = Field(..., description="Objet du marché en français.")
    titre_marche_ar: Optional[str] = Field(default=None, description="Objet du marché en arabe si disponible.")
    type_prestation: Literal["SERVICES", "TRAVAUX", "FOURNITURES", "ETUDES"] = Field(default="SERVICES")
    delai_execution_mois: Optional[int] = Field(default=None, ge=1)
    estimation_mad: Optional[float] = Field(default=None, ge=0.0)
    exigences_techniques: List[str] = Field(
        default_factory=list,
        description="Exigences clés extraites du RC/CPS à couvrir obligatoirement.",
    )
    bareme_criteres: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Critères et pondérations du barème technique (ex: [{'critere': '...', 'points_max': 35}]).",
    )
    contraintes_reglementaires: List[str] = Field(
        default_factory=lambda: ["Décret n° 2-22-431 relatif aux marchés publics"],
        description="Textes applicables (Décret 2-22-431, CCAG, DNSSI, Loi 09-08...).",
    )


class SubsectionSpec(BaseModel):
    """Spécification d'une sous-section attendue dans le gabarit."""

    code: str = Field(..., description="Numérotation (ex: '3.1').")
    title: str = Field(..., description="Intitulé de la sous-section.")
    guidance: str = Field(..., description="Attendus précis de rédaction.")


class SectionTemplate(BaseModel):
    """Définition complète d'un gabarit de section du mémoire technique (T42)."""

    section_id: SectionId
    order: int = Field(..., ge=1, le=6)
    title_fr: str
    title_ar: str
    objective: str
    preferred_doc_types: List[CorpusDocType]
    required_subsections: List[SubsectionSpec]
    retrieval_query_template: str
    expected_word_count_range: tuple[int, int]
    anti_hallucination_rules: List[str]
    output_format_instructions: str


class PromptSourceItem(BaseModel):
    """Entrée du registre de citations transmise au LLM (lien T41 -> T42 -> T43)."""

    citation_id: str = Field(..., description="Identifiant court (ex: SRC-1).")
    chunk_id: str
    doc_id: str
    doc_type: CorpusDocType
    source_file: str
    page_or_section: str
    rerank_score: float
    excerpt: str


class RenderedSectionPrompt(BaseModel):
    """Package complet de prompt prêt pour la génération LLM (T44) et vérification anti-hallucination (T43)."""

    section_id: SectionId
    section_order: int
    section_title_fr: str
    section_title_ar: str
    language: LanguageCode
    retrieval_query: str
    system_prompt: str
    user_prompt: str
    sources: List[PromptSourceItem]
    warnings: List[str] = Field(default_factory=list)
    estimated_prompt_chars: int


class BuildPromptRequest(BaseModel):
    """Requête API combinant T41 (retrieval) + T42 (prompt builder) pour une section."""

    company_id: str = Field(..., min_length=1)
    company_name: Optional[str] = Field(default=None)
    dce_context: DCEContext
    language: LanguageCode = Field(default=LanguageCode.FR)
    top_k: int = Field(default=6, ge=1, le=20)
    strict_doc_type_filter: bool = Field(
        default=False,
        description="Si True, filtre strictement Qdrant sur preferred_doc_types de la section.",
    )
    sector_filter: Optional[str] = Field(default=None)
    min_year: Optional[int] = Field(default=None, ge=1990, le=2050)
