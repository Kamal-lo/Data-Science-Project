# P3 (Rida Mellouki) — Module C : RAG & Rédaction du Mémoire Technique (T40 à T42)

> **Projet Master 2 Data Science & IA** — Plateforme IA de réponse aux marchés publics marocains (Décret n° 2-22-431)  
> **Responsable :** Rida Mellouki (**P3**)  
> **Périmètre de ce livrable :** Tâches **T40**, **T41** et **T42** (avec **Qdrant** + **Docker**)

---

## Ce que j'ai réalisé (Rida Mellouki — P3 / Module C)

Dans le cadre de mon rôle **P3 (RAG, embeddings, génération & anti-hallucination)**, j'ai conçu, développé, testé et conteneurisé le socle complet des tâches **T40, T41 et T42** autour de la base vectorielle **Qdrant** :

- **T40 — Indexation du corpus entreprise dans Qdrant (`rag_module/indexing/`)** :
  - J'ai développé un pipeline d'ingestion multi-formats (`.txt`, `.md`, `.json`, `.pdf`, `.docx`) avec détection automatique de la langue (`fr`, `ar`, `bilingual`) et un adaptateur convertissant directement le schéma `EntrepriseProfile` existant en documents typés (`memoire_gagne`, `cv`, `moyens`, `reference`).
  - J'ai implémenté **3 stratégies de découpage (chunking)** comparables (`recursive_structure` respectant les titres FR/AR, `sentence`, `fixed`), avec traçabilité (`page_or_section`), empreinte SHA-256 et identifiants **UUIDv5 déterministes** garantissant l'idempotence (zéro doublon lors des ré-indexations).
  - J'ai intégré les embeddings multilingues FR/AR (`intfloat/multilingual-e5-base` avec préfixes `passage:` / `query:` + mode léger `hash` pour tests hors-ligne) et configuré la collection Qdrant `entreprise_corpus` (similarité Cosinus + **Payload Indexes** sur les métadonnées métier).
- **T41 — Pipeline RAG avec filtrage métadonnées et reclassement (`rag_module/retrieval/`)** :
  - J'ai mis en place un **pré-filtrage strict Qdrant** imposant l'isolation multi-tenant (`company_id`) et combinant les filtres métier (`doc_types`, `sectors`, `language`, `year`, `client_type`, `amount_mad`, `tags`).
  - J'ai construit un pipeline en 2 étapes : recherche vectorielle dense top-20 suivie d'un **reclassement (reranking)** hybride (`HybridLexicalReranker` combinant cosinus + BM25 lexical sur sigles marocains `Décret 2-22-431`, `DNSSI`, `ISO 27001`, `D14` + bigrammes + boost `preferred_doc_types` et fraîcheur) ou neuronal (`CrossEncoderReranker`).
  - J'ai ajouté la génération automatique des citations `[SRC-i | doc_type | source_file § page_or_section]`, la télémétrie de latence par étape et les métriques d'évaluation **`Recall@k` et `MRR`**.
- **T42 — Gabarits et prompts anti-hallucination des 6 sections (`rag_module/templates/`)** :
  - J'ai défini les **6 gabarits réglementaires du mémoire technique** (titres FR/AR, sous-sections obligatoires, types de documents prioritaires et format de sortie structuré).
  - J'ai développé `PromptBuilder` reliant le contexte DCE (Module B2) aux chunks récupérés par T41 pour produire des prompts `system` et `user` imposant les citations `[SRC-i]`, le marqueur explicite `[DONNÉE MANQUANTE À COMPLÉTER PAR L'ENTREPRISE]` en cas d'absence de preuve et des alertes pré-génération (`warnings`).
- **API REST, Docker + Qdrant, Corpus d'exemple & Validation** :
  - J'ai exposé les endpoints FastAPI dédiés à T40, T41 et T42 (`api/main.py`), écrit le `Dockerfile` et le `docker-compose.yml` (Qdrant `v1.13.4` + API sur le port `8003`).
  - J'ai créé un corpus synthétique marocain réaliste (`data/sample_corpus/`), les scripts CLI `seed_sample_corpus.py` et `benchmark_rag.py`, ainsi qu'une suite automatisée `pytest` couvrant T40, T41, T42 et l'API.

---

## 1. Rôle du Module C dans la plateforme

Dans la chaîne globale du projet :
1. **P2 (B1)** lit et convertit le DCE (PDF/DOCX/scans FR & AR).
2. **P6 (B2)** extrait les champs structurés et exigences clés du DCE (caution, délai, agréments, barème technique).
3. **P3 (Module C — ce dossier)** s'appuie sur le **corpus interne de l'entreprise** (mémoires techniques déjà gagnés, CVs d'experts, moyens matériels/certifications, références similaires) pour préparer la rédaction d'un **mémoire technique fiable et traçable**, sans hallucination.

Ce livrable couvre exclusivement les **3 tâches fondatrices du pipeline RAG** :

| ID | Tâche | Objectif | Code principal |
|---|---|---|---|
| **T40** | Indexer le corpus entreprise (mémoires gagnés, CV, moyens, références) avec métadonnées | Ingestion multi-formats, découpage traçable, embeddings multilingues FR/AR et stockage dans **Qdrant** | `rag_module/indexing/` |
| **T41** | Pipeline RAG : filtre métadonnées, recherche vectorielle, reclassement | Pré-filtrage strict multi-tenant sur Qdrant, recherche cosinus top-K, reclassement (reranking) et mesure **Recall@k / MRR** | `rag_module/retrieval/` |
| **T42** | Gabarits et prompts des 6 sections | Structuration des 6 sections réglementaires du mémoire technique et construction de prompts ancrés avec règles **anti-hallucination** | `rag_module/templates/` |

> Les tâches suivantes (**T43** vérification anti-hallucination post-génération, **T44** génération LLM section par section, **T45** export DOCX, **T46** éditeur UI, **T47** évaluation finale) se branchent directement sur la sortie structurée de **T42**.

---

## 2. Architecture globale du pipeline (T40 → T41 → T42)

```text
                        [T40 : INDEXATION CORPUS ENTREPRISE]
   Documents (MD, TXT, PDF, DOCX) + EntrepriseProfile (JSON)
          │
          ▼
   Loaders & Détection langue (FR / AR / Bilingue)
          │
          ▼
   Chunking (recursive_structure | sentence | fixed) + SHA-256 + UUIDv5
          │
          ▼
   Embeddings Multilingues (intfloat/multilingual-e5-base, préfixe "passage:")
          │
          ▼
   ┌──────────────────────────────────────────────────────────┐
   │             QDRANT (Collection: entreprise_corpus)       │
   │  Vecteurs Cosinus (768d) + Payload Indexes (company_id,  │
   │  doc_type, sector, year, client_type, amount_mad, tags)  │
   └───────────────────────────┬──────────────────────────────┘
                               │
                        [T41 : PIPELINE RAG]
                               │
   Requête DCE + MetadataFilter (company_id obligatoire)
          │
          ├─► 1. Pré-filtrage métadonnées Qdrant (isolation entreprise + critères)
          ├─► 2. Recherche vectorielle dense (préfixe "query:", top-20 candidats)
          └─► 3. Reclassement (Hybrid BM25+Vectoriel ou Cross-Encoder multilingue → top-6)
                               │
                               ▼
              Chunks classés + Citations [SRC-1 .. SRC-k] + Télémétrie
                               │
                        [T42 : GABARITS & PROMPTS]
                               │
   DCEContext (Module B2) + Gabarit Section (1 à 6) + Sources [SRC-i]
          │
          ▼
   PromptBuilder → (system_prompt anti-hallucination, user_prompt structuré, registre sources)
          │
          ▼
   Prêt pour T43 (Vérification) et T44 (Génération LLM)
```

---

## 3. Choix techniques et justifications scientifiques

### 3.1 Base vectorielle : pourquoi **Qdrant** ?
- **Filtrage métadonnées natif performant (HNSW + Payload Indexes)** : Qdrant applique les filtres (`company_id`, `doc_type`, `year`, `amount_mad`, `sector`, `tags`) *pendant* la traversée du graphe HNSW (pre-filtering), évitant la perte de rappel du post-filtering classique.
- **Isolation multi-tenant stricte** : chaque requête impose un filtre `must` sur `company_id`, garantissant qu'une entreprise ne récupère jamais les données confidentielles d'une autre entreprise (exigence clé de sécurité et Loi n° 09-08).
- **Idempotence** : les points Qdrant utilisent un **UUIDv5 déterministe** calculé sur `(company_id, doc_id, chunk_index, content_hash)` ; ré-indexer un document mis à jour ne crée aucun doublon.
- **Flexibilité Dev / Prod** : support natif des modes `remote` (conteneur Docker Qdrant), `local` (disque) et `memory` (tests unitaires rapides sans dépendance externe).

### 3.2 Modèle d'embeddings multilingue (FR / AR) : pourquoi `intfloat/multilingual-e5-base` ?
- Les DCE et corpus d'entreprises marocaines mélangent **français administratif/technique** et **arabe** (titres, articles, pièces).
- `intfloat/multilingual-e5-base` (768 dimensions) est un standard open-source très performant sur les benchmarks multilingues (MTEB) pour le français et l'arabe, léger à déployer en local/Docker, et conçu pour la recherche asymétrique grâce aux préfixes **`passage:`** (indexation) et **`query:`** (recherche) + normalisation L2 (similarité cosinus).
- Un fournisseur secondaire **`hash`** (`HashFallbackEmbeddingProvider`, hachage signé de mots, bigrammes et trigrammes normalisés FR/AR) est également fourni pour exécuter les tests et la CI en moins d'une seconde sans télécharger de poids HuggingFace.

### 3.3 Stratégies de découpage (Chunking) comparables
Pour permettre l'évaluation scientifique demandée dans la fiche P3 (*« Comparaison chunking, retrieval et reclassement (recall@k) »*), 3 stratégies sont implémentées dans `rag_module/indexing/chunking.py` :
1. **`recursive_structure` (par défaut)** : détecte les titres Markdown (`#`), les intitulés réglementaires français (`CHAPITRE`, `ARTICLE`, `SECTION`, `1.2 ...`) et arabes (`الفصل`, `المادة`, `القسم`) afin de ne jamais couper un paragraphe au milieu d'un titre et de conserver `page_or_section` pour la traçabilité.
2. **`sentence`** : découpage par phrases FR/AR avec fenêtre glissante et chevauchement (`chunk_overlap`).
3. **`fixed`** : découpage par taille fixe de caractères (baseline de référence).

### 3.4 Reclassement (Reranking) en 2 étapes (Bi-Encoder → Reranker)
La recherche vectorielle seule (bi-encoder) capture bien la sémantique globale, mais peut rater des **sigles réglementaires exacts** décisifs dans un marché public marocain (`Décret 2-22-431`, `DNSSI`, `ISO 27001`, `Agrément D14`, `CNSS`, `CCAG-EMO`).
- **Étape 1 (Rappel)** : Qdrant récupère `initial_top_k = 20` candidats filtrés.
- **Étape 2 (Précision)** : le reranker réordonne les 20 candidats pour ne garder que les `final_top_k = 6` meilleurs :
  - **`HybridLexicalReranker` (par défaut, rapide, CPU)** : combine le score cosinus normalisé (`0.50`), un score BM25 local pondéré IDF sur les termes techniques FR/AR (`0.35`), la correspondance de bigrammes (`0.10`), un boost si le `doc_type` correspond à la section cible (`+0.05`) et un léger bonus de fraîcheur (`+0.03`).
  - **`CrossEncoderReranker` (neuronal, configurable)** : utilise `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (ou `BAAI/bge-reranker-v2-m3`) qui encode conjointement `(requête, passage)` pour un scoring sémantique fin.

### 3.5 Gabarits des 6 sections & conception Anti-Hallucination (T42)
Les 6 sections couvrent l'ensemble des critères habituels du barème technique (`bareme_technique`) au Maroc :

| # | Identifiant | Section du Mémoire Technique | Types de corpus prioritaires (`preferred_doc_types`) |
|---|---|---|---|
| 1 | `section_1_presentation_entreprise` | Présentation de l'entreprise, organisation et gouvernance | `moyens`, `reference`, `memoire_gagne` |
| 2 | `section_2_comprehension_enjeux` | Compréhension du besoin, contexte et analyse des exigences du DCE | `memoire_gagne`, `reference` |
| 3 | `section_3_methodologie_technique` | Méthodologie d'exécution, démarche technique et architecture | `memoire_gagne`, `moyens`, `reference` |
| 4 | `section_4_moyens_humains` | Moyens humains, équipe dédiée et qualifications des experts | `cv`, `moyens` |
| 5 | `section_5_moyens_materiels_qualite` | Moyens matériels, logistiques, démarche qualité, sécurité et HSE | `moyens`, `memoire_gagne` |
| 6 | `section_6_planning_references` | Planning prévisionnel, gestion des risques et références similaires | `reference`, `memoire_gagne` |

**Garde-fous anti-hallucination intégrés dès le prompt :**
- **Grounding strict** : interdiction explicite d'inventer un chiffre, nom d'expert, diplôme, numéro de marché, certificat ou équipement absent des sources `[SRC-1 .. SRC-N]`.
- **Traçabilité inline** : chaque fait vérifiable doit être suivi de sa citation `[SRC-i]`.
- **Gestion explicite des lacunes** : toute exigence du DCE non couverte par le corpus entreprise doit afficher littéralement `[DONNÉE MANQUANTE À COMPLÉTER PAR L'ENTREPRISE]` au lieu d'être inventée.
- **Alertes pré-génération (`warnings`)** : `PromptBuilder` signale automatiquement si aucune source n'a été trouvée ou si aucun document du type prioritaire (ex : aucun `cv` pour la section 4) n'est présent.

---

## 4. Structure du dossier P3

```text
P3_base_donnees_backend/
├── Dockerfile                          # Image Python 3.12-slim du service RAG P3
├── docker-compose.yml                  # Stack Qdrant (v1.13.4) + API FastAPI P3 (port 8003)
├── .env.example                        # Variables d'environnement documentées
├── .dockerignore / .gitignore
├── requirements.txt                    # Dépendances runtime (FastAPI, qdrant-client, sentence-transformers...)
├── requirements-dev.txt                # Dépendances tests (pytest, httpx)
├── database/                           # Fichiers initiaux conservés intacts (company_profile SQL/Pydantic)
├── rag_module/
│   ├── config.py                       # Configuration centrale (Qdrant, embeddings, chunking, reranker)
│   ├── schemas.py                      # Modèles Pydantic V2 pour T40, T41 et T42
│   ├── indexing/                       # === T40 ===
│   │   ├── loaders.py                  # Chargeurs fichiers + adaptateur EntrepriseProfile
│   │   ├── chunking.py                 # 3 stratégies de chunking + traçabilité + UUIDv5
│   │   ├── embeddings.py               # Multilingual E5 + Hash fallback FR/AR
│   │   ├── qdrant_store.py             # Collection Qdrant, payload indexes, upsert/search/delete
│   │   └── indexer.py                  # Orchestrateur CorpusIndexer
│   ├── retrieval/                      # === T41 ===
│   │   ├── filters.py                  # Traduction MetadataFilter → Qdrant models.Filter
│   │   ├── reranker.py                 # HybridLexicalReranker & CrossEncoderReranker
│   │   ├── pipeline.py                 # RAGRetrievalPipeline + télémétrie + citations
│   │   └── evaluation.py               # Métriques Recall@k et MRR
│   └── templates/                      # === T42 ===
│       ├── sections.py                 # Gabarits détaillés des 6 sections (FR & AR)
│       └── prompt_builder.py           # Assemblage DCEContext + T41 → Prompts ancrés
├── api/
│   └── main.py                         # Endpoints FastAPI dédiés à T40, T41 et T42
├── data/sample_corpus/                 # Corpus marocain synthétique (profil, mémoire gagné, CV, PAQ/DNSSI)
├── scripts/
│   ├── seed_sample_corpus.py           # CLI d'indexation du corpus exemple dans Qdrant
│   └── benchmark_rag.py                # CLI de comparaison chunking & reranking (Recall@k / MRR)
└── tests/                              # Tests unitaires et d'intégration T40, T41, T42 et API
```

---

## 5. Endpoints API FastAPI (T40 – T42)

| Méthode | Endpoint | Tâche | Description |
|---|---|---|---|
| `GET` | `/health` | Santé | Vérifie la connexion Qdrant, le modèle d'embeddings et le reranker actif |
| `POST` | `/api/v1/corpus/documents` | **T40** | Indexe un lot de documents (`memoire_gagne`, `cv`, `moyens`, `reference`) dans Qdrant |
| `POST` | `/api/v1/corpus/company-profile` | **T40** | Convertit et indexe directement un profil `EntrepriseProfile` (JSON) dans Qdrant |
| `GET` | `/api/v1/corpus/stats` | **T40** | Statistiques de la collection Qdrant (global ou filtré par `company_id`) |
| `DELETE` | `/api/v1/corpus/documents/{doc_id}` | **T40** | Supprime tous les chunks d'un document donné dans Qdrant |
| `POST` | `/api/v1/rag/retrieve` | **T41** | Exécute le pipeline complet : filtre métadonnées → recherche vectorielle → reclassement |
| `GET` | `/api/v1/templates/sections` | **T42** | Retourne la liste ordonnée des 6 gabarits de sections |
| `GET` | `/api/v1/templates/sections/{section_id}` | **T42** | Retourne le gabarit complet d'une section spécifique |
| `POST` | `/api/v1/templates/sections/{section_id}/build-prompt` | **T41+T42** | Exécute le retrieval ciblé pour la section et renvoie le prompt `system` + `user` prêt pour le LLM |

---

## 6. Lancer le projet (Docker + Qdrant)

### Option A — Stack complète avec Docker Compose (recommandé)
```bash
cd P3_base_donnees_backend
cp .env.example .env
docker compose up --build -d
```
- **Interface Qdrant (Dashboard) :** `http://localhost:6333/dashboard`
- **Documentation interactive Swagger (API P3) :** `http://localhost:8003/docs`
- **Healthcheck :** `http://localhost:8003/health`

> Pour un démarrage rapide en démonstration sans télécharger les poids HuggingFace (~1 Go) :
> ```bash
> EMBEDDING_PROVIDER=hash EMBEDDING_DIMENSION=384 docker compose up --build -d
> ```

### Option B — Exécution locale (Python)
```bash
cd P3_base_donnees_backend
pip install -r requirements.txt -r requirements-dev.txt

# 1. Lancer la suite de tests (utilise Qdrant en mémoire)
pytest -v

# 2. Comparer les 3 stratégies de chunking et le reranking (Recall@k & MRR)
python scripts/benchmark_rag.py

# 3. Indexer le corpus d'exemple dans Qdrant (démarrer Qdrant sur :6333 ou utiliser QDRANT_MODE=memory)
python scripts/seed_sample_corpus.py
```

---

## 7. Résultats de validation & métriques

- **Tests automatisés (`pytest -v`)** : validation de la conversion `EntrepriseProfile`, des 3 stratégies de chunking, de la détection FR/AR/bilingue, de l'idempotence des upserts Qdrant, de l'**isolation stricte multi-tenant** (zéro fuite entre entreprises), des filtres combinés (`doc_type`, `year`, `client_type`, `amount_mad`), du reranking, et de la génération des prompts des 6 sections.
- **Benchmark `scripts/benchmark_rag.py`** sur le corpus exemple marocain :
  - `fixed` (19 chunks) : `Recall@3 = 1.0`, `Recall@5 = 1.0`, `MRR = 1.0`
  - `sentence` (19 chunks) : `Recall@3 = 1.0`, `Recall@5 = 1.0`, `MRR = 1.0`
  - `recursive_structure` (26 chunks avec titres de sections préservés) : `Recall@3 = 1.0`, `Recall@5 = 1.0`, `MRR = 1.0`

---

## 8. Règles de collaboration respectées

- Seul le dossier `P3_base_donnees_backend/` a été modifié.
- Aucun fichier de `shared/` (y compris le jeu de test gelé `DCE-2024-005`) n'a été altéré.
- Les schémas existants `database/company_profile.sql` et `database/company_profile_model.py` ont été préservés et réutilisés dans T40.
