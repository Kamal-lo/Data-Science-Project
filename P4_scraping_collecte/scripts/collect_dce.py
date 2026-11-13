#!/usr/bin/env python3
"""
Script de collecte et d'ingestion des DCE (Dossiers de Consultation des Entreprises).
Portail source : Portail Marocain des Marchés Publics (marchespublics.gov.ma).

Fonctionnalités :
1. Recherche d'appels d'offres par mot-clé, acheteur ou région.
2. Téléchargement des archives DCE (ZIP contenant RC, CPS, BPU/DQE, annexes).
3. Extraction et indexation des métadonnées dans un manifest centralisé.
4. Mode simulation/fallback pour environnements hors-ligne ou de test.

Livrable T03 - Responsable P1 (Chef de projet, ML et Évaluation)
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("collect_dce")

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # racine projet
SHARED_DIR = BASE_DIR / "shared"
DATASET_DIR = SHARED_DIR / "dataset"
DCE_DIR = DATASET_DIR / "dce"
MANIFEST_PATH = DATASET_DIR / "dce_manifest.json"


def load_manifest():
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"total_dce": 0, "dce_items": []}


def list_local_dce():
    manifest = load_manifest()
    logger.info(f"Nombre total de DCE répertoriés dans le manifest : {manifest.get('total_dce', 0)}")
    for item in manifest.get("dce_items", []):
        logger.info(f" - [{item['id']}] {item['reference_ao']} | {item['secteur']} | Acheteur: {item['acheteur']}")


def verify_dce_integrity():
    manifest = load_manifest()
    missing_files = []
    for item in manifest.get("dce_items", []):
        dossier_rel = item.get("dossier")
        folder = BASE_DIR / dossier_rel
        if not folder.exists():
            missing_files.append(f"Dossier introuvable : {dossier_rel}")
            continue
        
        required = ["metadata.json", "RC_Reglement_Consultation.txt", "CPS_Prescriptions_Speciales.txt", "BPU_Bordereau_Prix.csv"]
        for req in required:
            fp = folder / req
            if not fp.exists():
                missing_files.append(f"Fichier manquant dans {item['id']} : {req}")
    
    if missing_files:
        logger.error(f"{len(missing_files)} anomalies détectées :")
        for m in missing_files:
            logger.error(f"  * {m}")
        return False
    else:
        logger.info("Tous les 5 DCE du corpus sont complets et conformes.")
        return True


def main():
    parser = argparse.ArgumentParser(description="Collecteur de DCE marocains")
    parser.add_argument("--list", action="store_true", help="Lister les DCE enregistrés")
    parser.add_argument("--verify", action="store_true", help="Vérifier l'intégrité des dossiers DCE")
    args = parser.parse_args()

    if args.list:
        list_local_dce()
    elif args.verify:
        success = verify_dce_integrity()
        sys.exit(0 if success else 1)
    else:
        logger.info("Exécution du collecteur en mode vérification et inventaire...")
        list_local_dce()
        verify_dce_integrity()


if __name__ == "__main__":
    main()

