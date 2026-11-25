"""Construction des filtres métadonnées Qdrant avec isolation multi-tenant obligatoire (T41)."""

from __future__ import annotations

from typing import Any, Dict, List

from qdrant_client import models

from rag_module.schemas import MetadataFilter


def build_qdrant_filter(metadata_filter: MetadataFilter) -> models.Filter:
    """
    Traduit un `MetadataFilter` Pydantic en `qdrant_client.models.Filter`.

    L'isolation par `company_id` est toujours injectée en clause `must` afin qu'une
    entreprise ne puisse jamais accéder aux documents d'une autre entreprise.
    """
    must_conditions: List[models.Condition] = [
        models.FieldCondition(
            key="company_id",
            match=models.MatchValue(value=metadata_filter.company_id),
        )
    ]

    if metadata_filter.doc_types:
        must_conditions.append(
            models.FieldCondition(
                key="doc_type",
                match=models.MatchAny(any=[dt.value for dt in metadata_filter.doc_types]),
            )
        )

    if metadata_filter.sectors:
        must_conditions.append(
            models.FieldCondition(
                key="sector",
                match=models.MatchAny(any=list(metadata_filter.sectors)),
            )
        )

    if metadata_filter.language:
        must_conditions.append(
            models.FieldCondition(
                key="language",
                match=models.MatchValue(value=metadata_filter.language.value),
            )
        )

    if metadata_filter.min_year is not None or metadata_filter.max_year is not None:
        must_conditions.append(
            models.FieldCondition(
                key="year",
                range=models.Range(
                    gte=metadata_filter.min_year,
                    lte=metadata_filter.max_year,
                ),
            )
        )

    if metadata_filter.client_types:
        must_conditions.append(
            models.FieldCondition(
                key="client_type",
                match=models.MatchAny(any=[ct.value for ct in metadata_filter.client_types]),
            )
        )

    if metadata_filter.min_amount_mad is not None:
        must_conditions.append(
            models.FieldCondition(
                key="amount_mad",
                range=models.Range(gte=metadata_filter.min_amount_mad),
            )
        )

    if metadata_filter.tags_any:
        must_conditions.append(
            models.FieldCondition(
                key="tags",
                match=models.MatchAny(any=list(metadata_filter.tags_any)),
            )
        )

    if metadata_filter.doc_ids:
        must_conditions.append(
            models.FieldCondition(
                key="doc_id",
                match=models.MatchAny(any=list(metadata_filter.doc_ids)),
            )
        )

    return models.Filter(must=must_conditions)


def summarize_filter(metadata_filter: MetadataFilter) -> Dict[str, Any]:
    """Résumé lisible des filtres actifs pour la télémétrie `RetrievalTrace`."""
    summary: Dict[str, Any] = {"company_id": metadata_filter.company_id}
    if metadata_filter.doc_types:
        summary["doc_types"] = [dt.value for dt in metadata_filter.doc_types]
    if metadata_filter.sectors:
        summary["sectors"] = list(metadata_filter.sectors)
    if metadata_filter.language:
        summary["language"] = metadata_filter.language.value
    if metadata_filter.min_year is not None:
        summary["min_year"] = metadata_filter.min_year
    if metadata_filter.max_year is not None:
        summary["max_year"] = metadata_filter.max_year
    if metadata_filter.client_types:
        summary["client_types"] = [ct.value for ct in metadata_filter.client_types]
    if metadata_filter.min_amount_mad is not None:
        summary["min_amount_mad"] = metadata_filter.min_amount_mad
    if metadata_filter.tags_any:
        summary["tags_any"] = list(metadata_filter.tags_any)
    if metadata_filter.doc_ids:
        summary["doc_ids"] = list(metadata_filter.doc_ids)
    return summary
