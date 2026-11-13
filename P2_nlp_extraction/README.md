# P2 — NLP · Extraction d'Information

**Responsable :** P2  
**Rôle :** Traitement du langage naturel, extraction des clauses clés des DCE, analyse sémantique

---

## Tes dossiers

| Dossier | Contenu |
|---|---|
| `models/` | Modèles NLP (CamemBERT, spaCy, etc.) |
| `notebooks/` | Notebooks d'expérimentation NLP |
| `scripts/` | Scripts d'extraction et de parsing |
| `outputs/` | Textes extraits, entités nommées, résultats |

## Ce que tu dois produire

- [ ] Pipeline d'extraction des clauses importantes des RC/CPS
- [ ] Modèle NER (Named Entity Recognition) pour marchés publics
- [ ] Extraction automatique : caution, délais, qualifications requises
- [ ] Sorties JSON dans `outputs/extractions/`

## Données disponibles (en lecture seule)

```
../shared/dataset/dce/           ← 5 DCE avec RC + CPS + BPU (texte brut)
../shared/dataset/annotations/   ← Ground truth pour évaluation
../shared/schemas/ground_truth.schema.json
```

## Formats d'entrée

Les DCE sont des fichiers `.txt` (RC, CPS) et `.csv` (BPU) :
```
shared/dataset/dce/DCE-2024-001-IT-CLOUD/
├── RC_Reglement_Consultation.txt
├── CPS_Prescriptions_Speciales.txt
└── BPU_Bordereau_Prix.csv
```

## Format de sortie attendu

```json
{
  "dce_id": "DCE-2024-001",
  "entites_extraites": {
    "caution_provisoire": "50000 MAD",
    "delai_execution": "12 mois",
    "qualification_requise": "Secteur I - Classe 3"
  }
}
```

> ⚠️ Ne jamais modifier les fichiers dans `shared/` directement.

