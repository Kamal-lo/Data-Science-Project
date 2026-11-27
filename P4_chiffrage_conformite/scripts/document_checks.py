import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from reglementation import charger_parametres

# NOTE : en attendant T25 (OCR sur pieces scannees), les dates/montants des
# pieces soumises par le candidat sont ici simulees. En production, ces
# valeurs viendront de l'extraction OCR + LLM (T30/T31).


def controler_caution(caution_requise_mad, caution_fournie_mad, estimation_mad):
    """Verifie que la caution fournie par le candidat couvre bien la caution
    exigee par le CPS, et que la caution exigee ne depasse pas le plafond
    legal de l'article 24 (T14/T50)."""
    params = charger_parametres()["parameters"]
    plafond_pct = params["caution_provisoire_plafond_pct"]
    plafond_mad = estimation_mad * plafond_pct / 100

    anomalies = []

    if caution_requise_mad > plafond_mad:
        anomalies.append(
            f"La caution exigee ({caution_requise_mad:,.0f} MAD) depasse le plafond "
            f"legal de {plafond_pct}% de l'estimation ({plafond_mad:,.0f} MAD) - a signaler"
        )

    if caution_fournie_mad < caution_requise_mad:
        anomalies.append(
            f"Caution fournie ({caution_fournie_mad:,.0f} MAD) insuffisante : "
            f"il manque {caution_requise_mad - caution_fournie_mad:,.0f} MAD"
        )

    return {
        "conforme": len(anomalies) == 0,
        "caution_requise_mad": caution_requise_mad,
        "caution_fournie_mad": caution_fournie_mad,
        "anomalies": anomalies,
    }


def controler_validite_attestation(nom_piece, date_delivrance, date_limite_depot):
    """Verifie qu'une attestation (fiscale, CNSS...) est bien delivree depuis
    moins de 1 an par rapport a la date de depot (article 28)."""
    params = charger_parametres()["parameters"]
    validite_jours = params["validite_attestation_fiscale_jours"]

    age_jours = (date_limite_depot - date_delivrance).days
    conforme = 0 <= age_jours <= validite_jours

    if age_jours < 0:
        message = f"{nom_piece} : date de delivrance posterieure a la date de depot (incoherent)"
    elif age_jours > validite_jours:
        message = (
            f"{nom_piece} : perimee - delivree il y a {age_jours} jours "
            f"(limite : {validite_jours} jours)"
        )
    else:
        message = f"{nom_piece} : valide (delivree il y a {age_jours} jours)"

    return {"conforme": conforme, "message": message}


if __name__ == "__main__":
    # Cas 1 : caution insuffisante (DCE-2024-002, caution exigee = 410 000 MAD)
    resultat_caution = controler_caution(
        caution_requise_mad=410_000,
        caution_fournie_mad=350_000,
        estimation_mad=27_700_000,
    )
    print("Controle de la caution :")
    print(" Conforme :", resultat_caution["conforme"])
    for a in resultat_caution["anomalies"]:
        print(" -", a)

    print()

    # Cas 2 : attestations fiscale/CNSS, dont une perimee
    date_depot = date(2024, 10, 8)
    attestations = [
        ("Attestation fiscale", date(2024, 3, 1)),
        ("Attestation CNSS", date(2023, 5, 15)),  # plus de 1 an -> perimee
    ]
    print("Controle de validite des attestations :")
    for nom, date_delivrance in attestations:
        r = controler_validite_attestation(nom, date_delivrance, date_depot)
        print(f" [{'OK' if r['conforme'] else 'KO'}] {r['message']}")
