"""Configuration centrale du module RAG P3 (Qdrant, embeddings multilingues, reranking)."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal, Optional

from pydantic import BaseModel, Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    _HAS_PYDANTIC_SETTINGS = True
except ImportError:
    _HAS_PYDANTIC_SETTINGS = False
    BaseSettings = BaseModel  # type: ignore[misc,assignment]


if _HAS_PYDANTIC_SETTINGS:

    class RAGSettings(BaseSettings):
        """Paramètres configurables par variables d'environnement ou fichier .env."""

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

        # --- Qdrant Vector Store ---
        qdrant_mode: Literal["remote", "memory", "local"] = Field(default="remote")
        qdrant_url: str = Field(default="http://localhost:6333")
        qdrant_api_key: Optional[str] = Field(default=None)
        qdrant_local_path: Optional[str] = Field(default=None)
        qdrant_collection_name: str = Field(default="entreprise_corpus")
        qdrant_timeout_seconds: float = Field(default=15.0, ge=1.0)

        # --- Embeddings multilingues (FR / AR) ---
        embedding_provider: Literal["sentence_transformer", "hash"] = Field(default="sentence_transformer")
        embedding_model_name: str = Field(default="intfloat/multilingual-e5-base")
        embedding_dimension: int = Field(default=768, ge=32)
        embedding_batch_size: int = Field(default=32, ge=1)

        # --- Chunking (T40) ---
        default_chunk_strategy: Literal["recursive_structure", "sentence", "fixed"] = Field(
            default="recursive_structure"
        )
        default_chunk_size: int = Field(default=800, ge=100, le=4000)
        default_chunk_overlap: int = Field(default=120, ge=0, le=1000)

        # --- Retrieval & Reranking (T41) ---
        reranker_provider: Literal["hybrid", "cross_encoder"] = Field(default="hybrid")
        reranker_model_name: str = Field(default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
        default_initial_top_k: int = Field(default=20, ge=1, le=100)
        default_final_top_k: int = Field(default=6, ge=1, le=50)

        # --- API ---
        api_title: str = "Module C (P3) — RAG & Gabarits Mémoire Technique"
        api_version: str = "1.0.0"

else:

    class RAGSettings(BaseModel):  # type: ignore[no-redef]
        """Fallback de configuration lisant les variables d'environnement sans pydantic-settings."""

        qdrant_mode: Literal["remote", "memory", "local"] = Field(
            default_factory=lambda: os.getenv("QDRANT_MODE", "remote")  # type: ignore[arg-type]
        )
        qdrant_url: str = Field(default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333"))
        qdrant_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
        qdrant_local_path: Optional[str] = Field(default_factory=lambda: os.getenv("QDRANT_LOCAL_PATH") or None)
        qdrant_collection_name: str = Field(
            default_factory=lambda: os.getenv("QDRANT_COLLECTION_NAME", "entreprise_corpus")
        )
        qdrant_timeout_seconds: float = Field(
            default_factory=lambda: float(os.getenv("QDRANT_TIMEOUT_SECONDS", "15.0")), ge=1.0
        )

        embedding_provider: Literal["sentence_transformer", "hash"] = Field(
            default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "sentence_transformer")  # type: ignore[arg-type]
        )
        embedding_model_name: str = Field(
            default_factory=lambda: os.getenv("EMBEDDING_MODEL_NAME", "intfloat/multilingual-e5-base")
        )
        embedding_dimension: int = Field(
            default_factory=lambda: int(os.getenv("EMBEDDING_DIMENSION", "768")), ge=32
        )
        embedding_batch_size: int = Field(
            default_factory=lambda: int(os.getenv("EMBEDDING_BATCH_SIZE", "32")), ge=1
        )

        default_chunk_strategy: Literal["recursive_structure", "sentence", "fixed"] = Field(
            default_factory=lambda: os.getenv("DEFAULT_CHUNK_STRATEGY", "recursive_structure")  # type: ignore[arg-type]
        )
        default_chunk_size: int = Field(
            default_factory=lambda: int(os.getenv("DEFAULT_CHUNK_SIZE", "800")), ge=100, le=4000
        )
        default_chunk_overlap: int = Field(
            default_factory=lambda: int(os.getenv("DEFAULT_CHUNK_OVERLAP", "120")), ge=0, le=1000
        )

        reranker_provider: Literal["hybrid", "cross_encoder"] = Field(
            default_factory=lambda: os.getenv("RERANKER_PROVIDER", "hybrid")  # type: ignore[arg-type]
        )
        reranker_model_name: str = Field(
            default_factory=lambda: os.getenv(
                "RERANKER_MODEL_NAME", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
            )
        )
        default_initial_top_k: int = Field(
            default_factory=lambda: int(os.getenv("DEFAULT_INITIAL_TOP_K", "20")), ge=1, le=100
        )
        default_final_top_k: int = Field(
            default_factory=lambda: int(os.getenv("DEFAULT_FINAL_TOP_K", "6")), ge=1, le=50
        )

        api_title: str = "Module C (P3) — RAG & Gabarits Mémoire Technique"
        api_version: str = "1.0.0"


@lru_cache(maxsize=1)
def get_settings() -> RAGSettings:
    """Retourne l'instance singleton des paramètres RAG."""
    return RAGSettings()
