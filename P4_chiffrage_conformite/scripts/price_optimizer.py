import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from reglementation import charger_parametres
from prix_reference_model import calculer_prix_reference


def seuil_anormalement_basse_pct(type_prestation, params):
    """Renvoie le seuil applicable, ou None si aucun seuil ne s'applique
    (cas des etudes, cf. article 44 et T14)."""
    tp = type_prestation.upper()
    if tp == "ETUDES":
        return None
    if tp == "TRAVAUX":
        return params["parameters"]["seuil_anormalement_basse_travaux_pct"]
    return params["parameters"]["seuil_anormalement_basse_fournitures_services_pct"]


def simuler_scenarios(estimation_mad, type_prestation, region, secteur_activite, pas_pct=2, marge_securite_pct=3):
    """Genere des scenarios de prix (par palier de rabais) et les classe par zone de risque
    selon les seuils du decret 2-22-431 (T14/T50)."""
    params = charger_parametres()
    seuil_bas = seuil_anormalement_basse_pct(type_prestation, params)
    seuil_excessif = params["parameters"]["seuil_offre_excessive_pct"]

    prix_ref, rabais_marche = calculer_prix_reference(estimation_mad, region, secteur_activite)

    if seuil_bas is None:
        # Etudes : aucun seuil d'offre anormalement basse (article 44 / T14).
        # On genere quand meme des scenarios indicatifs, sans zone de rejet.
        rabais_max_affiche = 30
        scenarios = []
        rabais = 0
        while rabais <= rabais_max_affiche:
            prix = estimation_mad * (1 - rabais / 100)
            scenarios.append({
                "rabais_pct": rabais,
                "prix_offre_mad": round(prix, 2),
                "zone": "SUR (pas de seuil - etudes, note technico-financiere art. 144)",
            })
            rabais += pas_pct

        return {
            "estimation_mad": estimation_mad,
            "type_prestation": type_prestation,
            "seuil_anormalement_basse_pct": None,
            "seuil_offre_excessive_pct": None,
            "rabais_marche_estime_pct": round(rabais_marche, 2),
            "prix_reference_marche_mad": round(prix_ref, 2),
            "scenarios": scenarios,
            "scenario_recommande": scenarios[-1],
        }

    scenarios = []
    rabais = 0
    while rabais <= seuil_bas + 10:
        prix = estimation_mad * (1 - rabais / 100)
        if rabais >= seuil_bas:
            zone = "REJETE (anormalement basse)"
        elif rabais >= seuil_bas - marge_securite_pct:
            zone = "RISQUE (proche du seuil)"
        else:
            zone = "SUR"
        scenarios.append({
            "rabais_pct": rabais,
            "prix_offre_mad": round(prix, 2),
            "zone": zone,
        })
        rabais += pas_pct

    candidats_surs = [s for s in scenarios if s["zone"] == "SUR"]
    meilleur = max(candidats_surs, key=lambda s: s["rabais_pct"]) if candidats_surs else None

    return {
        "estimation_mad": estimation_mad,
        "type_prestation": type_prestation,
        "seuil_anormalement_basse_pct": seuil_bas,
        "seuil_offre_excessive_pct": seuil_excessif,
        "rabais_marche_estime_pct": round(rabais_marche, 2),
        "prix_reference_marche_mad": round(prix_ref, 2),
        "scenarios": scenarios,
        "scenario_recommande": meilleur,
    }


if __name__ == "__main__":
    resultat = simuler_scenarios(
        estimation_mad=27_700_000,
        type_prestation="TRAVAUX",
        region="Casablanca-Settat",
        secteur_activite="BTP",
    )

    print(f"Estimation : {resultat['estimation_mad']:,.0f} MAD")
    print(f"Type de marche : {resultat['type_prestation']}")
    print(f"Seuil anormalement bas : {resultat['seuil_anormalement_basse_pct']}%")
    print(f"Rabais moyen observe sur le marche (region/secteur) : {resultat['rabais_marche_estime_pct']}%")
    print(f"Prix de reference historique estime : {resultat['prix_reference_marche_mad']:,.0f} MAD")
    print()
    print("Scenarios :")
    for s in resultat["scenarios"]:
        print(f"  Rabais {s['rabais_pct']:>3}% -> {s['prix_offre_mad']:>14,.0f} MAD  [{s['zone']}]")
    print()
    if resultat["scenario_recommande"]:
        r = resultat["scenario_recommande"]
        print(
            f"Scenario recommande : rabais {r['rabais_pct']}% -> {r['prix_offre_mad']:,.0f} MAD "
            f"(le plus competitif, hors zone de risque)"
        )
