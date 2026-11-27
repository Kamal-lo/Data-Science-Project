import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from compliance_checklist import generer_checklist
from document_checks import controler_caution, controler_validite_attestation

# Ce module prepare le contenu qui sera un jour renvoye par l'endpoint
# GET /bids/{id}/compliance (construit par P3/P6). Ici on se concentre sur
# le contenu metier : checklist, controles, feuille de route, statut global.


def generer_feuille_de_route(metadata_generale, date_limite_remise_plis, date_seance_ouverture):
    """Construit la liste des echeances cles du marche, dans l'ordre chronologique."""
    return [
        {"etape": "Date limite de remise des plis", "date": date_limite_remise_plis},
        {"etape": "Seance d'ouverture des plis", "date": date_seance_ouverture},
    ]


def generer_rapport_conformite(dce_id, champs_extraits, metadata_generale, documents_soumis):
    """Agrege checklist + controles en un seul rapport de conformite.

    documents_soumis attendu sous la forme :
        {
            "caution_fournie_mad": 410000,
            "attestation_fiscale_delivree_le": date(2024, 3, 1),
            "attestation_cnss_delivree_le": date(2023, 5, 15),
        }
    """
    checklist = generer_checklist(champs_extraits)

    estimation = champs_extraits["estimation_maitre_ouvrage_mad"]["valeur_normalisee"]
    caution_requise = champs_extraits.get("caution_provisoire_mad", {}).get("valeur_normalisee", 0)
    date_depot = datetime.fromisoformat(
        champs_extraits["date_limite_remise_plis"]["valeur_normalisee"]
    ).date()

    controles = []

    if caution_requise:
        controles.append(("caution", controler_caution(
            caution_requise_mad=caution_requise,
            caution_fournie_mad=documents_soumis.get("caution_fournie_mad", 0),
            estimation_mad=estimation,
        )))

    for nom_cle, nom_affiche in [
        ("attestation_fiscale_delivree_le", "Attestation fiscale"),
        ("attestation_cnss_delivree_le", "Attestation CNSS"),
    ]:
        date_delivrance = documents_soumis.get(nom_cle)
        if date_delivrance:
            resultat = controler_validite_attestation(nom_affiche, date_delivrance, date_depot)
            controles.append((nom_cle, resultat))

    anomalies = []
    for _, resultat in controles:
        if not resultat["conforme"]:
            anomalies.extend(resultat.get("anomalies", [resultat.get("message", "anomalie")]))

    feuille_de_route = generer_feuille_de_route(
        metadata_generale,
        champs_extraits["date_limite_remise_plis"]["valeur_normalisee"],
        champs_extraits["date_seance_ouverture"]["valeur_normalisee"],
    )

    return {
        "dce_id": dce_id,
        "statut_global": "CONFORME" if not anomalies else "NON_CONFORME",
        "checklist_pieces": checklist,
        "controles": {nom: resultat for nom, resultat in controles},
        "anomalies": anomalies,
        "feuille_de_route": feuille_de_route,
    }


if __name__ == "__main__":
    annotation_file = (
        Path(__file__).parent.parent.parent
        / "shared" / "dataset" / "annotations" / "DCE-2024-002_ground_truth.json"
    )
    with open(annotation_file, encoding="utf-8") as f:
        data = json.load(f)

    documents_soumis = {
        "caution_fournie_mad": 350_000,  # insuffisant, cf T56
        "attestation_fiscale_delivree_le": date(2024, 3, 1),
        "attestation_cnss_delivree_le": date(2023, 5, 15),  # perimee
    }

    rapport = generer_rapport_conformite(
        dce_id=data["dce_id"],
        champs_extraits=data["champs_cles_extraits"],
        metadata_generale=data["metadata_generale"],
        documents_soumis=documents_soumis,
    )

    print(f"Rapport de conformite - {rapport['dce_id']}")
    print(f"Statut global : {rapport['statut_global']}\n")

    print(f"Checklist ({len(rapport['checklist_pieces'])} pieces) :")
    for item in rapport["checklist_pieces"]:
        print(f"  - {item}")

    print("\nAnomalies detectees :")
    if rapport["anomalies"]:
        for a in rapport["anomalies"]:
            print(f"  ! {a}")
    else:
        print("  Aucune")

    print("\nFeuille de route :")
    for etape in rapport["feuille_de_route"]:
        print(f"  {etape['date']} -> {etape['etape']}")
