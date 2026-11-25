"""
Gabarits officiels des 6 sections du mémoire technique pour marchés publics marocains (T42).

Alignés sur le Décret n° 2-22-431, les critères usuels du barème technique (`bareme_technique`)
et les principes anti-hallucination du Module C (traçabilité [SRC-i], zéro invention).
"""

from __future__ import annotations

from typing import Dict, List

from rag_module.schemas import CorpusDocType, SectionId, SectionTemplate, SubsectionSpec

COMMON_ANTI_HALLUCINATION_RULES: List[str] = [
    "Appuyez-vous EXCLUSIVEMENT sur le contexte DCE et les sources entreprise fournies ([SRC-1] à [SRC-N]).",
    "N'inventez AUCUN chiffre, nom d'expert, diplôme, numéro de marché, certificat, date ou matériel absent des sources.",
    "Citez explicitement la source de chaque affirmation factuelle juste après la phrase au format [SRC-i].",
    "Si une exigence du DCE n'est couverte par aucune source entreprise, écrivez littéralement : [DONNÉE MANQUANTE À COMPLÉTER PAR L'ENTREPRISE] et listez-la dans le bloc des lacunes.",
    "Respectez la terminologie officielle des marchés publics marocains (Décret n° 2-22-431, Maître d'Ouvrage, CPS, RC, réception provisoire/définitive).",
]

COMMON_OUTPUT_CONTRACT = """Format de sortie attendu :
1. Rédigez la section en Markdown structuré en respectant strictement la numérotation des sous-sections demandées.
2. Intégrez des tableaux Markdown lorsque cela clarifie les livrables, l'équipe, le matériel, le planning ou les références.
3. Insérez les citations [SRC-i] à la fin de chaque fait vérifiable.
4. Terminez OBLIGATOIREMENT par un bloc synthétique intitulé `### Traçabilité et Points à Compléter` contenant :
   - La liste des exigences du DCE couvertes dans cette section avec leurs citations [SRC-i] ;
   - La liste des éventuelles lacunes marquées `[DONNÉE MANQUANTE À COMPLÉTER PAR L'ENTREPRISE]` (ou « Aucune lacune détectée »)."""


SECTION_TEMPLATES: Dict[SectionId, SectionTemplate] = {
    SectionId.PRESENTATION_ENTREPRISE: SectionTemplate(
        section_id=SectionId.PRESENTATION_ENTREPRISE,
        order=1,
        title_fr="1. Présentation de l'entreprise, organisation et gouvernance",
        title_ar="1. تقديم المقاولة والتنظيم والحكامة",
        objective=(
            "Présenter la légitimité juridique, financière et technique du soumissionnaire, ses qualifications, "
            "agréments et certifications (ISO, BTP, Bureau d'Études), ainsi que le dispositif de gouvernance "
            "proposé vis-à-vis du Maître d'Ouvrage."
        ),
        preferred_doc_types=[CorpusDocType.MOYENS, CorpusDocType.REFERENCE, CorpusDocType.MEMOIRE_GAGNE],
        required_subsections=[
            SubsectionSpec(
                code="1.1",
                title="Identité, statut juridique et positionnement",
                guidance="Raison sociale, forme juridique, siège, statut PME / préférence nationale, domaines d'expertise.",
            ),
            SubsectionSpec(
                code="1.2",
                title="Qualifications, agréments et certifications",
                guidance="Rappeler uniquement les certificats BTP, agréments d'études et normes ISO attestés dans le corpus.",
            ),
            SubsectionSpec(
                code="1.3",
                title="Capacités financières et structure organisationnelle",
                guidance="Synthèse des effectifs CNSS, chiffres d'affaires vérifiés et gouvernance projet (comité de pilotage, interlocuteur unique).",
            ),
        ],
        retrieval_query_template=(
            "Présentation entreprise raison sociale qualifications agréments certifications ISO BTP "
            "capacités financières effectif CNSS gouvernance pour {titre_marche_fr} ({type_prestation}) "
            "exigences : {exigences_resume}"
        ),
        expected_word_count_range=(350, 650),
        anti_hallucination_rules=COMMON_ANTI_HALLUCINATION_RULES
        + [
            "Vérifiez que les numéros d'agrément, classes BTP, dates d'expiration et chiffres d'affaires correspondent mot pour mot aux sources.",
        ],
        output_format_instructions=COMMON_OUTPUT_CONTRACT,
    ),
    SectionId.COMPREHENSION_ENJEUX: SectionTemplate(
        section_id=SectionId.COMPREHENSION_ENJEUX,
        order=2,
        title_fr="2. Compréhension du besoin, contexte et analyse des exigences du DCE",
        title_ar="2. فهم الحاجيات والسياق وتحليل متطلبات ملف طلب العروض",
        objective=(
            "Démontrer une maîtrise fine du contexte institutionnel du Maître d'Ouvrage, reformuler les objectifs "
            "du marché, cartographier les exigences critiques du CPS/RC et anticiper les contraintes réglementaires et opérationnelles."
        ),
        preferred_doc_types=[CorpusDocType.MEMOIRE_GAGNE, CorpusDocType.REFERENCE],
        required_subsections=[
            SubsectionSpec(
                code="2.1",
                title="Contexte institutionnel et enjeux du Maître d'Ouvrage",
                guidance="Contextualiser les objectifs stratégiques et opérationnels du marché sans paraphraser mécaniquement le CPS.",
            ),
            SubsectionSpec(
                code="2.2",
                title="Analyse des exigences clés et matrice de conformité",
                guidance="Tableau reliant chaque exigence technique/réglementaire du DCE à la réponse concrète apportée par l'entreprise.",
            ),
            SubsectionSpec(
                code="2.3",
                title="Facteurs clés de succès et contraintes identifiées",
                guidance="Identifier les contraintes de délai, sécurité, continuité de service ou conformité légale (Décret 2-22-431, Loi 09-08, DNSSI, CCAG).",
            ),
        ],
        retrieval_query_template=(
            "Compréhension besoin enjeux analyse exigences contraintes réglementaires et retour d'expérience "
            "pour {acheteur} — {titre_marche_fr} ({type_prestation}) : {exigences_resume}"
        ),
        expected_word_count_range=(450, 800),
        anti_hallucination_rules=COMMON_ANTI_HALLUCINATION_RULES
        + [
            "Distinguez clairement les exigences issues du DCE (données d'entrée) des acquis issus du corpus entreprise ([SRC-i]).",
        ],
        output_format_instructions=COMMON_OUTPUT_CONTRACT,
    ),
    SectionId.METHODOLOGIE_TECHNIQUE: SectionTemplate(
        section_id=SectionId.METHODOLOGIE_TECHNIQUE,
        order=3,
        title_fr="3. Méthodologie d'exécution, démarche technique et architecture de la solution",
        title_ar="3. منهجية التنفيذ والمقاربة التقنية وهندسة الحل",
        objective=(
            "Détailler la démarche opérationnelle phase par phase, l'architecture technique ou procédés d'exécution, "
            "les livrables attendus, les modalités de recette/validation et le transfert de compétences."
        ),
        preferred_doc_types=[CorpusDocType.MEMOIRE_GAGNE, CorpusDocType.MOYENS, CorpusDocType.REFERENCE],
        required_subsections=[
            SubsectionSpec(
                code="3.1",
                title="Approche méthodologique globale et phasage d'exécution",
                guidance="Découper l'exécution en phases cohérentes avec le CPS (cadrage, conception/déploiement, recette, mise en service, garantie).",
            ),
            SubsectionSpec(
                code="3.2",
                title="Architecture technique, normes et standards retenus",
                guidance="Décrire les choix techniques éprouvés issus des mémoires gagnés et des moyens de l'entreprise.",
            ),
            SubsectionSpec(
                code="3.3",
                title="Livrables, protocoles de recette et transfert de compétences",
                guidance="Tableau des livrables par phase, critères d'acceptation, formation et support/garantie post-réception.",
            ),
        ],
        retrieval_query_template=(
            "Méthodologie exécution phasage architecture technique livrables recette transfert compétences "
            "garantie support pour {titre_marche_fr} ({type_prestation}) : {exigences_resume}"
        ),
        expected_word_count_range=(650, 1200),
        anti_hallucination_rules=COMMON_ANTI_HALLUCINATION_RULES
        + [
            "Ne promettez aucun SLA, outil logiciel ou composant d'architecture qui ne figure pas dans le DCE ou les sources [SRC-i].",
        ],
        output_format_instructions=COMMON_OUTPUT_CONTRACT,
    ),
    SectionId.MOYENS_HUMAINS: SectionTemplate(
        section_id=SectionId.MOYENS_HUMAINS,
        order=4,
        title_fr="4. Moyens humains, équipe dédiée et qualifications des experts",
        title_ar="4. الموارد البشرية والفريق المخصص وكفاءات الخبراء",
        objective=(
            "Présenter l'organigramme de l'équipe projet dédiée, les profils, diplômes, années d'expérience et "
            "compétences vérifiées de chaque expert clé, ainsi que la répartition des responsabilités (RACI) et le plan de continuité."
        ),
        preferred_doc_types=[CorpusDocType.CV, CorpusDocType.MOYENS],
        required_subsections=[
            SubsectionSpec(
                code="4.1",
                title="Organigramme projet et gouvernance de l'équipe dédiée",
                guidance="Décrire la structuration de l'équipe (Directeur de projet, Chef de projet, Experts métier/techniques) et les interfaces avec le Maître d'Ouvrage.",
            ),
            SubsectionSpec(
                code="4.2",
                title="Tableau synthétique des profils et qualifications clés",
                guidance="Tableau (Nom, Rôle, Diplôme, Expérience totale/spécifique, Compétences clés, Source [SRC-i]) strictement fidèle aux CVs.",
            ),
            SubsectionSpec(
                code="4.3",
                title="Fiches synthétiques des experts, matrice RACI et continuité",
                guidance="Mettre en évidence les expériences similaires vérifiées de chaque expert et les modalités de remplacement à compétence équivalente.",
            ),
        ],
        retrieval_query_template=(
            "CV personnel clé experts équipe dédiée diplôme années expérience compétences chef de projet "
            "architecte ingénieur pour {titre_marche_fr} ({type_prestation}) : {exigences_resume}"
        ),
        expected_word_count_range=(500, 950),
        anti_hallucination_rules=COMMON_ANTI_HALLUCINATION_RULES
        + [
            "N'inventez JAMAIS un nom d'expert, un diplôme, une école ou un nombre d'années d'expérience.",
            "Si un profil exigé par le DCE n'a pas de CV correspondant dans les sources, indiquez explicitement [DONNÉE MANQUANTE À COMPLÉTER PAR L'ENTREPRISE].",
        ],
        output_format_instructions=COMMON_OUTPUT_CONTRACT,
    ),
    SectionId.MOYENS_MATERIELS_QUALITE: SectionTemplate(
        section_id=SectionId.MOYENS_MATERIELS_QUALITE,
        order=5,
        title_fr="5. Moyens matériels, logistiques, démarche qualité, sécurité et HSE",
        title_ar="5. الوسائل المادية واللوجستية ومنهجية الجودة والأمن والسلامة",
        objective=(
            "Détailler le parc matériel, logiciel et logistique mobilisé pour le marché ainsi que le plan "
            "d'assurance qualité (PAQ), les mesures de sécurité SI / protection des données (DNSSI, Loi 09-08) ou HSE."
        ),
        preferred_doc_types=[CorpusDocType.MOYENS, CorpusDocType.MEMOIRE_GAGNE],
        required_subsections=[
            SubsectionSpec(
                code="5.1",
                title="Parc matériel, équipements techniques et licences mobilisés",
                guidance="Tableau des équipements issus du corpus (Désignation, Marque/Modèle, Statut de possession, État, Source [SRC-i]).",
            ),
            SubsectionSpec(
                code="5.2",
                title="Plan d'Assurance Qualité (PAQ) et contrôle interne",
                guidance="Processus qualité, revues de livrables, indicateurs de suivi, conformité ISO si attestée dans les sources.",
            ),
            SubsectionSpec(
                code="5.3",
                title="Sécurité, confidentialité (Loi 09-08 / DNSSI) et dispositif HSE",
                guidance="Mesures de sécurité de l'information, confidentialité des données publiques ou plan Hygiène-Sécurité-Environnement selon la nature du marché.",
            ),
        ],
        retrieval_query_template=(
            "Parc matériel équipements licences logiciels logistique plan assurance qualité PAQ ISO "
            "sécurité DNSSI Loi 09-08 HSE pour {titre_marche_fr} ({type_prestation}) : {exigences_resume}"
        ),
        expected_word_count_range=(450, 850),
        anti_hallucination_rules=COMMON_ANTI_HALLUCINATION_RULES
        + [
            "Ne listez que les équipements, numéros de série, licences et certifications explicitement présents dans les sources [SRC-i].",
        ],
        output_format_instructions=COMMON_OUTPUT_CONTRACT,
    ),
    SectionId.PLANNING_REFERENCES: SectionTemplate(
        section_id=SectionId.PLANNING_REFERENCES,
        order=6,
        title_fr="6. Planning prévisionnel, gestion des risques et références similaires",
        title_ar="6. الجدول الزمني التوقعي وتدبير المخاطر والمراجع المماثلة",
        objective=(
            "Présenter un calendrier d'exécution réaliste respectant impérativement le délai contractuel du CPS, "
            "une matrice de gestion des risques opérationnels, et les références similaires vérifiées appuyées d'attestations de bonne fin."
        ),
        preferred_doc_types=[CorpusDocType.REFERENCE, CorpusDocType.MEMOIRE_GAGNE],
        required_subsections=[
            SubsectionSpec(
                code="6.1",
                title="Planning prévisionnel jalonné et respect du délai contractuel",
                guidance="Tableau des jalons et durées strictement cohérent avec `delai_execution_mois` indiqué dans le DCE.",
            ),
            SubsectionSpec(
                code="6.2",
                title="Analyse des risques et plan de mitigation",
                guidance="Tableau (Risque, Probabilité/Impact, Mesure préventive, Plan de contingence) ancré sur le retour d'expérience du corpus.",
            ),
            SubsectionSpec(
                code="6.3",
                title="Références similaires vérifiées et attestations de bonne fin",
                guidance="Tableau des marchés similaires (Client, N° Marché, Objet, Montant MAD, Période, Attestation bonne fin, Source [SRC-i]).",
            ),
        ],
        retrieval_query_template=(
            "Références similaires attestations bonne fin montants marchés publics planning jalons délai "
            "gestion des risques pour {titre_marche_fr} ({type_prestation}) : {exigences_resume}"
        ),
        expected_word_count_range=(500, 950),
        anti_hallucination_rules=COMMON_ANTI_HALLUCINATION_RULES
        + [
            "Vérifiez que la somme des durées des phases du planning ne dépasse jamais le délai contractuel du DCE.",
            "N'inventez aucune référence client, montant en MAD, numéro de marché ou attestation de bonne fin.",
        ],
        output_format_instructions=COMMON_OUTPUT_CONTRACT,
    ),
}


def get_section_template(section_id: SectionId) -> SectionTemplate:
    """Retourne le gabarit d'une des 6 sections."""
    if section_id not in SECTION_TEMPLATES:
        raise KeyError(f"Section inconnue : {section_id}")
    return SECTION_TEMPLATES[section_id]


def get_all_section_templates() -> List[SectionTemplate]:
    """Retourne les 6 gabarits ordonnés de 1 à 6."""
    return sorted(SECTION_TEMPLATES.values(), key=lambda tpl: tpl.order)
