"""
Fournisseurs d'embeddings multilingues (FR / AR) pour T40 et T41.

- SentenceTransformerEmbeddingProvider : recommandé en production (ex: intfloat/multilingual-e5-base ou BAAI/bge-m3).
  Applique automatiquement les préfixes `passage:` et `query:` pour les modèles de la famille E5.
- HashFallbackEmbeddingProvider : encodeur déterministe multilingue (tokens + n-grammes de caractères FR/AR)
  normalisé L2 pour les tests unitaires, le CI et le développement hors-ligne sans téléchargement de poids.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from abc import ABC, abstractmethod
from typing import List, Sequence

from rag_module.config import RAGSettings

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9\u00C0-\u024F\u0600-\u06FF]+")


def _normalize_text(text: str) -> str:
    """Normalise le texte FR/AR (minuscules, suppression diacritiques latins/arabes courants)."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    # Supprime les diacritiques combinants latins et voyelles courtes arabes (tashkeel)
    cleaned = "".join(
        ch
        for ch in nfkd
        if not unicodedata.combining(ch) and not ("\u064B" <= ch <= "\u0652")
    )
    # Normalise les variantes d'Alef en arabe
    cleaned = cleaned.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    return cleaned


class EmbeddingProvider(ABC):
    """Interface abstraite pour la vectorisation des passages et requêtes."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nom du modèle d'embeddings utilisé."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimension des vecteurs produits."""

    @abstractmethod
    def embed_passages(self, texts: Sequence[str]) -> List[List[float]]:
        """Encode une liste de chunks/passages du corpus."""

    @abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """Encode une requête de recherche."""


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Fournisseur basé sur `sentence-transformers` (supporte E5 multilingue, BGE-M3, etc.)."""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-base", batch_size: int = 32) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._is_e5 = "e5" in model_name.lower()
        self._model = None
        self._dimension: int | None = None

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ImportError(
                    "Le package 'sentence-transformers' est requis pour SentenceTransformerEmbeddingProvider. "
                    "Installez-le ou utilisez EMBEDDING_PROVIDER=hash."
                ) from exc
            self._model = SentenceTransformer(self._model_name)
            self._dimension = int(self._model.get_sentence_embedding_dimension())
        return self._model

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load_model()
        assert self._dimension is not None
        return self._dimension

    def embed_passages(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        model = self._load_model()
        prepared = [f"passage: {t}" if self._is_e5 else t for t in texts]
        vectors = model.encode(
            prepared,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in vectors]

    def embed_query(self, query: str) -> List[float]:
        model = self._load_model()
        prepared = f"query: {query}" if self._is_e5 else query
        vector = model.encode(
            [prepared],
            batch_size=1,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return vector.tolist()


class HashFallbackEmbeddingProvider(EmbeddingProvider):
    """
    Encodeur léger déterministe (hachage signé de mots, bigrammes et n-grammes de caractères).

    Conserve une vraie similarité cosinus multilingue FR/AR sans dépendance réseau ni GPU,
    idéal pour les tests automatisés et la CI.
    """

    def __init__(self, dimension: int = 384, model_name: str = "hash-multilingual-v1") -> None:
        self._dimension = dimension
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _encode_one(self, text: str) -> List[float]:
        vec = [0.0] * self._dimension
        normalized = _normalize_text(text)
        tokens = TOKEN_PATTERN.findall(normalized)
        if not tokens:
            vec[0] = 1.0
            return vec

        # Pondération : unigrammes (2.0), bigrammes (1.5), trigrammes de caractères (0.5)
        features: List[tuple[str, float]] = []
        for token in tokens:
            if len(token) >= 2:
                features.append((f"w:{token}", 2.0))
                if len(token) >= 4:
                    padded = f"<{token}>"
                    for i in range(len(padded) - 2):
                        features.append((f"c:{padded[i : i + 3]}", 0.45))

        for i in range(len(tokens) - 1):
            features.append((f"b:{tokens[i]}_{tokens[i + 1]}", 1.5))

        for feat, weight in features:
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dimension
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[idx] += sign * weight

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [v / norm for v in vec]
        return vec

    def embed_passages(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._encode_one(t) for t in texts]

    def embed_query(self, query: str) -> List[float]:
        return self._encode_one(query)


def create_embedding_provider(settings: RAGSettings) -> EmbeddingProvider:
    """Fabrique le fournisseur d'embeddings selon la configuration."""
    if settings.embedding_provider == "hash":
        return HashFallbackEmbeddingProvider(dimension=settings.embedding_dimension)
    return SentenceTransformerEmbeddingProvider(
        model_name=settings.embedding_model_name,
        batch_size=settings.embedding_batch_size,
    )
