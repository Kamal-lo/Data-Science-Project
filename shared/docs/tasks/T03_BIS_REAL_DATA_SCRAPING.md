# T03-BIS — Scraping Données Réelles : marchespublics.gov.ma

**Tâche :** Collecte de métadonnées d'appels d'offres réels depuis le portail officiel marocain  
**Date :** Novembre 2026  
**Responsable :** P1 (Chef de projet)  
**Statut :** ✅ Métadonnées collectées | ⚠️ DCE ZIP non téléchargeables (WAF)

---

## 1. Contexte

Les données synthétiques créées en T03 servent de corpus d'entraînement et d'évaluation. En complément, ce document décrit la collecte de **métadonnées réelles** depuis le portail officiel des marchés publics marocains afin d'enrichir le projet avec des données authentiques.

**Portail :** [https://www.marchespublics.gov.ma](https://www.marchespublics.gov.ma)  
**Base légale :** Décret n° 2-22-431 relatif aux marchés publics (Art. 48 — publicité obligatoire)

---

## 2. Méthode de Collecte

### 2.1 Exploration du Portail

Le portail utilise le framework **PRADO PHP** avec un mécanisme de session `PRADO_PAGESTATE`. La navigation a été effectuée via requêtes HTTP anonymes.

**URL de recherche des consultations en cours :**
```
https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseAdvancedSearch&AllCons&EnCours&searchAnnCons
```

**URL des avis d'attribution :**
```
https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseAdvancedSearch&AvisAttribution
```

### 2.2 IDs Collectés

| RefId Portail | Dossier Projet | Acheteur | Statut |
|---|---|---|---|
| `1053059` | DCE-REAL-001 | Commune de Kariat Ben Aouda | Scraping ✅ |
| `1051597` | DCE-REAL-002 | ONEE Branche Eau | Scraping ✅ |
| `1050297` | DCE-REAL-003 | ONEE Branche Électricité | Scraping ✅ |
| `1043336` | DCE-REAL-004 | AREP Béni Mellal-Khénifra | Scraping ✅ |
| `1041198` | DCE-REAL-005 | AREP Béni Mellal-Khénifra | Scraping ✅ |

### 2.3 Script PowerShell Utilisé

```powershell
$ids = @("1053059","1051597","1050297","1043336","1041198")
$results = @()
foreach ($id in $ids) {
    $url = "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseConsultationDetail&refCons=$id"
    $resp = Invoke-WebRequest -Uri $url -TimeoutSec 30 -UseBasicParsing
    # Extraction par regex des champs HTML
    # ...
    $results += [ordered]@{ RefId=$id; Acheteur=$acheteur; Objet=$objet; DateLimite=$dateLimite }
}
$results | ConvertTo-Json | Set-Content "dataset/real_tenders_live.json" -Encoding UTF8
```

---

## 3. Données Collectées

### Fichiers Produits

| Fichier | Description |
|---|---|
| `dataset/real_tenders_live.json` | 5 appels d'offres réels (métadonnées complètes) |
| `data/real_attributions_live.json` | Données d'attribution associées (statut en cours) |
| `dataset/dce_real/DCE-REAL-00X/metadata.json` | Métadonnées par dossier (5 fichiers) |

### Champs Extraits par Appel d'Offres

```json
{
  "RefId": "1053059",
  "Acheteur": "Collectivité territoriale de KARIAT BEN AOUDA",
  "Objet": "Travaux d'extension et de renforcement des réseaux d'électricité HTA/BT...",
  "DateLimite": "Jeu 07 Jan 2027 11:00",
  "CautionProvisoire": "50 000 MAD",
  "est_reel": true,
  "source_url": "https://www.marchespublics.gov.ma/..."
}
```

---

## 4. Limitation : DCE ZIP Non Téléchargeables

### Problème Rencontré

Le téléchargement automatique des fichiers DCE ZIP est **bloqué par le WAF (Web Application Firewall)** du portail.

**Message d'erreur reçu :**
```
Accès refusé
Request ID: 14397524885242518144
```

### Architecture Bloquante

```
Navigateur → Formulaire anonyme (nom/prénom) → POST PRADO_POSTBACK_TARGET=completeDownload
                                                        ↓
                                               [WAF BLOCK] ← Détecte automation
```

Le portail exige :
1. Remplissage d'un formulaire avec informations entreprise
2. Click bouton `Télécharger le DCE` (action POST avec token PRADO_PAGESTATE)
3. ⚠️ Le WAF bloque les requêtes automatisées à cette étape

### Solution Manuelle

Pour télécharger manuellement les DCE ZIP depuis le portail :
1. Aller sur [marchespublics.gov.ma](https://www.marchespublics.gov.ma)
2. Rechercher l'appel d'offres par son RefId (ex: `1053059`)
3. Cliquer sur "Télécharger le DCE"
4. Remplir le formulaire d'identification (nom, prénom, ICE, téléphone)
5. Cliquer sur "Télécharger"

**URL directe par RefId :**
```
https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseConsultationDetail&refCons=1053059
```

---

## 5. Stratégie Données Mixte

```
Dataset Projet
├── dataset/dce/              ← 5 DCE SYNTHÉTIQUES (RC + CPS + BPU complets)
│   ├── DCE-2024-001-IT-CLOUD/      → Corpus entraînement
│   ├── DCE-2024-002-BTP-CONSTRUCTION/
│   ├── DCE-2024-003-SERVICES-GARDIENNAGE/
│   ├── DCE-2024-004-FOURNITURES-MEDICALES/
│   └── DCE-2024-005-INGENIERIE-ETUDES/
│
└── dataset/dce_real/         ← 5 DCE RÉELS (métadonnées portail uniquement)
    ├── DCE-REAL-001/         → Validation externe, benchmark
    ├── DCE-REAL-002/
    ├── DCE-REAL-003/
    ├── DCE-REAL-004/
    └── DCE-REAL-005/
```

**Avantages de cette approche hybride :**
- Les DCE synthétiques ont des fichiers RC/CPS/BPU complets → idéaux pour entraînement/annotation
- Les métadonnées réelles prouvent que le système utilise des vrais identifiants de marchés publics
- Conformité avec le Décret 2-22-431 (données publiques)

---

## 6. Vérification de l'Intégrité

```powershell
# Vérifier les 5 dossiers réels
Get-ChildItem "dataset/dce_real" -Recurse -Filter "metadata.json" | Measure-Object
# Expected: 5

# Vérifier le fichier JSON principal
(Get-Content "dataset/real_tenders_live.json" | ConvertFrom-Json).Count
# Expected: 5
```

---

## 7. Références Légales

- **Art. 48, Décret 2-22-431** : Publication obligatoire des appels d'offres sur le portail national
- **Art. 50** : Accès libre aux dossiers de consultation pour les entreprises intéressées
- **Art. 65** : Publicité des résultats d'attribution (avis d'attribution)

Les données collectées sont **publiques** et accessibles sans authentification conformément à ces articles.

