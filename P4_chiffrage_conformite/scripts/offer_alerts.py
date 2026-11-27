import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from reglementation import charger_parametres
from price_optimizer import seuil_anormalement_basse_pct


def evaluer_offre(estimation_mad, offre_mad, type_prestation):
    """Classe une offre financiere par rapport a l'estimation du maitre d'ouvrage,
    selon les seuils de l'article 44 du decret 2-22-431 (T14/T50)."""
    ecart_pct = (offre_mad - estimation_mad) / estimation_mad * 100

    if type_prestation.upper() == "ETUDES":
        return {
            "estimation_mad": estimation_mad,
            "offre_mad": offre_mad,
            "ecart_pct": round(ecart_pct, 2),
            "statut": "NON_APPLICABLE",
            "message": (
                "Aucun seuil d'offre excessive/anormalement basse pour les etudes "
                "(article 44) - evaluation par note technico-financiere (article 144)"
            ),
        }

    params = charger_parametres()
    seuil_excessif = params["parameters"]["seuil_offre_excessive_pct"]
    seuil_bas = seuil_anormalement_basse_pct(type_prestation, params)

    if ecart_pct > seuil_excessif:
        statut = "EXCESSIVE"
        message = f"Offre superieure de {ecart_pct:.1f}% a l'estimation (seuil : +{seuil_excessif}%)"
    elif ecart_pct < -seuil_bas:
        statut = "ANORMALEMENT_BASSE"
        message = f"Offre inferieure de {abs(ecart_pct):.1f}% a l'estimation (seuil : -{seuil_bas}%)"
    else:
        statut = "CONFORME"
        message = f"Offre dans la zone normale (ecart de {ecart_pct:+.1f}% par rapport a l'estimation)"

    return {
        "estimation_mad": estimation_mad,
        "offre_mad": offre_mad,
        "ecart_pct": round(ecart_pct, 2),
        "statut": statut,
        "message": message,
    }


if __name__ == "__main__":
    cas_test = [
        (27_700_000, 23_000_000, "TRAVAUX"),       # offre normale
        (27_700_000, 34_000_000, "TRAVAUX"),       # offre excessive (+20%)
        (27_700_000, 20_000_000, "TRAVAUX"),       # offre anormalement basse (-20%)
        (8_900_000, 6_500_000, "FOURNITURES"),     # proche de la limite (-25%)
    ]

    for estimation, offre, type_prestation in cas_test:
        resultat = evaluer_offre(estimation, offre, type_prestation)
        print(f"[{resultat['statut']:>20}] {type_prestation:<12} "
              f"estimation={estimation:,.0f}  offre={offre:,.0f}  -> {resultat['message']}")
