# shared/ — Données et Ressources Partagées

> ⚠️ **LECTURE SEULE** — Ne pas modifier directement.  
> Pour modifier : copier le fichier dans ton dossier `PX_xxx/`, modifier, puis soumettre via PR.

---

## Contenu

```
shared/
├── dataset/
│   ├── dce/                     ← 5 DCE synthétiques (RC + CPS + BPU + metadata)
│   │   ├── DCE-2024-001-IT-CLOUD/
│   │   ├── DCE-2024-002-BTP-CONSTRUCTION/
│   │   ├── DCE-2024-003-SERVICES-GARDIENNAGE/
│   │   ├── DCE-2024-004-FOURNITURES-MEDICALES/
│   │   └── DCE-2024-005-INGENIERIE-ETUDES/
│   ├── dce_real/                ← 5 DCE réels (metadata portail uniquement)
│   ├── annotations/             ← Ground truth T04 (5 fichiers JSON)
│   ├── dce_manifest.json        ← Index de tous les DCE
│   └── real_tenders_live.json   ← AO réels scrapés
│
├── schemas/
│   ├── company_profile.schema.json    ← Schéma profil entreprise
│   ├── attribution_data.schema.json   ← Schéma attributions
│   └── ground_truth.schema.json       ← Schéma annotations
│
├── data/
│   ├── attributions_historique.csv    ← 150 attributions (synthétique)
│   ├── real_attributions_live.json    ← 5 attributions réelles
│   └── mock_company_profile.json      ← Exemple profil entreprise
│
└── docs/
    └── tasks/                   ← Documentation T02 à T06
```

## Qui utilise quoi

| Membre | Dossiers shared utilisés |
|---|---|
| P1 | `data/attributions_historique.csv`, `dataset/annotations/` |
| P2 | `dataset/dce/` (RC + CPS + BPU), `dataset/annotations/` |
| P3 | `schemas/` (tous les schémas JSON + SQL) |
| P4 | `dataset/real_tenders_live.json`, `data/` |
| P5 | `schemas/company_profile.schema.json`, `data/mock_company_profile.json` |
| P6 | `schemas/` (pour configurer la BDD) |

