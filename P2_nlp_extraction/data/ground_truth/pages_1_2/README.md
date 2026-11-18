# Références françaises conservées — pages 1 et 2

Les deux pages portent une validation humaine explicite enregistrée le
18 novembre 2026 dans `manifest.json`. Les copies scellées sont dans `validated/` ;
leurs noms contiennent les SHA-256. Les fichiers page_001.txt et page_002.txt
restent les transcriptions de travail, distinctes des copies validées.
Ne jamais valider automatiquement une nouvelle transcription.

Le périmètre français est défini dans le manifeste : mêmes rectangles pour les
deux anciens moteurs, champs vides laissés vides, traits de formulaire absents
de la référence. En-têtes arabe/tifinagh, logos, tampons et pagination exclus.
Modifier le texte ou le périmètre exige une nouvelle validation humaine.

`relecture_francaise.md` conserve les notes de préparation antérieures à la
validation ; le manifeste fait foi pour le statut final. Ses chemins et empreintes
décrivent les sources historiques sauvegardées hors de P2 avant leur retrait.
Pour reproduire l'ancienne évaluation, restaurer l'atelier et ses données depuis
la sauvegarde du nettoyage.

## Disponibilité après clonage

Le [manifeste partagé](manifest.json), les transcriptions de travail et les deux
copies dans `validated/` restent dans Git. Les chemins de `source_hashes` sont
relatifs à `P2_nlp_extraction/` et sont volontairement conservés sans réécriture.
Les 15 sources et leurs empreintes ont été retrouvées dans le manifeste de la
sauvegarde locale `_p2_cleanup_backup_20261118T220341Z/`, située à la racine du dépôt.
Elles sont récupérables dans `p2_before_cleanup.zip` sous ces mêmes chemins.
Le PDF est encore présent localement dans `data/pdf/test_dce.pdf`, mais n'est pas
partagé par Git. Les 14 autres sources historiques ne sont plus dans le dossier
actif. La sauvegarde, le PDF et les sorties OCR ne sont pas fournis par un clone :
demander leur transmission séparée au membre qui les conserve si une reproduction
de l'ancienne comparaison est nécessaire. L'API actuelle n'utilise pas ces sources.

Ces références restent disponibles pour les futures évaluations. Elles ne sont
ni une Ground Truth arabe ni une validation du routage automatique.
