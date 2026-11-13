# P6 — DevOps · Infrastructure

**Responsable :** P6  
**Rôle :** Mise en place de l'infrastructure, CI/CD, containerisation, déploiement

---

## Tes dossiers

| Dossier | Contenu |
|---|---|
| `docker/` | Dockerfiles et docker-compose |
| `ci_cd/` | Pipelines CI/CD (GitHub Actions, GitLab CI) |
| `configs/` | Configurations serveurs, variables d'environnement |

## Ce que tu dois produire

- [ ] `docker/docker-compose.yml` — Stack complète (API + BDD + Frontend)
- [ ] `docker/Dockerfile.api` — Image Docker pour le backend FastAPI
- [ ] `docker/Dockerfile.frontend` — Image Docker pour le frontend
- [ ] `ci_cd/github_actions.yml` — Pipeline test + build + deploy
- [ ] `configs/.env.example` — Variables d'environnement documentées

## Stack cible

```yaml
services:
  postgres:    # PostgreSQL 16 + pgvector
  api:         # FastAPI (P3)
  frontend:    # React/Vue (P5)
  nginx:       # Reverse proxy
  redis:       # Cache (optionnel)
```

## Variables d'environnement à configurer

```env
DATABASE_URL=postgresql://user:pass@postgres:5432/marches_publics
SECRET_KEY=...
CORS_ORIGINS=http://localhost:3000
PORTAL_URL=https://www.marchespublics.gov.ma
```

## Ports par défaut

| Service | Port |
|---|---|
| Frontend | 3000 |
| API | 8000 |
| PostgreSQL | 5432 |
| Nginx | 80 / 443 |

