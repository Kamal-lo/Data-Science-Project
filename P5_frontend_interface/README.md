# P5 — Frontend · Interface Utilisateur

**Responsable :** P5  
**Rôle :** Conception et développement de l'interface web de la plateforme

---

## Tes dossiers

| Dossier | Contenu |
|---|---|
| `src/` | Code source frontend (React / Vue / HTML) |
| `assets/` | Images, icônes, CSS, polices |
| `mockups/` | Maquettes et wireframes |

## Ce que tu dois produire

- [ ] Interface de recherche et consultation des appels d'offres
- [ ] Formulaire de profil entreprise (basé sur le schéma T02)
- [ ] Dashboard de suivi des marchés (statut, délais, montants)
- [ ] Page de résultats avec score de compatibilité IA
- [ ] Maquettes validées dans `mockups/`

## APIs à consommer (depuis P3)

```
GET  /api/dce              ← Liste des appels d'offres
GET  /api/dce/{id}         ← Détail d'un DCE
POST /api/entreprise       ← Créer profil entreprise
GET  /api/prediction/{id}  ← Score de compatibilité ML
GET  /api/attributions     ← Historique des attributions
```

## Schéma du profil entreprise (pour le formulaire)

```
../shared/schemas/company_profile.schema.json
```

## Exemple de profil (pour les maquettes)

```
../shared/data/mock_company_profile.json
```

## Stack recommandée

- **Framework :** React.js ou Vue.js
- **UI :** Tailwind CSS ou Bootstrap 5
- **Charts :** Chart.js ou Recharts
- **Langue :** Interface bilingue Français / Arabe

