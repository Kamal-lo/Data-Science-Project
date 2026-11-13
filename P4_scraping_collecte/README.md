# P4 — Scraping · Collecte de Données

**Responsable :** P4  
**Rôle :** Collecte automatique des données depuis marchespublics.gov.ma et autres sources

---

## Tes dossiers

| Dossier | Contenu |
|---|---|
| `scripts/` | Scripts de scraping et collecte |
| `raw/` | Données brutes collectées (JSON, HTML, CSV) |
| `logs/` | Logs des sessions de scraping |
| `notebooks/` | Notebooks d'exploration du portail |

## Tes fichiers clés (déjà présents)

- `scripts/collect_dce.py` — Collecte et vérification des DCE
- `scripts/collect_attributions.py` — Collecte des historiques d'attribution

## Ce que tu dois produire

- [ ] Script de scraping robuste du portail marchespublics.gov.ma
- [ ] Données brutes enrichies dans `raw/`
- [ ] Pipeline de nettoyage et normalisation des données
- [ ] Logs structurés des collectes dans `logs/`

## Données déjà collectées (dans shared/)

```
../shared/dataset/real_tenders_live.json   ← 5 AO réels scrapés
../shared/data/real_attributions_live.json ← 5 attributions réelles
../shared/data/attributions_historique.csv ← 150 lignes synthétiques
```

## Limitation connue du portail

> ⚠️ **WAF Block** : Le téléchargement automatique des DCE ZIP est bloqué  
> par le WAF (Web Application Firewall) du portail.  
> Seules les métadonnées sont accessibles sans navigateur.  
> Voir : `../shared/docs/tasks/T03_BIS_REAL_DATA_SCRAPING.md`

## Portail officiel

- URL : https://www.marchespublics.gov.ma
- Framework : PRADO PHP (token PRADO_PAGESTATE requis)
- Accès : Anonyme pour les métadonnées, inscription pour DCE ZIP

