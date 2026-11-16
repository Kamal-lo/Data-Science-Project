import pandas as pd
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent.parent / "shared" / "data" / "attributions_historique.csv"


def charger_historique():
    return pd.read_csv(DATA_FILE)


def calculer_prix_reference(estimation_mad, region, secteur_activite, df=None):
    """Estime un prix de reference a partir du rabais moyen historique."""
    if df is None:
        df = charger_historique()

    rabais_global = df["rabais_pourcentage"].mean()

    sous_ensemble = df[(df["region"] == region) & (df["secteur_activite"] == secteur_activite)]
    if len(sous_ensemble) >= 5:
        rabais = sous_ensemble["rabais_pourcentage"].mean()
    else:
        rabais = rabais_global

    prix_reference = estimation_mad * (1 - rabais / 100)
    return prix_reference, rabais


if __name__ == "__main__":
    prix, rabais = calculer_prix_reference(10_000_000, "Casablanca-Settat", "BTP")
    print(f"Rabais estime : {rabais:.2f}%")
    print(f"Prix de reference estime : {prix:,.2f} MAD")