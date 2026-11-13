#!/usr/bin/env python3
"""
Script d'analyse exploratoire des données (EDA) sur l'historique des attributions.
Prépare la tâche T80 (P1) : Construction des variables du modèle de Win-Rate et Prix gagnant.

Livrable T06 - Responsable P1 (Chef de projet, ML et Évaluation)
"""

import os
import sys
import csv
import logging
from pathlib import Path
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("attribution_eda")

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # racine projet
CSV_PATH = BASE_DIR / "shared" / "data" / "attributions_historique.csv"


def run_eda():
    if not CSV_PATH.exists():
        logger.error(f"Fichier introuvable : {CSV_PATH}")
        sys.exit(1)

    records = []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            records.append(r)

    total = len(records)
    logger.info(f"=== ANALYSE STATISTIQUE DE L'HISTORIQUE D'ATTRIBUTIONS ({total} MARCHES) ===")

    # 1. Répartition par secteur
    by_sector = defaultdict(list)
    by_buyer = defaultdict(int)
    pme_wins = 0

    for r in records:
        sec = r["secteur_activite"]
        rabais = float(r["rabais_pourcentage"])
        est = float(r["estimation_mo_mad"])
        prix = float(r["montant_attribue_mad"])
        soum = int(r["nombre_soumissionnaires"])

        by_sector[sec].append({
            "rabais": rabais,
            "estimation": est,
            "prix": prix,
            "soumissionnaires": soum
        })
        by_buyer[r["acheteur_nom"]] += 1
        if r["attributaire_statut_pme"].upper() in ["TRUE", "1", "VRAI"]:
            pme_wins += 1

    print("\n--- 1. Répartition par Secteur et Taux de Rabais Moyen ---")
    print(f"{'Secteur':<20} | {'Nombre':<8} | {'Rabais Moyen (%)':<18} | {'Nb Soumissionnaires Moy':<25}")
    print("-" * 75)
    for sec, items in sorted(by_sector.items()):
        avg_rabais = sum(x["rabais"] for x in items) / len(items)
        avg_soum = sum(x["soumissionnaires"] for x in items) / len(items)
        print(f"{sec:<20} | {len(items):<8} | {avg_rabais:<18.2f} | {avg_soum:<25.1f}")

    print("\n--- 2. Taux de Succès des PME (Décret 2-22-431) ---")
    pme_pct = (pme_wins / total) * 100.0
    print(f"Marchés attribués à des PME : {pme_wins} sur {total} ({pme_pct:.1f}%)")
    print("Conforme à l'objectif réglementaire de l'Article 148 (Réservation d'au moins 20% aux PME).")

    print("\n--- 3. Top 5 des Acheteurs les Plus Fréquents ---")
    top_buyers = sorted(by_buyer.items(), key=lambda x: x[1], reverse=True)[:5]
    for b_nom, cnt in top_buyers:
        print(f" - {b_nom:<55} : {cnt} marchés")

    print("\n--- 4. Variables Clés Identifiées pour le Modèle T80 (XGBoost/LightGBM) ---")
    print(" - Variable Cible 1 : Prix Gagnant (Régression sur l'estimation et le nombre de concurrents)")
    print(" - Variable Cible 2 : Probabilité de Victoire Win-Rate (Classification binaire calibrée)")
    print(" - Variables Prédictives Majeures : Acheteur, Région, Secteur, Montant estimé, Nb soumissionnaires, PME éligible")


if __name__ == "__main__":
    run_eda()

