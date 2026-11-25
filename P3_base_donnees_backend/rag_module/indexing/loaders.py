"""
Chargeurs de documents (TXT, MD, JSON, PDF, DOCX) et adaptateur `EntrepriseProfile` (T40).

Permet d'ingérer aussi bien :
1. Des fichiers bruts du corpus entreprise (mémoires gagnés, CV, fiches moyens)
2. Un profil structuré `EntrepriseProfile` (défini dans `database/company_profile_model.py`)
   en générant automatiquement des documents typés (`cv`, `moyens`, `reference`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from rag_module.schemas import (
    ClientType,
    CorpusDocType,
    CorpusDocument,
    DocumentMetadata,
    LanguageCode,
)


def detect_language_simple(text: str) -> LanguageCode:
    """Détecte de manière légère si le texte est FR, AR ou bilingue."""
    arabic_chars = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
    latin_chars = sum(1 for ch in text if ("a" <= ch.lower() <= "z") or ("\u00C0" <= ch <= "\u024F"))
    total = arabic_chars + latin_chars
    if total == 0:
        return LanguageCode.FR
    arabic_ratio = arabic_chars / total
    if arabic_ratio >= 0.70:
        return LanguageCode.AR
    if arabic_ratio >= 0.10:
        return LanguageCode.BILINGUAL
    return LanguageCode.FR


def extract_text_from_file(file_path: Path) -> str:
    """Extrait le texte d'un fichier .txt, .md, .json, .pdf ou .docx."""
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8")

    if suffix == ".json":
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        return json.dumps(raw, ensure_ascii=False, indent=2)

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ImportError("Le package 'pypdf' est requis pour lire les fichiers PDF.") from exc
        reader = PdfReader(str(file_path))
        pages: List[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                pages.append(f"## Page {idx}\n{page_text}")
        return "\n\n".join(pages)

    if suffix == ".docx":
        try:
            from docx import Document as DocxDocument
        except ImportError as exc:
            raise ImportError("Le package 'python-docx' est requis pour lire les fichiers DOCX.") from exc
        doc = DocxDocument(str(file_path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)

    raise ValueError(f"Format de fichier non supporté : {suffix}")


def load_document_from_file(
    file_path: str | Path,
    company_id: str,
    doc_type: CorpusDocType,
    doc_id: Optional[str] = None,
    title: Optional[str] = None,
    sector: Optional[str] = None,
    year: Optional[int] = None,
    client_type: Optional[ClientType] = None,
    amount_mad: Optional[float] = None,
    tags: Optional[List[str]] = None,
    language: Optional[LanguageCode] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> CorpusDocument:
    """Charge un fichier disque en `CorpusDocument` avec métadonnées complètes."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")

    content = extract_text_from_file(path)
    resolved_lang = language or detect_language_simple(content)
    resolved_doc_id = doc_id or path.stem
    resolved_title = title or path.stem.replace("_", " ").strip().title()

    metadata = DocumentMetadata(
        company_id=company_id,
        doc_id=resolved_doc_id,
        doc_type=doc_type,
        title=resolved_title,
        source_file=path.name,
        language=resolved_lang,
        sector=sector,
        year=year,
        client_type=client_type,
        amount_mad=amount_mad,
        tags=tags or [],
        extra=extra or {},
    )
    return CorpusDocument(content=content, metadata=metadata)


def company_profile_to_documents(
    profile: Dict[str, Any],
    source_file: str = "company_profile.json",
    company_id_override: Optional[str] = None,
) -> List[CorpusDocument]:
    """
    Convertit un dictionnaire conforme au schéma `EntrepriseProfile` (P3/T02)
    en une liste de `CorpusDocument` indexables dans Qdrant :
    - Fiche synthétique entreprise & qualifications (`moyens`)
    - Chaque expert clé (`cv`)
    - Parc matériel & logistique (`moyens`)
    - Chaque référence similaire (`reference`)
    """
    ident = profile.get("identification_administrative", {})
    coords = profile.get("coordonnees", {})
    qualifs = profile.get("qualifications_et_certifications", {})
    fin = profile.get("capacites_financieres", {})
    humains = profile.get("moyens_humains", {})
    materiels = profile.get("moyens_materiels", {})
    refs = profile.get("references_similaires", [])
    prefs = profile.get("preferences_veille_et_strategie", {})

    company_id = company_id_override or str(profile.get("id") or ident.get("ice") or "company-default")
    raison_sociale = ident.get("raison_sociale", "Entreprise")
    domaines = prefs.get("domaines_cibles", [])
    primary_sector = domaines[0] if domaines else None

    documents: List[CorpusDocument] = []

    # 1. Fiche entreprise, capacités financières et qualifications/certifications -> doc_type = moyens
    cert_lines: List[str] = []
    tags_company: List[str] = list(domaines)
    for cert in qualifs.get("certificats_btp", []):
        cert_lines.append(
            f"- Certificat BTP {cert.get('secteur')} ({cert.get('libelle_secteur')}), "
            f"Classe {cert.get('classe')}, catégories {', '.join(cert.get('categories', []))}, "
            f"N° {cert.get('numero_certificat')}, expire le {cert.get('date_expiration')}."
        )
        tags_company.append(f"BTP {cert.get('secteur')} Classe {cert.get('classe')}")

    for agr in qualifs.get("agrements_etudes", []):
        cert_lines.append(
            f"- Agrément Bureau d'Études {agr.get('domaine_code')} ({agr.get('domaine_libelle')}), "
            f"N° {agr.get('numero_agrement')}, expire le {agr.get('date_expiration')}."
        )
        tags_company.append(str(agr.get("domaine_code")))

    for iso in qualifs.get("certifications_normes", []):
        cert_lines.append(
            f"- Certification {iso.get('norme')} délivrée par {iso.get('organisme_certificateur')}, "
            f"N° {iso.get('numero_certificat')}, valide jusqu'au {iso.get('date_expiration')}."
        )
        tags_company.append(str(iso.get("norme")))

    bilans_lines: List[str] = []
    latest_year: Optional[int] = None
    for b in fin.get("bilans_3_derniers_exercices", []):
        yr = b.get("exercice_annee")
        if isinstance(yr, int) and (latest_year is None or yr > latest_year):
            latest_year = yr
        bilans_lines.append(
            f"- Exercice {yr} : CA global {b.get('chiffre_affaires_global_mad'):,.0f} MAD, "
            f"CA secteur {b.get('chiffre_affaires_secteur_mad'):,.0f} MAD, "
            f"Résultat net {b.get('resultat_net_mad'):,.0f} MAD."
        )

    company_overview = "\n".join(
        [
            f"# Présentation et Moyens Généraux — {raison_sociale}",
            f"Raison sociale : {raison_sociale} ({ident.get('forme_juridique', 'N/A')}).",
            f"ICE : {ident.get('ice', 'N/A')} | IF : {ident.get('identifiant_fiscal', 'N/A')} | "
            f"CNSS : {ident.get('numero_affiliation_cnss', 'N/A')}.",
            f"Siège social : {coords.get('adresse_siege', '')}, {coords.get('ville', '')} ({coords.get('region', '')}).",
            f"Capital social : {ident.get('capital_social_mad', 0):,.0f} MAD | "
            f"Statut PME : {'Oui' if ident.get('statut_pme') else 'Non'} | "
            f"Préférence nationale : {'Oui' if ident.get('eligibilite_preference_nationale') else 'Non'}.",
            "",
            "## Effectifs déclarés CNSS",
            f"Effectif total : {humains.get('effectif_total_declare_cnss', 0)} collaborateurs, dont "
            f"{humains.get('cadres_et_ingenieurs', 0)} cadres et ingénieurs, "
            f"{humains.get('techniciens_et_agents_maitrise', 0)} techniciens et "
            f"{humains.get('ouvriers_et_employes', 0)} employés/ouvriers.",
            "",
            "## Qualifications, Agréments et Certifications",
            *(cert_lines or ["- Aucune qualification déclarée."]),
            "",
            "## Capacités Financières",
            f"Chiffre d'affaires moyen 3 ans : {fin.get('chiffre_affaires_moyen_3_ans_mad', 0):,.0f} MAD.",
            *bilans_lines,
        ]
    )

    documents.append(
        CorpusDocument(
            content=company_overview,
            metadata=DocumentMetadata(
                company_id=company_id,
                doc_id=f"{company_id}::profile_overview",
                doc_type=CorpusDocType.MOYENS,
                title=f"Présentation, qualifications et capacités — {raison_sociale}",
                source_file=source_file,
                language=LanguageCode.FR,
                sector=primary_sector,
                year=latest_year,
                tags=tags_company + ["presentation", "qualifications", "capacites_financieres"],
            ),
        )
    )

    # 2. Personnel clé / Experts -> doc_type = cv
    for expert in humains.get("personnel_cle_experts", []):
        exp_id = expert.get("id", expert.get("nom_complet", "expert"))
        competences = expert.get("competences_cles", [])
        cv_text = "\n".join(
            [
                f"# CV Expert — {expert.get('nom_complet')} ({expert.get('role_titre')})",
                f"Rôle proposé : {expert.get('role_titre')}.",
                f"Formation : {expert.get('diplome')} ({expert.get('niveau_etudes')}) — {expert.get('ecole_universite')}.",
                f"Expérience totale : {expert.get('annees_experience_totale')} ans "
                f"(dont {expert.get('annees_experience_specifique')} ans d'expérience spécifique).",
                f"Compétences clés : {', '.join(competences)}.",
                "",
                "## Synthèse du parcours et missions réalisées",
                str(expert.get("resume_cv", "")),
            ]
        )
        documents.append(
            CorpusDocument(
                content=cv_text,
                metadata=DocumentMetadata(
                    company_id=company_id,
                    doc_id=f"{company_id}::cv::{exp_id}",
                    doc_type=CorpusDocType.CV,
                    title=f"CV {expert.get('nom_complet')} — {expert.get('role_titre')}",
                    source_file=source_file,
                    language=detect_language_simple(cv_text),
                    sector=primary_sector,
                    year=latest_year,
                    tags=list(competences) + [str(expert.get("role_titre", "")), "cv", "expert"],
                    extra={
                        "expert_id": exp_id,
                        "role_titre": expert.get("role_titre"),
                        "annees_experience_totale": expert.get("annees_experience_totale"),
                        "niveau_etudes": expert.get("niveau_etudes"),
                    },
                ),
            )
        )

    # 3. Parc matériel -> doc_type = moyens
    parc = materiels.get("parc_materiel", [])
    if parc:
        mat_lines = [f"# Parc Matériel et Moyens Techniques — {raison_sociale}"]
        mat_tags: List[str] = ["materiel", "logistique"]
        for item in parc:
            cat = item.get("categorie", "AUTRE")
            mat_tags.append(str(cat))
            mat_lines.append(
                f"- {item.get('designation')} | Catégorie : {cat} | Marque/Modèle : {item.get('marque_modele')} | "
                f"Année : {item.get('annee_acquisition')} | Statut : {item.get('statut_possession')} | "
                f"État : {item.get('etat_fonctionnel', 'EXCELLENT')}"
                + (
                    f" | N° série/Immat : {item.get('immatriculation_ou_numero_serie')}"
                    if item.get("immatriculation_ou_numero_serie")
                    else ""
                )
            )
        documents.append(
            CorpusDocument(
                content="\n".join(mat_lines),
                metadata=DocumentMetadata(
                    company_id=company_id,
                    doc_id=f"{company_id}::parc_materiel",
                    doc_type=CorpusDocType.MOYENS,
                    title=f"Parc matériel et équipements — {raison_sociale}",
                    source_file=source_file,
                    language=LanguageCode.FR,
                    sector=primary_sector,
                    year=latest_year,
                    tags=mat_tags,
                    extra={"equipment_count": len(parc)},
                ),
            )
        )

    # 4. Références similaires -> doc_type = reference
    for ref in refs:
        ref_id = ref.get("id", ref.get("intitule_projet", "ref"))
        raw_client_type = ref.get("client_type")
        parsed_client_type = ClientType(raw_client_type) if raw_client_type in {"PUBLIC", "SEMI_PUBLIC", "PRIVE"} else None
        mots_cles = ref.get("mots_cles_techniques", [])
        ref_text = "\n".join(
            [
                f"# Référence Similaire — {ref.get('intitule_projet')}",
                f"Maître d'ouvrage / Client : {ref.get('client_nom')} (Type : {raw_client_type}).",
                f"Numéro de marché : {ref.get('numero_marche') or 'Non communiqué'}.",
                f"Secteur / Nomenclature : {ref.get('secteur_nomenclature')}.",
                f"Montant du marché : {ref.get('montant_marche_mad', 0):,.0f} MAD "
                f"(Part réalisée : {ref.get('part_realisee_pourcentage', 100)}%).",
                f"Période d'exécution : {ref.get('annee_debut')} – {ref.get('annee_fin')}.",
                f"Attestation de bonne fin disponible : {'Oui' if ref.get('attestation_bonne_fin_disponible') else 'Non'}"
                + (f" (Signataire : {ref.get('signataire_attestation')})" if ref.get("signataire_attestation") else "")
                + ".",
                "",
                "## Description des prestations réalisées",
                str(ref.get("description_prestations", "")),
                f"Mots-clés techniques : {', '.join(mots_cles)}." if mots_cles else "",
            ]
        )
        documents.append(
            CorpusDocument(
                content=ref_text.strip(),
                metadata=DocumentMetadata(
                    company_id=company_id,
                    doc_id=f"{company_id}::ref::{ref_id}",
                    doc_type=CorpusDocType.REFERENCE,
                    title=f"Référence : {ref.get('intitule_projet')}",
                    source_file=source_file,
                    language=detect_language_simple(ref_text),
                    sector=ref.get("secteur_nomenclature") or primary_sector,
                    year=ref.get("annee_fin"),
                    client_type=parsed_client_type,
                    amount_mad=ref.get("montant_marche_mad"),
                    tags=list(mots_cles) + ["reference", "attestation_bonne_fin"],
                    extra={
                        "client_nom": ref.get("client_nom"),
                        "numero_marche": ref.get("numero_marche"),
                        "attestation_bonne_fin_disponible": ref.get("attestation_bonne_fin_disponible", True),
                    },
                ),
            )
        )

    return documents
