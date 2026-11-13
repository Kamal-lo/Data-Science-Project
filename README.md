# Plateforme IA — Réponse aux Marchés Publics Marocains

> **Projet Master 2 Data Science** | Réglementé par le Décret n° 2-22-431  
> Équipe de 6 membres (P1 à P6)

---

## Structure du Projet

```
project/
│
├── P1_chef_projet_ML_evaluation/   ← P1 : ML prédictif + évaluation
│   ├── models/                        Modèles entraînés
│   ├── evaluation/                    eval_suite.py, protocol, test_split
│   ├── notebooks/                     Analyses EDA
│   └── scripts/                       validate_annotations.py, attribution_eda.py
│
├── P2_nlp_extraction/              ← P2 : NLP + extraction d'info
│   ├── models/                        Modèles NER/NLP
│   ├── notebooks/                     Expérimentations
│   ├── scripts/                       Parsers, extracteurs
│   └── outputs/                       Résultats extractions
│
├── P3_base_donnees_backend/        ← P3 : BDD + API REST
│   ├── database/                      SQL, Pydantic (company_profile)
│   ├── api/                           FastAPI endpoints
│   ├── migrations/                    Alembic migrations
│   └── tests/                         Tests d'intégration
│
├── P4_scraping_collecte/           ← P4 : Scraping + collecte
│   ├── scripts/                       collect_dce.py, collect_attributions.py
│   ├── raw/                           Données brutes
│   └── logs/                          Logs de scraping
│
├── P5_frontend_interface/          ← P5 : Interface web
│   ├── src/                           Code React/Vue
│   ├── assets/                        Styles, images
│   └── mockups/                       Maquettes
│
├── P6_devops_infrastructure/       ← P6 : Docker + CI/CD
│   ├── docker/                        Dockerfiles, docker-compose
│   ├── ci_cd/                         Pipelines GitHub Actions
│   └── configs/                       Variables d'environnement
│
└── shared/                         ← DONNÉES PARTAGÉES (lecture seule)
    ├── dataset/
    │   ├── dce/                       5 DCE synthétiques (RC + CPS + BPU)
    │   ├── dce_real/                  5 DCE réels (metadata portail)
    │   ├── annotations/               5 ground truth (T04)
    │   └── real_tenders_live.json     AO réels scrapés
    ├── schemas/                       Schémas JSON + SQL
    ├── data/                          Attributions historiques
    └── docs/tasks/                    Documentation T02–T06
```

---

## Répartition des Tâches

| Membre | Rôle | Tâches principales |
|---|---|---|
| **P1** | Chef de projet · ML · Évaluation | T05 Protocole éval, Modèle ML prédictif |
| **P2** | NLP · Extraction | T03/T04 Parsing DCE, NER, extraction clauses |
| **P3** | BDD · Backend | T02 Schéma BDD, API REST FastAPI |
| **P4** | Scraping · Collecte | T03/T06 Collecte portail, attributions |
| **P5** | Frontend · UI | Interface web, dashboard marchés |
| **P6** | DevOps · Infrastructure | Docker, CI/CD, déploiement |

---

## Règles de Collaboration

1. **Chacun travaille dans son dossier `PX_xxx/`** — pas dans celui des autres
2. **`shared/` est en lecture seule** — copier dans son dossier avant de modifier
3. **Ne pas toucher `shared/dataset/annotations/`** — données d'évaluation gelées
4. **`shared/dataset/dce/DCE-2024-005-INGENIERIE-ETUDES/`** = jeu de TEST, lecture seule absolue

---

## Cadre Légal

Décret n° 2-22-431 relatif aux marchés publics au Maroc  
Portail officiel : [marchespublics.gov.ma](https://www.marchespublics.gov.ma)
