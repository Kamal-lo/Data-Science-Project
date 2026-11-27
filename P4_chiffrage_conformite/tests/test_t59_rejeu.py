"""T59 - Rejoue les 5 DCE synthetiques du jeu partage, et teste des dossiers
volontairement incomplets, pour verifier la robustesse de D (chiffrage) et
E (conformite) avant que le module B ne soit disponible en production."""

import json
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from offer_alerts import evaluer_offre
from compliance_report import generer_rapport_conformite

ANNOTATIONS_DIR = (
    Path(__file__).parent.parent.parent / "shared" / "dataset" / "annotations"
)


def charger_tous_les_dce():
    dce_list = []
    for fichier in sorted(ANNOTATIONS_DIR.glob("*_ground_truth.json")):
        with open(fichier, encoding="utf-8") as f:
            dce_list.append(json.load(f))
    return dce_list


def test_rejouer_tous_les_dce():
    """Verifie que chaque DCE du jeu de donnees passe sans erreur dans le
    pipeline D/E, et que le type de marche est correctement pris en compte
    (notamment le cas particulier ETUDES, cf. T56)."""
    dce_list = charger_tous_les_dce()
    assert len(dce_list) == 5, f"Attendu 5 DCE, trouve {len(dce_list)}"

    for dce in dce_list:
        type_prestation = dce["metadata_generale"]["type_prestation"]
        estimation = dce["champs_cles_extraits"]["estimation_maitre_ouvrage_mad"]["valeur_normalisee"]

        # Scenario d'offre arbitraire : 15% de rabais
        offre_simulee = estimation * 0.85
        alerte = evaluer_offre(estimation, offre_simulee, type_prestation)

        if type_prestation == "ETUDES":
            assert alerte["statut"] == "NON_APPLICABLE", (
                f"{dce['dce_id']} (ETUDES) ne devrait avoir aucun seuil applique"
            )
        else:
            assert alerte["statut"] in ("CONFORME", "EXCESSIVE", "ANORMALEMENT_BASSE")

        # Document conforme : caution complete, attestations fraiches
        date_depot = datetime.fromisoformat(
            dce["champs_cles_extraits"]["date_limite_remise_plis"]["valeur_normalisee"]
        ).date()
        documents_conformes = {
            "caution_fournie_mad": dce["champs_cles_extraits"]
            .get("caution_provisoire_mad", {})
            .get("valeur_normalisee", 0),
            "attestation_fiscale_delivree_le": date_depot.replace(year=date_depot.year - 0),
            "attestation_cnss_delivree_le": date_depot.replace(year=date_depot.year - 0),
        }
        rapport = generer_rapport_conformite(
            dce_id=dce["dce_id"],
            champs_extraits=dce["champs_cles_extraits"],
            metadata_generale=dce["metadata_generale"],
            documents_soumis=documents_conformes,
        )
        assert rapport["statut_global"] == "CONFORME", (
            f"{dce['dce_id']} : dossier complet et a jour signale a tort NON_CONFORME "
            f"-> anomalies: {rapport['anomalies']}"
        )

        print(f"[OK] {dce['dce_id']} ({type_prestation}) - rejoue sans erreur, dossier conforme valide")


def test_dossier_volontairement_incomplet():
    """Prend un DCE reel et simule un dossier incomplet : caution insuffisante
    et attestation CNSS perimee. Le rapport doit detecter les deux anomalies."""
    dce_file = ANNOTATIONS_DIR / "DCE-2024-002_ground_truth.json"
    with open(dce_file, encoding="utf-8") as f:
        dce = json.load(f)

    documents_incomplets = {
        "caution_fournie_mad": 0,  # caution non fournie du tout
        "attestation_fiscale_delivree_le": date(2020, 1, 1),  # tres ancienne
        "attestation_cnss_delivree_le": date(2020, 1, 1),  # tres ancienne
    }

    rapport = generer_rapport_conformite(
        dce_id=dce["dce_id"],
        champs_extraits=dce["champs_cles_extraits"],
        metadata_generale=dce["metadata_generale"],
        documents_soumis=documents_incomplets,
    )

    assert rapport["statut_global"] == "NON_CONFORME"
    assert len(rapport["anomalies"]) >= 2, "Le dossier incomplet devrait remonter au moins 2 anomalies"

    print(f"[OK] Dossier volontairement incomplet correctement rejete "
          f"({len(rapport['anomalies'])} anomalies detectees)")


if __name__ == "__main__":
    test_rejouer_tous_les_dce()
    test_dossier_volontairement_incomplet()
    print("\nTous les tests T59 sont passes.")
