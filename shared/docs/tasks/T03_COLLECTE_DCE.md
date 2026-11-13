# Documentation T03 : Collecte et Constitution du Corpus de DCE

**Projet :** Plateforme IA de réponse aux marchés publics marocains  
**Responsable :** P1 (Chef de projet, ML prédictif et évaluation)  
**Destinataires :** P2 (Document AI & OCR), P6 (Extraction LLM & Go/No-Go)  
**Milestone lié :** Prérequis direct pour T04 (Annotation) et Porte 1 (T05)

---

## 1. Contexte et Objectifs de la Collecte

Dans le cadre des marchés publics au Maroc (régis par le **Décret n° 2-22-431**), le **DCE (Dossier de Consultation des Entreprises)** est le paquet documentaire officiel téléchargé par les candidats depuis le portail national [marchespublics.gov.ma](https://www.marchespublics.gov.ma).

Un DCE complet comprend typiquement :
1. **Le Règlement de la Consultation (RC) :** Fixe les conditions de participation, la caution provisoire, les pièces administratives et techniques requises, les critères d'évaluation et la notation technique.
2. **Le Cahier des Prescriptions Spéciales (CPS) :** Comprend le CCAP (clauses administratives, pénalités, délais, retenue de garantie) et le CCTP (clauses techniques et descriptif des prestations).
3. **Le Bordereau des Prix Unitaires (BPU) / Détail Quantitatif et Estimatif (DQE) :** Tableau chiffré des prestations, unités et quantités.
4. **Les Pièces administratives types :** Modèle de déclaration sur l'honneur (Art. 26), modèle d'acte d'engagement, modèle de cautionnement bancaire.

---

## 2. Typologie du Corpus Constitué (5 DCE Majeurs)

Pour tester de façon rigoureuse la robustesse des briques de **P2 (OCR / Parsing)** et de **P6 (LLM Extraction)**, le corpus couvre les 5 grands secteurs d'achat public marocain avec une diversité de formats :

| Identifiant | Intitulé du Marché | Acheteur Public | Secteur | Type de document | Langues | Lots |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **DCE-2024-001** | Plateforme Cloud et Dématérialisation | Conseil Régional Rabat-Salé-Kénitra | Informatique & Digital | PDF Numérique natif structuré | FR + AR | 1 lot |
| **DCE-2024-002** | Construction Complexe Administratif | Direction Régionale de l'Équipement Casablanca | BTP / Travaux | Scanné 300 DPI, tampons officiels | FR + AR | 2 lots |
| **DCE-2024-003** | Gardiennage et Surveillance | Direction Régionale de la Santé Fès-Meknès | Services & Sécurité | Numérique avec formulaires types | FR + AR | 1 lot |
| **DCE-2024-004** | Acquisition Équipements Médicaux | CHU Ibn Sina Rabat | Fournitures Biomédicales | Numérique avec BPU détaillé | FR + AR | 1 lot |
| **DCE-2024-005** | Études d'Impact et Topographie | Agence du Bassin Hydraulique du Sebou | Études & Ingénierie | Numérique haute exigence technique | FR + AR | 1 lot |

---

## 3. Rôle pour les Travaux de l'Équipe

- **Pour P2 (Tâche T10 & T11) :**
  - **T10 :** Permet de benchmarker `Docling` vs `Marker` sur la conversion PDF/Markdown des DCE natifs (DCE 01, 04, 05).
  - **T11 :** Permet de comparer `PaddleOCR` vs `Tesseract 5` sur les pages scannées bilingues avec tampons administratifs du DCE 02.
- **Pour P6 (Tâche T12) :**
  - Benchmark des LLM (`Llama 3`, `Mistral Large`, `GPT-4o`, `Claude 3.5 Sonnet`) sur des textes de marchés marocains réels.

---

## 4. Outils et Scripts Associés

- **Manifeste :** `dataset/dce_manifest.json` liste l'inventaire complet et les chemins.
- **Script d'intégrité :** `scripts/collect_dce.py --verify` valide l'existence et l'exhaustivité de l'ensemble des fichiers composants de chaque dossier.

