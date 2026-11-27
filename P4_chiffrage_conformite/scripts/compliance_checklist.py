import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from reglementation import charger_parametres

DOCUMENTS_STANDARDS = [
    "Declaration sur l'honneur (Art. 29)",
    "Attestation de regularite fiscale (< 1 an)",
    "Attestation CNSS (< 1 an)",
    "Extrait du Registre de Commerce (modele 9)",
    "Pieces justifiant les pouvoirs du representant legal",
]


def generer_checklist(champs_extraits):
    """Construit la checklist des pieces a fournir, a partir des champs extraits
    d'un DCE (T27/T32 dans le pipeline final ; pour l'instant, les annotations
    ground truth du jeu de donnees partage servent de substitut)."""
    params = charger_parametres()["parameters"]
    checklist = list(DOCUMENTS_STANDARDS)

    caution_champ = champs_extraits.get("caution_provisoire_mad", {})
    caution = caution_champ.get("valeur_normalisee")
    if caution:
        plafond_pct = params["caution_provisoire_plafond_pct"]
        checklist.append(
            f"Caution provisoire bancaire ({caution:,.0f} MAD) "
            f"- rappel : plafond legal {plafond_pct}% de l'estimation"
        )
    else:
        penalite_pct = params["penalite_sans_caution_pct"]
        checklist.append(
            f"Pas de caution provisoire exigee par ce CPS "
            f"- penalite de {penalite_pct}% applicable en cas de defaillance"
        )

    exigences_champ = champs_extraits.get("exigences_techniques_ou_agrements", {})
    for exigence in exigences_champ.get("valeur_normalisee", []):
        checklist.append(f"Certificat de qualification/agrement requis : {exigence}")

    return checklist


if __name__ == "__main__":
    annotation_file = (
        Path(__file__).parent.parent.parent
        / "shared" / "dataset" / "annotations" / "DCE-2024-002_ground_truth.json"
    )
    with open(annotation_file, encoding="utf-8") as f:
        data = json.load(f)

    checklist = generer_checklist(data["champs_cles_extraits"])

    print(f"Checklist des pieces a fournir - {data['dce_id']} :\n")
    for i, item in enumerate(checklist, 1):
        print(f"  {i}. {item}")
