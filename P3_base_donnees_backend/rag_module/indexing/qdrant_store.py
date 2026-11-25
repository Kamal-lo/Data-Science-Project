"""
Gestionnaire Qdrant pour le stockage vectoriel et les index de métadonnées (T40 & T41).

Fonctionnalités :
- Connexion flexible : serveur Qdrant distant (`remote`), mémoire (`memory`), ou disque local (`local`)
- Création automatique de la collection (distance Cosinus) + Payload Indexes sur les champs filtrés
- Upsert idempotent par lots (UUIDv5 déterministes)
- Recherche vectorielle filtrée via `query_points`
- Suppression par `doc_id` ou `company_id` et statistiques de collection
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from qdrant_client import QdrantClient, models

from rag_module.config import RAGSettings
from rag_module.schemas import ChunkRecord

# Index de payload créés sur Qdrant pour accélérer les pré-filtres T41
PAYLOAD_INDEX_SCHEMAS: Dict[str, models.PayloadSchemaType] = {
    "company_id": models.PayloadSchemaType.KEYWORD,
    "doc_id": models.PayloadSchemaType.KEYWORD,
    "doc_type": models.PayloadSchemaType.KEYWORD,
    "sector": models.PayloadSchemaType.KEYWORD,
    "language": models.PayloadSchemaType.KEYWORD,
    "client_type": models.PayloadSchemaType.KEYWORD,
    "tags": models.PayloadSchemaType.KEYWORD,
    "content_hash": models.PayloadSchemaType.KEYWORD,
    "year": models.PayloadSchemaType.INTEGER,
    "amount_mad": models.PayloadSchemaType.FLOAT,
}


class QdrantCorpusStore:
    """Couche d'accès Qdrant dédiée au corpus entreprise (Module C - P3)."""

    def __init__(
        self,
        settings: RAGSettings,
        vector_size: int,
        client: Optional[QdrantClient] = None,
    ) -> None:
        self.settings = settings
        self.collection_name = settings.qdrant_collection_name
        self.vector_size = vector_size
        self.client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings: RAGSettings) -> QdrantClient:
        if settings.qdrant_mode == "memory":
            return QdrantClient(":memory:")
        if settings.qdrant_mode == "local":
            path = settings.qdrant_local_path or "./qdrant_local_data"
            return QdrantClient(path=path)
        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=settings.qdrant_timeout_seconds,
        )

    def health_check(self) -> Dict[str, Any]:
        """Vérifie la joignabilité de Qdrant et la présence de la collection."""
        collections = self.client.get_collections()
        names = [c.name for c in collections.collections]
        return {
            "status": "ok",
            "mode": self.settings.qdrant_mode,
            "collection_name": self.collection_name,
            "collection_exists": self.collection_name in names,
            "collections_count": len(names),
        }

    def ensure_collection(self) -> None:
        """Crée la collection Qdrant et ses index de payload si absents."""
        exists = self.client.collection_exists(self.collection_name)
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
        # Les index de payload sont créés en mode remote (en mode memory/local ils sont ignorés sans erreur)
        if self.settings.qdrant_mode == "remote":
            for field_name, schema_type in PAYLOAD_INDEX_SCHEMAS.items():
                try:
                    self.client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field_name,
                        field_schema=schema_type,
                    )
                except Exception:
                    # L'index existe déjà ou le serveur est en version antérieure
                    pass

    def upsert_chunks(
        self,
        chunks: Sequence[ChunkRecord],
        vectors: Sequence[Sequence[float]],
        batch_size: int = 64,
    ) -> int:
        """Insère ou met à jour des chunks vectorisés dans Qdrant de façon idempotente."""
        if len(chunks) != len(vectors):
            raise ValueError("Le nombre de chunks doit correspondre au nombre de vecteurs.")
        if not chunks:
            return 0

        self.ensure_collection()
        points = [
            models.PointStruct(
                id=chunk.point_id,
                vector=list(vec),
                payload=chunk.to_qdrant_payload(),
            )
            for chunk, vec in zip(chunks, vectors)
        ]

        for start in range(0, len(points), batch_size):
            batch = points[start : start + batch_size]
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
                wait=True,
            )
        return len(points)

    def search(
        self,
        query_vector: Sequence[float],
        query_filter: Optional[models.Filter] = None,
        limit: int = 20,
        score_threshold: Optional[float] = None,
    ) -> List[models.ScoredPoint]:
        """Exécute une recherche vectorielle avec pré-filtrage métadonnées sur Qdrant."""
        if not self.client.collection_exists(self.collection_name):
            return []

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=list(query_vector),
            query_filter=query_filter,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        return list(response.points)

    def delete_by_doc_id(self, doc_id: str, company_id: Optional[str] = None) -> None:
        """Supprime tous les chunks associés à un document (et éventuellement à une entreprise)."""
        if not self.client.collection_exists(self.collection_name):
            return

        conditions: List[models.Condition] = [
            models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))
        ]
        if company_id:
            conditions.append(
                models.FieldCondition(key="company_id", match=models.MatchValue(value=company_id))
            )

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(filter=models.Filter(must=conditions)),
            wait=True,
        )

    def delete_by_company_id(self, company_id: str) -> None:
        """Supprime l'intégralité du corpus d'une entreprise donnée."""
        if not self.client.collection_exists(self.collection_name):
            return

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="company_id", match=models.MatchValue(value=company_id))]
                )
            ),
            wait=True,
        )

    def count_points(self, company_id: Optional[str] = None) -> int:
        """Compte le nombre de chunks indexés (globalement ou pour une entreprise)."""
        if not self.client.collection_exists(self.collection_name):
            return 0

        count_filter = None
        if company_id:
            count_filter = models.Filter(
                must=[models.FieldCondition(key="company_id", match=models.MatchValue(value=company_id))]
            )
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=count_filter,
            exact=True,
        )
        return int(result.count)

    def get_stats(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        """Retourne les métriques de la collection Qdrant."""
        exists = self.client.collection_exists(self.collection_name)
        if not exists:
            return {
                "collection_name": self.collection_name,
                "exists": False,
                "total_points": 0,
                "filtered_points": 0,
                "vector_size": self.vector_size,
            }

        total_points = self.count_points(company_id=None)
        filtered_points = self.count_points(company_id=company_id) if company_id else total_points
        return {
            "collection_name": self.collection_name,
            "exists": True,
            "total_points": total_points,
            "filtered_points": filtered_points,
            "company_id_filter": company_id,
            "vector_size": self.vector_size,
        }
