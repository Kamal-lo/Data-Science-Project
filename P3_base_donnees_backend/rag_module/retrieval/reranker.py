"""
Modules de reclassement (Reranking) pour le pipeline RAG (T41).

- HybridLexicalReranker : reclassement rapide combinant score vectoriel Qdrant, recouvrement lexical
  pondéré IDF (termes techniques FR/AR, acronymes réglementaires), correspondance de bigrammes,
  adéquation du type de document (`preferred_doc_types`) et fraîcheur temporelle.
- CrossEncoderReranker : reclassement neuronal via Cross-Encoder multilingue
  (ex: cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 ou BAAI/bge-reranker-v2-m3).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from rag_module.config import RAGSettings
from rag_module.indexing.embeddings import TOKEN_PATTERN, _normalize_text
from rag_module.schemas import CorpusDocType

FRENCH_STOPWORDS = {
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou", "en", "au", "aux",
    "pour", "par", "sur", "avec", "dans", "que", "qui", "est", "sont", "ce", "ces",
    "cet", "cette", "son", "sa", "ses", "leur", "leurs", "nous", "vous", "ils", "elles",
    "plus", "tout", "tous", "toute", "toutes", "d", "l", "a", "y", "ne", "pas",
}


@dataclass
class CandidateHit:
    """Candidat brut issu de la recherche vectorielle Qdrant avant reclassement."""

    point_id: str
    vector_score: float
    payload: Dict[str, Any]
    rerank_score: float = 0.0


def _tokenize_significant(text: str) -> List[str]:
    normalized = _normalize_text(text)
    return [tok for tok in TOKEN_PATTERN.findall(normalized) if len(tok) >= 2 and tok not in FRENCH_STOPWORDS]


class BaseReranker(ABC):
    """Interface abstraite de reclassement des candidats RAG."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom lisible du reranker pour la télémétrie."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: Sequence[CandidateHit],
        top_k: int,
        preferred_doc_types: Optional[Sequence[CorpusDocType]] = None,
    ) -> List[CandidateHit]:
        """Reclasse les candidats par pertinence décroissante et retourne les `top_k` meilleurs."""


class HybridLexicalReranker(BaseReranker):
    """
    Reranker hybride (vectoriel + BM25-like lexical + bigrammes + métadonnées).

    Particulièrement efficace sur les marchés publics marocains où les sigles exacts
    (Décret 2-22-431, DNSSI, D14, ISO 27001, CNSS, BPU, CCAG-EMO) sont déterminants.
    """

    def __init__(
        self,
        vector_weight: float = 0.50,
        lexical_weight: float = 0.35,
        bigram_weight: float = 0.10,
        doc_type_boost: float = 0.05,
        recency_boost_max: float = 0.03,
    ) -> None:
        self.vector_weight = vector_weight
        self.lexical_weight = lexical_weight
        self.bigram_weight = bigram_weight
        self.doc_type_boost = doc_type_boost
        self.recency_boost_max = recency_boost_max

    @property
    def name(self) -> str:
        return "hybrid_lexical_reranker"

    def rerank(
        self,
        query: str,
        candidates: Sequence[CandidateHit],
        top_k: int,
        preferred_doc_types: Optional[Sequence[CorpusDocType]] = None,
    ) -> List[CandidateHit]:
        if not candidates:
            return []

        query_tokens = _tokenize_significant(query)
        query_token_set = set(query_tokens)
        query_bigrams = {
            f"{query_tokens[i]}_{query_tokens[i + 1]}" for i in range(len(query_tokens) - 1)
        }
        preferred_values = {dt.value for dt in (preferred_doc_types or [])}

        # Statistiques documentaires sur le lot de candidats (IDF local)
        n_docs = len(candidates)
        doc_tokens_list: List[List[str]] = []
        df: Counter[str] = Counter()
        for hit in candidates:
            payload = hit.payload
            searchable = " ".join(
                [
                    str(payload.get("title", "")),
                    str(payload.get("page_or_section", "")),
                    str(payload.get("text", "")),
                    " ".join(payload.get("tags") or []),
                ]
            )
            tokens = _tokenize_significant(searchable)
            doc_tokens_list.append(tokens)
            for unique_tok in set(tokens):
                df[unique_tok] += 1

        avg_doc_len = sum(len(t) for t in doc_tokens_list) / max(1, n_docs)

        # Normalisation min-max des scores vectoriels sur les candidats
        raw_v_scores = [hit.vector_score for hit in candidates]
        v_min = min(raw_v_scores)
        v_max = max(raw_v_scores)
        v_span = v_max - v_min

        rescored: List[CandidateHit] = []
        k1 = 1.2
        b = 0.75

        for hit, doc_tokens in zip(candidates, doc_tokens_list):
            norm_vec = (hit.vector_score - v_min) / v_span if v_span > 1e-9 else max(0.0, min(1.0, hit.vector_score))

            # Score BM25 normalisé
            tf_counts = Counter(doc_tokens)
            doc_len = len(doc_tokens) or 1
            bm25_raw = 0.0
            bm25_max = 0.0
            for q_tok in query_token_set:
                idf = math.log(1.0 + (n_docs - df[q_tok] + 0.5) / (df[q_tok] + 0.5))
                bm25_max += idf * (k1 + 1.0)
                tf = tf_counts.get(q_tok, 0)
                if tf > 0:
                    bm25_raw += idf * ((tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * (doc_len / max(1.0, avg_doc_len)))))
            lexical_score = (bm25_raw / bm25_max) if bm25_max > 0 else 0.0

            # Score bigrammes exacts
            if query_bigrams:
                doc_bigrams = {
                    f"{doc_tokens[i]}_{doc_tokens[i + 1]}" for i in range(len(doc_tokens) - 1)
                }
                bigram_score = len(query_bigrams & doc_bigrams) / len(query_bigrams)
            else:
                bigram_score = 0.0

            # Boost type de document préféré pour la section ciblée
            doc_type_val = hit.payload.get("doc_type")
            type_bonus = self.doc_type_boost if (preferred_values and doc_type_val in preferred_values) else 0.0

            # Bonus léger de fraîcheur (2018 -> 0.0, 2026+ -> recency_boost_max)
            year = hit.payload.get("year")
            if isinstance(year, int):
                recency_ratio = max(0.0, min(1.0, (year - 2018) / 8.0))
                recency_bonus = self.recency_boost_max * recency_ratio
            else:
                recency_bonus = 0.0

            final_score = (
                self.vector_weight * norm_vec
                + self.lexical_weight * lexical_score
                + self.bigram_weight * bigram_score
                + type_bonus
                + recency_bonus
            )

            rescored.append(
                CandidateHit(
                    point_id=hit.point_id,
                    vector_score=hit.vector_score,
                    payload=hit.payload,
                    rerank_score=round(float(final_score), 6),
                )
            )

        rescored.sort(key=lambda h: (h.rerank_score, h.vector_score), reverse=True)
        return rescored[:top_k]


class CrossEncoderReranker(BaseReranker):
    """Reranker neuronal multilingue via `sentence_transformers.CrossEncoder`."""

    def __init__(
        self,
        model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        doc_type_boost: float = 0.05,
    ) -> None:
        self._model_name = model_name
        self._doc_type_boost = doc_type_boost
        self._model = None

    @property
    def name(self) -> str:
        return f"cross_encoder:{self._model_name}"

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise ImportError(
                    "Le package 'sentence-transformers' est requis pour CrossEncoderReranker."
                ) from exc
            self._model = CrossEncoder(self._model_name)
        return self._model

    @staticmethod
    def _sigmoid(x: float) -> float:
        if x >= 0:
            z = math.exp(-x)
            return 1.0 / (1.0 + z)
        z = math.exp(x)
        return z / (1.0 + z)

    def rerank(
        self,
        query: str,
        candidates: Sequence[CandidateHit],
        top_k: int,
        preferred_doc_types: Optional[Sequence[CorpusDocType]] = None,
    ) -> List[CandidateHit]:
        if not candidates:
            return []

        model = self._load_model()
        pairs = [(query, str(hit.payload.get("text", ""))) for hit in candidates]
        raw_scores = model.predict(pairs)
        preferred_values = {dt.value for dt in (preferred_doc_types or [])}

        rescored: List[CandidateHit] = []
        for hit, raw_score in zip(candidates, raw_scores):
            prob = self._sigmoid(float(raw_score))
            doc_type_val = hit.payload.get("doc_type")
            bonus = self._doc_type_boost if (preferred_values and doc_type_val in preferred_values) else 0.0
            rescored.append(
                CandidateHit(
                    point_id=hit.point_id,
                    vector_score=hit.vector_score,
                    payload=hit.payload,
                    rerank_score=round(prob + bonus, 6),
                )
            )

        rescored.sort(key=lambda h: (h.rerank_score, h.vector_score), reverse=True)
        return rescored[:top_k]


def create_reranker(settings: RAGSettings) -> BaseReranker:
    """Fabrique le reranker configuré."""
    if settings.reranker_provider == "cross_encoder":
        return CrossEncoderReranker(model_name=settings.reranker_model_name)
    return HybridLexicalReranker()
