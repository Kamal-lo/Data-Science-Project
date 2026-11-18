# Comparaison OCR et choix provisoire de PaddleOCR

## Objectif et document

Comparer PaddleOCR et Tesseract 5 pour préparer l'extraction des marchés publics
marocains. Le PDF local test_dce.pdf est un CPS scanné de 28 pages : jardinage de
l'Institut supérieur de la magistrature, AO 02/ISM/2024, principalement français,
avec en-têtes arabe/tifinagh et tampons.
SHA-256 : `e7b529f09720b63c07f6fb728d51a8ded9e8c527162d91591770241cf08e5bb1`.

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
chaque passage. Le run consolidé `20261113T111045_112432Z_complete` rassemble
un passage et sa reprise : 56 lignes de mesures réussies.

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
18 novembre 2026 ; manifeste et copies scellées sont conservés dans
[références et manifeste partagés](../data/ground_truth/pages_1_2/README.md). Mêmes régions pour les deux moteurs ;
Unicode NFC, espaces harmonisés, casse/accents/ponctuation conservés.
Les globaux utilisent 2 177 caractères et 383 mots de référence :
42/204 erreurs de caractères et 30/66 erreurs de mots pour Paddle/Tesseract.
Ce ne sont pas des moyennes de pourcentages.

## Erreurs et choix

Paddle conserve mieux les titres et rubriques sur cet échantillon, mais produit
notamment mats pour mars et Insctit pour Inscrit. Tesseract omet des titres et
produit 02/1SM/2024, petsonnel, Titulaite et du bruit de formulaire.
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

Bruts arabes : المملكةالمغربية et المعهدالعاليللقضاء.
Les propositions d'espacement restent séparées et ne changent pas les lettres.
Les deux en-têtes suivent l'ordre de droite à gauche. Aucun CER/WER arabe n'a été
calculé et aucune référence arabe n'a été validée.

Chaque bloc conserve les deux hypothèses. Le français est une hypothèse
d'écriture latine ; les seuils ne sont pas calibrés. Tifinagh, tampons, logos,
colonnes, tableaux et orientations complexes restent des limites.
Les tests techniques ne valident pas la précision en production.

## Preuves et suite

Les anciens benchmarks, sorties, rapports détaillés et interfaces ont été
sauvegardés et vérifiés hors de P2 avant suppression du dossier actif :
`../../_p2_cleanup_backup_20261118T220341Z/`.
Son manifeste répertorie les fichiers et leurs SHA-256. Cette sauvegarde est
locale, absente de GitHub ; conserver son ZIP pour restaurer l'ancien atelier.
Le ZIP `p2_before_cleanup.zip` et son `backup_manifest.json` restent disponibles
sur la machine ayant effectué le nettoyage ; ils ne sont pas fournis par un clone.
Les chemins `source_hashes` du manifeste Ground Truth sont conservés pour leur
traçabilité : les sources correspondantes sont dans ce ZIP avec leurs chemins
relatifs à P2. Le PDF existe également dans `P2_nlp_extraction/data/pdf/`, hors Git.
Les références validées et leur manifeste sont partagés ; les résultats OCR
historiques et les sorties d'intégration sous `outputs/` restent locaux.

Une seule synthèse reste dans le module. Le contrôle après nettoyage conserve
ses résultats dans le nouveau dossier d'intégration sous
`outputs/ocr/automatic_sample/`.
Contrôle effectué après nettoyage : **17 tests techniques réussis**, `pip check`
sans dépendance cassée, puis extraction réelle des seules pages 1 et 2 en
**71,547 s**, sans erreur d'exécution. Résultat : 17 blocs (13 fr, 2 ar, 2 und)
sur la page 1 et 55 blocs (48 fr, 7 und) sur la page 2, toujours
`completed_with_review`. Run : `20261118T221046_740048Z_de048b93`.
Les exports JSON/TXT UTF-8 et les hypothèses bilingues ont été vérifiés.
Avant production : corpus réel annoté plus large, paragraphes arabes longs,
validation des espaces, du routage et de l'ordre de lecture, PDF mixtes/tournés,
charge mémoire et coût CPU.
