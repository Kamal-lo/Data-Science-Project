# P1 — Chef de Projet · ML Prédictif · Évaluation

**Responsable :** P1  
**Rôle :** Coordination générale + modèle ML de prédiction d'attribution + protocole d'évaluation

---

## Tes dossiers

| Dossier | Contenu |
|---|---|
| `models/` | Modèles ML entraînés (.pkl, .pt, .joblib) |
| `evaluation/` | Scripts d'évaluation, métriques, Gate 1 |
| `notebooks/` | Tes Jupyter notebooks d'analyse |
| `scripts/` | Scripts Python de validation et EDA |

## Tes fichiers clés (déjà présents)

- `evaluation/eval_suite.py` — Suite de métriques (CER, WER, F1, ExactMatch)
- `evaluation/protocol_specification.json` — Protocole officiel
- `evaluation/test_split.json` — Split Train/Val/Test (NE PAS MODIFIER)
- `scripts/validate_annotations.py` — Validation des annotations T04
- `scripts/attribution_eda.py` — Analyse exploratoire des attributions

## Ce que tu dois produire

- [ ] Modèle ML de prédiction du rabais / attribution (`models/`)
- [ ] Rapport d'évaluation Gate 1 (`evaluation/rapport_gate1.md`)
- [ ] Notebook d'analyse EDA (`notebooks/eda_attributions.ipynb`)

## Données disponibles (en lecture seule)

```
../shared/dataset/     ← DCE synthétiques + réels
../shared/data/        ← Attributions historiques (150 lignes)
../shared/schemas/     ← Schémas JSON/SQL
```

> ⚠️ Ne jamais modifier les fichiers dans `shared/` directement.
> Copier ce dont tu as besoin dans ton dossier.

