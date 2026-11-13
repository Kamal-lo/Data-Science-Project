# P3 — Base de Données · Backend API

**Responsable :** P3  
**Rôle :** Conception et gestion de la base de données, API REST backend

---

## Tes dossiers

| Dossier | Contenu |
|---|---|
| `database/` | Schémas SQL, modèles Pydantic, migrations |
| `api/` | Code de l'API REST (FastAPI / Flask) |
| `migrations/` | Scripts de migration de BDD |
| `tests/` | Tests unitaires et d'intégration |

## Tes fichiers clés (déjà présents)

- `database/company_profile.sql` — DDL PostgreSQL + pgvector (table entreprise)
- `database/company_profile_model.py` — Modèles Pydantic V2

## Ce que tu dois produire

- [ ] Base de données PostgreSQL opérationnelle (schéma complet)
- [ ] API REST : endpoints `/dce`, `/entreprise`, `/prediction`, `/attribution`
- [ ] Documentation API (Swagger/OpenAPI)
- [ ] Tests d'intégration dans `tests/`

## Schémas disponibles (lecture seule)

```
../shared/schemas/company_profile.schema.json   ← Profil entreprise
../shared/schemas/attribution_data.schema.json  ← Historique attributions
../shared/schemas/ground_truth.schema.json      ← Annotations
```

## Stack recommandée

- **BDD :** PostgreSQL 16 + pgvector (vecteurs d'embeddings)
- **ORM :** SQLAlchemy + Alembic
- **API :** FastAPI + Pydantic V2
- **Auth :** JWT tokens

> ⚠️ Ne jamais modifier les fichiers dans `shared/` directement.

