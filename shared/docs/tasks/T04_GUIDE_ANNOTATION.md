# Documentation T04 : Guide et Règles d'Annotation de la Vérité Terrain

**Projet :** Plateforme IA de réponse aux marchés publics marocains  
**Responsable :** P1 (Chef de projet, ML prédictif et évaluation)  
**Destinataires :** P2 (OCR & Parsing), P6 (Extraction LLM), P4 (Conformité)  
**Milestone lié :** Entrée obligatoire pour figer la Porte 1 (T05)

---

## 1. Principes Directeurs d'Annotation

Pour garantir une évaluation scientifique, reproductible et exempte de biais lors des benchmarks des modules d'IA (OCR de P2, Extraction LLM de P6, Conformité de P4), l'annotation de la vérité terrain suit quatre règles cardinales :

1. **Traçabilité stricte (Source Grounding) :**
   Aucun champ n'est annoté sans son triplet d'ancrage documentaire :
   - `source_fichier` (ex: `RC_Reglement_Consultation.txt`)
   - `article_ou_page` (ex: `Article 7`)
   - `citation_source` (extrait textuel exact, sans modification)
2. **Normalisation canonique :**
   - **Dates et Heures :** Format strict ISO 8601 avec fuseau horaire marocain : `YYYY-MM-DDTHH:MM:SS+01:00`.
   - **Montants monétaires :** Nombres à virgule flottante en Dirhams marocains (MAD), débarrassés de tout formatage de texte (`"95 000,00 MAD"` $\rightarrow$ `95000.0`).
   - **Délais :** Entiers numériques stricts exprimés en mois ou jours (`"dix (10) mois"` $\rightarrow$ `10`).
3. **Bilinguisme Arabe / Français :**
   L'annotation consigne systématiquement l'intitulé officiel en français et sa traduction/version arabe telle que stipulée dans l'avis ou l'en-tête du RC.
4. **Exhaustivité des Pièces Administratives :**
   La liste de contrôle (`pieces_requises_checklist`) détaille les 3 sous-dossiers requis par le Décret n° 2-22-431 : Dossier Administratif, Dossier Technique, Offre Financière.

---

## 2. Définition des Champs Clés Annotés

| Champ | Type cible | Règle d'évaluation | Impact en production |
| :--- | :--- | :--- | :--- |
| `date_limite_remise_plis` | ISO DateTime | Exact Match (Tolérance 0 min) | Rejet automatique si dépôt après l'heure limite |
| `caution_provisoire_mad` | Float (MAD) | Exact Match ($\Delta = 0$) | Rejet irrévocable du pli si caution erronée (Art. 22) |
| `estimation_maitre_ouvrage`| Float (MAD) | Tolérance 0.01 MAD | Base du calcul des seuils excessif / anormalement bas |
| `exigences_techniques` | List[String] | Soft F1 / Recouvrement sémantique | Filtre Go/No-Go (Module B2) |
| `pieces_requises_checklist`| List[String] | Faux négatifs strictement interdits ($FN = 0$) | Porte 3 (Conformité anti-rejet) |
| `bareme_technique` | Object | Exactitude des notes max et seuils | Calcul de la note éliminatoire |

---

## 3. Fichiers et Outils d'Annotation

- **Schéma JSON de validation :** `schemas/ground_truth.schema.json`
- **Fichiers de vérité terrain annotés :**
  - `dataset/annotations/DCE-2024-001_ground_truth.json` (IT & Cloud)
  - `dataset/annotations/DCE-2024-002_ground_truth.json` (BTP & Construction, 2 lots)
  - `dataset/annotations/DCE-2024-003_ground_truth.json` (Gardiennage & Sécurité)
  - `dataset/annotations/DCE-2024-004_ground_truth.json` (Fournitures Médicales)
  - `dataset/annotations/DCE-2024-005_ground_truth.json` (Ingénierie & Études)
- **Script de contrôle automatisé :** `scripts/validate_annotations.py`

