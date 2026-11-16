import json
from pathlib import Path

PARAMS_FILE = Path(__file__).parent / "reglementation_params.json"


def charger_parametres():
    with open(PARAMS_FILE, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    data = charger_parametres()
    print("Version du decret :", data["decree_version"])
    print("Seuil offre excessive :", data["parameters"]["seuil_offre_excessive_pct"], "%")