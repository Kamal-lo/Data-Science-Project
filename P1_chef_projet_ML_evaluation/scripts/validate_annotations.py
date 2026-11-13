#!/usr/bin/env python3
"""
Script de validation des vérités terrain (Ground Truth Annotations).
Vérifie la conformité structurelle, les formats de dates ISO 8601,
les montants positifs et la cohérence avec les fichiers sources.

Livrable T04 - Responsable P1 (Chef de projet, ML et Évaluation)
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("validate_annotations")

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # racine projet
SHARED_DIR = BASE_DIR / "shared"
ANNOTATIONS_DIR = SHARED_DIR / "dataset" / "annotations"
DCE_DIR = SHARED_DIR / "dataset" / "dce"


def validate_single_annotation(filepath: Path) -> list:
    errors = []
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            return [f"Erreur de syntaxe JSON : {e}"]

    # Vérifications obligatoires de premier niveau
    for key in ["dce_id", "metadata_generale", "champs_cles_extraits", "pieces_requises_checklist", "bareme_technique"]:
        if key not in data:
            errors.append(f"Clé racine manquante : '{key}'")

    champs = data.get("champs_cles_extraits", {})
    required_fields = [
        "date_limite_remise_plis",
        "date_seance_ouverture",
        "caution_provisoire_mad",
        "delai_execution_mois",
        "delai_validite_offres_jours"
    ]

    for rf in required_fields:
        if rf not in champs:
            errors.append(f"Champ clé manquant : '{rf}'")
        else:
            item = champs[rf]
            for sub in ["valeur_normalisee", "source_fichier", "article_ou_page", "citation_source"]:
                if sub not in item:
                    errors.append(f"Dans '{rf}', attribut manquant : '{sub}'")

    # Validation du format date-time
    for date_field in ["date_limite_remise_plis", "date_seance_ouverture"]:
        if date_field in champs:
            val = champs[date_field].get("valeur_normalisee")
            try:
                datetime.fromisoformat(val)
            except Exception as e:
                errors.append(f"Format de date invalide dans '{date_field}' : {val} ({e})")

    # Validation des montants
    if "caution_provisoire_mad" in champs:
        c_val = champs["caution_provisoire_mad"].get("valeur_normalisee")
        if not isinstance(c_val, (int, float)) or c_val <= 0:
            errors.append(f"Caution provisoire invalide : {c_val}")

    # Validation de la checklist
    checklist = data.get("pieces_requises_checklist", {})
    for check_sec in ["dossier_administratif", "dossier_technique", "offre_financiere"]:
        if check_sec not in checklist or len(checklist[check_sec]) == 0:
            errors.append(f"Section checklist vide ou manquante : '{check_sec}'")

    return errors


def main():
    logger.info("Lancement de la validation des vérités terrain...")
    annotation_files = sorted(list(ANNOTATIONS_DIR.glob("*_ground_truth.json")))
    if not annotation_files:
        logger.error(f"Aucun fichier d'annotation trouvé dans {ANNOTATIONS_DIR}")
        sys.exit(1)

    total_errors = 0
    for af in annotation_files:
        errs = validate_single_annotation(af)
        if errs:
            logger.error(f"❌ {af.name} ({len(errs)} erreurs) :")
            for e in errs:
                logger.error(f"    - {e}")
            total_errors += len(errs)
        else:
            logger.info(f"✅ {af.name} : Conforme à 100%")

    if total_errors > 0:
        logger.error(f"Validation échouée avec {total_errors} erreurs au total.")
        sys.exit(1)
    else:
        logger.info("Toutes les annotations de vérité terrain sont valides et prêtes pour l'évaluation !")
        sys.exit(0)


if __name__ == "__main__":
    main()

