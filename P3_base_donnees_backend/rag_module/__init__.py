"""
Module C (P3) — RAG et rédaction du mémoire technique (Tâches T40, T41, T42).

- T40 : Indexation du corpus entreprise (mémoires gagnés, CV, moyens, références) dans Qdrant avec métadonnées
- T41 : Pipeline RAG (filtrage métadonnées, recherche vectorielle Qdrant, reclassement)
- T42 : Gabarits et prompts des 6 sections du mémoire technique (Décret n° 2-22-431)
"""

from rag_module.config import RAGSettings, get_settings

__all__ = ["RAGSettings", "get_settings"]
