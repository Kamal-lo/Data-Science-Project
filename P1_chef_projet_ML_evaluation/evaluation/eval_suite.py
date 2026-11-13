#!/usr/bin/env python3
"""
Harnais d'Ã©valuation officiel de la plateforme IA MarchÃ©s Publics Marocains.
Responsable : P1 (Chef de projet, ML prÃ©dictif et Ã©valuation)

Fournit Ã  l'ensemble de l'Ã©quipe :
- Calcul du CER (Character Error Rate) et WER pour P2 (T28)
- Exactitude par champ, Exact Match, et F1 pour P6 (T37)
- Ã‰valuation Go/No-Go pour P6 (T32)
- Ã‰valuation du contrÃ´le de conformitÃ© (Faux nÃ©gatifs) pour P4 (T57)
- VÃ©rification des garde-fous rÃ©glementaires du DÃ©cret 2-22-431 pour P4 (T54)
- Validation automatique des critÃ¨res de la Porte 1 (T05)
"""

import os
import sys
import json
import math
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eval_suite")

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # racine projet
EVAL_DIR = Path(__file__).resolve().parent                # P1/.../evaluation/
SHARED_DIR = BASE_DIR / "shared"
DATASET_DIR = SHARED_DIR / "dataset"
ANNOTATIONS_DIR = DATASET_DIR / "annotations"


# ==============================================================================
# 1. METRIQUES TEXTE : CER & WER (Pour Module B1 - P2)
# ==============================================================================

def levenshtein_distance(s1: str, s2: str) -> int:
    """Calcule la distance d'Ã©dition minimale de Levenshtein entre deux chaÃ®nes."""
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[m][n]


def calculate_cer(reference: str, hypothesis: str) -> float:
    """Calcule le Character Error Rate : CER = Levenshtein(ref, hyp) / len(ref)."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    dist = levenshtein_distance(reference, hypothesis)
    return min(1.0, dist / len(reference))


def calculate_wer(reference: str, hypothesis: str) -> float:
    """Calcule le Word Error Rate au niveau des mots."""
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    m, n = len(ref_words), len(hyp_words)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref_words[i - 1].lower() == hyp_words[j - 1].lower():
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return min(1.0, dp[m][n] / len(ref_words))


# ==============================================================================
# 2. METRIQUES D'EXTRACTION DE CHAMPS (Pour Module B2 - P6)
# ==============================================================================

def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    return str(text).strip().lower()


def evaluate_field_exact_match(predicted: Any, target: Any) -> bool:
    """Exact Match : stricte Ã©galitÃ© aprÃ¨s normalisation des types."""
    if isinstance(target, (int, float)) and isinstance(predicted, (int, float)):
        return math.isclose(float(predicted), float(target), rel_tol=1e-3, abs_tol=1.0)
    return normalize_text(predicted) == normalize_text(target)


def token_f1_score(predicted: str, target: str) -> float:
    """Calcule le F1 score basÃ© sur le recouvrement des tokens de mots."""
    pred_tokens = normalize_text(predicted).split()
    target_tokens = normalize_text(target).split()
    if not pred_tokens or not target_tokens:
        return 1.0 if pred_tokens == target_tokens else 0.0

    common = set(pred_tokens) & set(target_tokens)
    if not common:
        return 0.0

    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(target_tokens)
    return (2 * precision * recall) / (precision + recall)


def evaluate_dce_extraction(predictions: Dict[str, Any], ground_truth: Dict[str, Any]) -> Dict[str, Any]:
    """Ã‰value l'ensemble des champs extraits d'un DCE par rapport Ã  la vÃ©ritÃ© terrain."""
    results = {}
    total_fields = 0
    exact_matches = 0
    f1_sum = 0.0

    gt_fields = ground_truth.get("champs_cles_extraits", {})

    for field_name, gt_obj in gt_fields.items():
        total_fields += 1
        gt_val = gt_obj.get("valeur_normalisee")
        pred_val = predictions.get(field_name)

        is_em = evaluate_field_exact_match(pred_val, gt_val)
        if is_em:
            exact_matches += 1

        f1 = token_f1_score(str(pred_val), str(gt_val))
        f1_sum += f1

        results[field_name] = {
            "prediction": pred_val,
            "verite_terrain": gt_val,
            "exact_match": is_em,
            "token_f1": round(f1, 4)
        }

    overall_em = exact_matches / max(1, total_fields)
    overall_f1 = f1_sum / max(1, total_fields)

    return {
        "champs_evalues": results,
        "exact_match_ratio": round(overall_em, 4),
        "mean_token_f1": round(overall_f1, 4),
        "total_champs": total_fields
    }


# ==============================================================================
# 3. CONFORMITE ANTI-REJET : PIECES OBLIGATOIRES (Pour Module E - P4)
# ==============================================================================

def evaluate_compliance_checklist(dossier_fourni: List[str], pieces_exigees: List[str]) -> Dict[str, Any]:
    """
    Ã‰value l'absence de piÃ¨ces obligatoires.
    CRITERE VITAL : Le taux de faux nÃ©gatifs (piÃ¨ce manquante non signalÃ©e) DOIT Ãªtre Ã©gal Ã  0.
    """
    pieces_exigees_norm = [normalize_text(p) for p in pieces_exigees]
    fourni_norm = [normalize_text(p) for p in dossier_fourni]

    pieces_manquantes = []
    for req in pieces_exigees_norm:
        found = any(req in f or f in req for f in fourni_norm)
        if not found:
            pieces_manquantes.append(req)

    est_conforme = len(pieces_manquantes) == 0
    return {
        "conforme": est_conforme,
        "nombre_pieces_exigees": len(pieces_exigees),
        "nombre_pieces_fournies": len(dossier_fourni),
        "pieces_manquantes": pieces_manquantes,
        "taux_couverture": round(1.0 - (len(pieces_manquantes) / max(1, len(pieces_exigees))), 4)
    }


# ==============================================================================
# 4. REGLES REGLEMENTAIRES DE CHIFPAGE : DECRET 2-22-431 (Pour Module D - P4)
# ==============================================================================

def check_regulatory_price_guards(prix_propose_ttc: float, estimation_mo_ttc: float, nature_marche: str = "TRAVAUX") -> Dict[str, Any]:
    """
    VÃ©rifie les garde-fous rÃ©glementaires du DÃ©cret 2-22-431 :
    - Offre excessive : supÃ©rieure de plus de 20% Ã  l'estimation du maÃ®tre d'ouvrage.
    - Offre anormalement basse :
        * Travaux : infÃ©rieure de plus de 20% Ã  l'estimation.
        * Fournitures et Services : infÃ©rieure de plus de 25% Ã  l'estimation.
    """
    if estimation_mo_ttc <= 0:
        return {"statut": "ESTIMATION_INVALIDE", "alerte": True}

    ratio = (prix_propose_ttc - estimation_mo_ttc) / estimation_mo_ttc
    ecart_pct = round(ratio * 100.0, 2)

    seuil_basse = -0.25 if nature_marche.upper() in ["FOURNITURES", "SERVICES", "ETUDES"] else -0.20
    seuil_excessive = 0.20

    anormalement_basse = ratio < seuil_basse
    excessive = ratio > seuil_excessive

    statut = "CONFORME"
    message = "Le prix se situe dans la plage rÃ©glementaire admise."

    if anormalement_basse:
        statut = "ANORMALEMENT_BASSE"
        message = f"ALERTE REJET : Le prix proposÃ© est infÃ©rieur de {abs(ecart_pct)}% Ã  l'estimation (seuil: {seuil_basse * 100}%)."
    elif excessive:
        statut = "EXCESSIVE"
        message = f"ALERTE REJET : Le prix proposÃ© dÃ©passe l'estimation de {ecart_pct}% (seuil lÃ©gal: +20%)."

    return {
        "prix_propose_ttc": prix_propose_ttc,
        "estimation_mo_ttc": estimation_mo_ttc,
        "ecart_pourcentage": ecart_pct,
        "statut": statut,
        "alerte_rejet": anormalement_basse or excessive,
        "message_reglementaire": message
    }


# ==============================================================================
# 5. VALIDATION PORTE 1 : CORPUS ET PROTOCOLE FIGES (T05)
# ==============================================================================

def verify_gate1() -> Dict[str, Any]:
    """Valide officiellement le passage de la Porte 1 (Milestone T05)."""
    checks = []

    # 1. VÃ©rification de l'existence des annotations
    anno_files = list(ANNOTATIONS_DIR.glob("*_ground_truth.json"))
    has_5_dce = len(anno_files) >= 5
    checks.append({
        "critere": "Nombre minimal de DCE annotÃ©s (>= 5)",
        "valeur": len(anno_files),
        "succes": has_5_dce
    })

    # 2. VÃ©rification du split gelÃ©
    split_file = EVAL_DIR / "test_split.json"
    split_exists = split_file.exists()
    checks.append({
        "critere": "Jeu de test gelÃ© et split SHA-256 enregistrÃ©",
        "valeur": "PrÃ©sent" if split_exists else "Manquant",
        "succes": split_exists
    })

    # 3. SpÃ©cification formelle du protocole
    proto_file = EVAL_DIR / "protocol_specification.json"
    proto_exists = proto_file.exists()
    checks.append({
        "critere": "SpÃ©cification du protocole et mÃ©triques formelles",
        "valeur": "PrÃ©sent" if proto_exists else "Manquant",
        "succes": proto_exists
    })

    # 4. SchÃ©ma profil entreprise (T02)
    profile_schema = SHARED_DIR / "schemas" / "company_profile.schema.json"
    profile_ok = profile_schema.exists()
    checks.append({
        "critere": "SchÃ©ma profil entreprise T02 validÃ©",
        "valeur": "PrÃ©sent" if profile_ok else "Manquant",
        "succes": profile_ok
    })

    all_passed = all(c["succes"] for c in checks)
    return {
        "porte": "PORTE 1 (T05) : Corpus annotÃ© et protocole figÃ©s",
        "statut_global": "VALIDE" if all_passed else "ECHEC",
        "details_controles": checks,
        "date_validation": datetime.now().isoformat()
    }


def main():
    logger.info("=== SUITE D'EVALUATION OFFICIELLE (P1) ===")
    gate1_res = verify_gate1()
    logger.info(f"Statut Porte 1 : {gate1_res['statut_global']}")
    for c in gate1_res["details_controles"]:
        flag = "âœ…" if c["succes"] else "âŒ"
        logger.info(f" {flag} {c['critere']} : {c['valeur']}")

    # Exemple de dÃ©monstration des garde-fous de prix
    logger.info("\n--- DÃ©monstration des garde-fous DÃ©cret 2-22-431 ---")
    test_prix = check_regulatory_price_guards(prix_propose_ttc=4900000.0, estimation_mo_ttc=6500000.0, nature_marche="SERVICES")
    logger.info(f"Test Prix Services : {test_prix['statut']} (Ecart: {test_prix['ecart_pourcentage']}%) -> {test_prix['message_reglementaire']}")


if __name__ == "__main__":
    main()


