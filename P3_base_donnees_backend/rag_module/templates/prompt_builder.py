"""
Constructeur de prompts ancrés dans les sources (T42) reliant les gabarits 6 sections au pipeline RAG (T41).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from rag_module.retrieval.pipeline import RAGRetrievalPipeline
from rag_module.schemas import (
    BuildPromptRequest,
    DCEContext,
    LanguageCode,
    MetadataFilter,
    PromptSourceItem,
    RenderedSectionPrompt,
    RetrievalRequest,
    RetrievalResponse,
    RetrievedChunk,
    SectionId,
)
from rag_module.templates.sections import get_section_template


class PromptBuilder:
    """Assemble des prompts `system` + `user` rigoureusement ancrés sur les sources T41."""

    def __init__(self, max_context_chars: int = 12000) -> None:
        self.max_context_chars = max_context_chars

    @staticmethod
    def build_retrieval_query(section_id: SectionId, dce_context: DCEContext) -> str:
        """Génère une requête RAG ciblée à partir du gabarit de section et du contexte DCE."""
        template = get_section_template(section_id)
        exigences_resume = (
            " ; ".join(dce_context.exigences_techniques[:5])
            if dce_context.exigences_techniques
            else dce_context.titre_marche_fr
        )
        return template.retrieval_query_template.format(
            acheteur=dce_context.acheteur,
            titre_marche_fr=dce_context.titre_marche_fr,
            type_prestation=dce_context.type_prestation,
            exigences_resume=exigences_resume,
        )

    @staticmethod
    def _language_directive(language: LanguageCode) -> str:
        if language == LanguageCode.AR:
            return (
                "Langue de rédaction : Arabe administratif et technique formel adapté aux marchés publics marocains "
                "(avec maintien des sigles officiels tels que ISO, DNSSI, BPU, CPS si présents dans les sources)."
            )
        if language == LanguageCode.BILINGUAL:
            return (
                "Langue de rédaction : Français principal avec titres de section bilingues Français / Arabe "
                "et résumé exécutif en arabe à la fin de la section."
            )
        return "Langue de rédaction : Français professionnel, formel et précis, conforme aux usages des marchés publics marocains."

    @staticmethod
    def _format_dce_block(dce: DCEContext) -> str:
        lines = [
            f"- Identifiant DCE : {dce.dce_id}",
            f"- Référence AO : {dce.reference_ao}",
            f"- Maître d'Ouvrage (Acheteur) : {dce.acheteur}",
            f"- Objet du marché (FR) : {dce.titre_marche_fr}",
        ]
        if dce.titre_marche_ar:
            lines.append(f"- Objet du marché (AR) : {dce.titre_marche_ar}")
        lines.append(f"- Type de prestation : {dce.type_prestation}")
        if dce.delai_execution_mois is not None:
            lines.append(f"- Délai d'exécution contractuel : {dce.delai_execution_mois} mois")
        if dce.estimation_mad is not None:
            lines.append(f"- Estimation du Maître d'Ouvrage : {dce.estimation_mad:,.2f} MAD TTC")

        if dce.contraintes_reglementaires:
            lines.append("- Cadre réglementaire applicable :")
            for rule in dce.contraintes_reglementaires:
                lines.append(f"  * {rule}")

        if dce.exigences_techniques:
            lines.append("- Exigences techniques & administratives extraites du DCE :")
            for idx, ex in enumerate(dce.exigences_techniques, start=1):
                lines.append(f"  {idx}. {ex}")

        if dce.bareme_criteres:
            lines.append("- Barème d'évaluation technique :")
            for crit in dce.bareme_criteres:
                lines.append(f"  * {crit.get('critere', 'Critère')} : {crit.get('points_max', 'N/A')} points")

        return "\n".join(lines)

    def render_section_prompt(
        self,
        section_id: SectionId,
        dce_context: DCEContext,
        retrieved_chunks: Sequence[RetrievedChunk],
        company_name: Optional[str] = None,
        language: LanguageCode = LanguageCode.FR,
        retrieval_query: Optional[str] = None,
    ) -> RenderedSectionPrompt:
        """Construit les prompts `system` et `user` ainsi que le registre des sources [SRC-i]."""
        template = get_section_template(section_id)
        query_used = retrieval_query or self.build_retrieval_query(section_id, dce_context)

        # Assemblage des sources dans le budget de caractères
        sources: List[PromptSourceItem] = []
        source_blocks: List[str] = []
        used_chars = 0

        for idx, chunk in enumerate(retrieved_chunks, start=1):
            citation_id = f"SRC-{idx}"
            block = (
                f"[{citation_id}] Type: {chunk.doc_type.value} | Titre: {chunk.title} | "
                f"Fichier: {chunk.source_file} | Section/Page: {chunk.page_or_section} | "
                f"Score: {chunk.rerank_score:.4f}\n"
                f"{chunk.text.strip()}"
            )
            if used_chars + len(block) > self.max_context_chars and source_blocks:
                break
            source_blocks.append(block)
            used_chars += len(block)
            sources.append(
                PromptSourceItem(
                    citation_id=citation_id,
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    doc_type=chunk.doc_type,
                    source_file=chunk.source_file,
                    page_or_section=chunk.page_or_section,
                    rerank_score=chunk.rerank_score,
                    excerpt=chunk.text.strip()[:300],
                )
            )

        # Détection d'alertes qualité/couverture avant génération
        warnings: List[str] = []
        if not sources:
            warnings.append(
                "Aucune source entreprise n'a été récupérée pour cette section : la rédaction devra "
                "marquer [DONNÉE MANQUANTE À COMPLÉTER PAR L'ENTREPRISE] pour chaque fait entreprise."
            )
        else:
            retrieved_types = {s.doc_type for s in sources}
            preferred_set = set(template.preferred_doc_types)
            if not retrieved_types.intersection(preferred_set):
                expected_str = ", ".join(dt.value for dt in template.preferred_doc_types)
                warnings.append(
                    f"Aucun document des types prioritaires ({expected_str}) n'a été retrouvé pour {section_id.value}."
                )

        # System Prompt
        rules_formatted = "\n".join(f"- {r}" for r in template.anti_hallucination_rules)
        system_prompt = "\n\n".join(
            [
                (
                    "Vous êtes un expert senior en rédaction de mémoires techniques pour les appels d'offres "
                    "publics au Maroc (Décret n° 2-22-431). Votre mission est de rédiger une section rigoureuse, "
                    "convaincante et 100 % vérifiable à partir des seules preuves fournies."
                ),
                self._language_directive(language),
                f"RÈGLES STRICTES ANTI-HALLUCINATION :\n{rules_formatted}",
                template.output_format_instructions,
            ]
        )

        # User Prompt
        subsections_formatted = "\n".join(
            f"- **{sub.code} {sub.title}** : {sub.guidance}" for sub in template.required_subsections
        )
        sources_formatted = (
            "\n\n---\n\n".join(source_blocks)
            if source_blocks
            else "[AUCUNE SOURCE ENTREPRISE DISPONIBLE DANS QDRANT POUR CETTE SECTION]"
        )

        min_words, max_words = template.expected_word_count_range
        company_line = f"Soumissionnaire : {company_name}" if company_name else "Soumissionnaire : (voir sources entreprise ci-dessous)"

        user_prompt = "\n\n".join(
            [
                f"### SECTION À RÉDIGER\n- Titre (FR) : {template.title_fr}\n- Titre (AR) : {template.title_ar}\n- Objectif : {template.objective}\n- Volume cible indicatif : {min_words} à {max_words} mots.\n- {company_line}",
                f"### STRUCTURE OBLIGATOIRE DES SOUS-SECTIONS\n{subsections_formatted}",
                f"### CONTEXTE ET EXIGENCES DU DCE\n{self._format_dce_block(dce_context)}",
                f"### SOURCES VÉRIFIÉES DU CORPUS ENTREPRISE (QDRANT)\n{sources_formatted}",
                "### CONSIGNE FINALE\nRédigez maintenant cette section en citant [SRC-i] pour chaque fait entreprise et en signalant toute donnée absente via [DONNÉE MANQUANTE À COMPLÉTER PAR L'ENTREPRISE].",
            ]
        )

        return RenderedSectionPrompt(
            section_id=template.section_id,
            section_order=template.order,
            section_title_fr=template.title_fr,
            section_title_ar=template.title_ar,
            language=language,
            retrieval_query=query_used,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            sources=sources,
            warnings=warnings,
            estimated_prompt_chars=len(system_prompt) + len(user_prompt),
        )

    def retrieve_and_build_prompt(
        self,
        pipeline: RAGRetrievalPipeline,
        section_id: SectionId,
        request: BuildPromptRequest,
    ) -> Tuple[RenderedSectionPrompt, RetrievalResponse]:
        """Exécute T41 (retrieval + reranking) puis T42 (rendu du prompt) pour une section."""
        template = get_section_template(section_id)
        retrieval_query = self.build_retrieval_query(section_id, request.dce_context)

        metadata_filter = MetadataFilter(
            company_id=request.company_id,
            doc_types=template.preferred_doc_types if request.strict_doc_type_filter else None,
            sectors=[request.sector_filter] if request.sector_filter else None,
            min_year=request.min_year,
        )

        retrieval_response = pipeline.retrieve(
            RetrievalRequest(
                query=retrieval_query,
                filters=metadata_filter,
                initial_top_k=max(20, request.top_k * 3),
                final_top_k=request.top_k,
                enable_reranking=True,
                preferred_doc_types=template.preferred_doc_types,
            )
        )

        rendered = self.render_section_prompt(
            section_id=section_id,
            dce_context=request.dce_context,
            retrieved_chunks=retrieval_response.results,
            company_name=request.company_name,
            language=request.language,
            retrieval_query=retrieval_query,
        )
        return rendered, retrieval_response
