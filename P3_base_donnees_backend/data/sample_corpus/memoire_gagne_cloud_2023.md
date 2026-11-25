# Mémoire Technique Gagné — Plateforme Cloud Souveraine & Dématérialisation (Marché 07/2023/ADD)
إرساء منصة سحابية سيادية ورقمنة المساطر الإدارية

## 1. Approche Méthodologique et Phasage d'Exécution
Atlas Cloud & Systèmes applique une démarche hybride combinant gouvernance structurée par jalons contractuels (conforme au CCAG-EMO et au Décret n° 2-22-431) et itérations agiles encadrées avec le Maître d'Ouvrage.

- **Phase 1 — Cadrage et Spécifications (2 mois)** : Ateliers de cartographie des processus métiers, dossier d'architecture technique (DAT), plan d'assurance qualité (PAQ) et validation en Comité de Pilotage.
- **Phase 2 — Infrastructure Cloud Souveraine et Conteneurs (3 mois)** : Déploiement d'un cluster Kubernetes durci (CIS Benchmarks), cloisonnement réseau Zero Trust, sauvegarde chiffrée AES-256 et supervision Prometheus/Grafana hébergés au Maroc.
- **Phase 3 — Développement des Modules de Dématérialisation (3 mois)** : Portail citoyen et entreprises bilingue (Français / Arabe RTL), moteur de workflow paramétrable, interfaçage API REST sécurisé et journalisation probante.
- **Phase 4 — Recette, Audit de Sécurité DNSSI et Pré-production (1 mois)** : Exécution du cahier de recette (VA/VSR), tests de charge et tests d'intrusion boîte noire/grise alignés sur la Directive Nationale de la Sécurité des Systèmes d'Information (DNSSI).
- **Phase 5 — Mise en Production, Formation et Transfert de Compétences (1 mois)** : Bascule contrôlée sans interruption, formation certifiante des administrateurs et agents (supports FR/AR) et remise de la documentation d'exploitation.
- **Phase 6 — Garantie et Support 24/7 (12 mois)** : Centre de services basé à Rabat avec astreinte 24h/24 et 7j/7, GTR de 2 heures pour incidents critiques (P1) et maintenance corrective/évolutive.

## 2. Architecture Technique Souveraine
L'architecture déployée repose sur une pile 100 % souveraine et réversible sans verrouillage éditeur :
- Orchestration de conteneurs haute disponibilité multi-nœuds (disponibilité cible 99,9 % vérifiée lors de la VSR).
- Couche d'authentification forte SSO / OIDC avec gestion fine des rôles (RBAC) et traçabilité complète des actions.
- Hébergement conforme aux exigences de localisation des données au Royaume du Maroc et à la Loi n° 09-08 (CNDP).

## 3. Gestion des Risques Opérationnels
Les risques majeurs identifiés sur les projets publics de dématérialisation (retard de validation des spécifications, reprise de données hétérogènes, résistance au changement) sont couverts par :
1. Un jalon de gel fonctionnel co-signé dès la semaine 6 ;
2. Des scripts automatisés de migration et contrôle d'intégrité avant bascule ;
3. Un plan d'accompagnement au changement incluant des sessions pratiques par profil utilisateur.
