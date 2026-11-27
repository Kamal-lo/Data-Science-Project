# Comparaison OCR et choix provisoire de PaddleOCR

## Objectif et document

Comparer PaddleOCR et Tesseract 5 pour préparer l'extraction des marchés publics
marocains sur un CPS scanné bilingue de 28 pages. Les sources restent locales.

**Vitesse : 28 pages. Précision : zones françaises des pages 1 et 2 seulement.**
Cette synthèse reprend les résultats enregistrés avant nettoyage, sans nouvelle
reconnaissance ni nouveau calcul de CER/WER.

## Environnement et méthode historiques

Windows 10 x64, Python 3.12, CPU, quatre threads par moteur ; images RGB communes
à 200 DPI. PaddlePaddle 3.2.2, PaddleOCR 3.3.2, PaddleX 3.3.13, détecteur
PP-OCRv5_mobile_det et reconnaisseur latin_PP-OCRv5_mobile_rec.
Tesseract 5.5.4, tessdata_fast/fra, OEM 1, PSM 3. MKLDNN et orientation désactivés.

Les temps de reconnaissance excluent rendu, initialisation et sauvegarde.
Tesseract recharge son processus par page ; Paddle conserve son instance dans
chaque passage. Les deux moteurs ont produit 56 mesures au total.

## Résultats enregistrés

| Moteur | Temps des 28 pages | CER global français, pages 1–2 | WER global français, pages 1–2 |
|---|---:|---:|---:|
| PaddleOCR | 2 234,886 s | 1,9293 % | 7,8329 % |
| Tesseract 5 | 97,576 s | 9,3707 % | 17,2324 % |

| Moteur | Page | Temps historique | CER | WER |
|---|---:|---:|---:|---:|
| PaddleOCR | 1 | 49,093 s | 0,9091 % | 5,4945 % |
| PaddleOCR | 2 | 81,018 s | 2,2741 % | 8,5616 % |
| Tesseract | 1 | 1,775 s | 23,2727 % | 21,9780 % |
| Tesseract | 2 | 3,851 s | 4,6712 % | 15,7534 % |

Les références françaises ont été explicitement validées humainement le
18 novembre 2026. Les références et leur manifeste sont conservés localement.
Le protocole utilise les mêmes régions pour les deux moteurs.
Unicode NFC, espaces harmonisés, casse/accents/ponctuation conservés.
Les globaux utilisent 2 177 caractères et 383 mots de référence :
42/204 erreurs de caractères et 30/66 erreurs de mots pour Paddle/Tesseract.
Ce ne sont pas des moyennes de pourcentages.

## Erreurs et choix

Les erreurs observées incluent des omissions de titres et des substitutions de lettres et de chiffres.
Accents, apostrophes, n°, noms propres, chiffres et dates restent sensibles.

Tesseract est nettement plus rapide dans ce protocole. **PaddleOCR est retenu
provisoirement** pour la fidélité observée et le prototype bilingue ; son coût CPU
reste une limite. Ces deux pages ne représentent pas tous les tableaux et DCE.

## Pipeline automatique français–arabe

Le package actif utilise le détecteur mobile et les reconnaisseurs latin et
arabic_PP-OCRv3_mobile_rec, sans régions manuelles. Avant nettoyage, l'intégration
réelle produisait 17 blocs page 1 (13 fr, 2 ar, 2 indéterminés) et 55 page 2
(48 fr, 7 indéterminés), en environ 64,25 s, statut completed_with_review.
Ces temps incluent un traitement différent : double reconnaissance, routage et
segmentation ; ils ne sont pas directement comparables au benchmark historique.

Les propositions d'espacement restent séparées et ne changent pas les lettres.
Les deux en-têtes suivent l'ordre de droite à gauche. Aucun CER/WER arabe n'a été
calculé et aucune référence arabe n'a été validée.

Chaque bloc conserve les deux hypothèses. Le français est une hypothèse
d'écriture latine ; les seuils ne sont pas calibrés. Tifinagh, tampons, logos,
colonnes, tableaux et orientations complexes restent des limites.
Les tests techniques ne valident pas la précision en production.

## Conservation des preuves

Les fichiers sources, les transcriptions, les manifestes avec leurs empreintes
et les sorties OCR sont conservés dans la sauvegarde privée du projet.
Les pourcentages ci-dessus décrivent uniquement le périmètre français approuvé.
