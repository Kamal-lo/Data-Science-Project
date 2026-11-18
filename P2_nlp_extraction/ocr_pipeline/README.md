# API OCR automatique P2

Ce package expérimental accepte un chemin de PDF sans zone prédéfinie. Il utilise
uniquement le détecteur `PP-OCRv5_mobile_det` et les reconnaisseurs français/latin et
arabe déjà présents dans P2. Aucun modèle n’est téléchargé automatiquement.

## Appel par les autres modules

Depuis un programme exécuté avec la racine du projet dans le chemin Python :

```python
from pathlib import Path
from P2_nlp_extraction.ocr_pipeline import extract_pdf, OCRPipelineError

if __name__ == "__main__":
    result = extract_pdf(
        pdf_path=Path("P2_nlp_extraction/data/pdf/test_dce.pdf"),
        output_dir=Path("P2_nlp_extraction/outputs/ocr/my_module"),
        pages=[1, 2],  # None : toutes les pages du PDF fourni
        arabic_spacing="suggest",  # "off" pour désactiver les propositions
        on_error="continue",      # "raise" : OCRPipelineError avec .result
        timeout_seconds=600,
        page_timeout_seconds=240,
    )
    for page in result["pages"]:
        for block in page["blocks"]:
            print(page["page"], block["language"], block["raw_text"])
            if block["needs_review"]:
                print(block["routing_reason"], block["recognition_candidates"])
```

Utiliser le Python 3.12 de `.venv` dans P2, où les dépendances existent. Le package
ne charge pas Paddle dans le processus appelant : l’OCR s’exécute dans un worker
isolé. Les versions actuellement acceptées sont PaddlePaddle 3.2.2, PaddleOCR 3.3.2
et PaddleX 3.3.13 ; leur adaptation bas niveau est confinée dans `models.py`.

Le PDF peut être situé ailleurs et reste lu en lecture seule. `output_dir` doit être
dans P2. Chaque appel crée un sous-dossier unique, sans remplacer les anciennes
exécutions. Les anciens outils de comparaison sont hors du module actif.
Le manifeste des neuf fichiers modèles actifs est `config/model_inventory.json`.

## Fonctionnement

1. Validation du PDF et des pages (numérotation à partir de 1), empreinte SHA-256.
2. Rendu progressif RGB 200 DPI (300 possible). Une seule page en mémoire.
3. Détection automatique des lignes par le modèle mobile, une fois par page.
4. Rectification des polygones détectés et double reconnaissance de chaque ligne.
5. Routage heuristique avec abstention, conservation des deux hypothèses.
6. Ordre géométrique et propositions d’espacement arabe séparées du texte brut.
7. Sauvegardes progressives, exports JSON/TXT UTF-8 et journaux.

Les paramètres du détecteur reprennent le pipeline installé déjà fonctionnel :
`limit_side_len=64`, `limit_type=min`, `max_side_limit=4000`, `unclip_ratio=1.5`,
seuil de détection 0,3 et de boîte 0,6. Le mode CPU `paddle` évite MKLDNN ; quatre
threads par défaut. Aucun modèle d’orientation, de redressement ou de classification
de langue n’est ajouté. Les pages tournées et mises en page complexes restent une limite.

## Contrat des résultats

- Document : `schema_version`, `run_id`, source et empreinte, pages sélectionnées,
  statut, métadonnées des modèles, règles de routage, temps, erreurs et exports.
- Page : `page`, `status`, dimensions, `raw_detection_count`,
  `detected_block_count`, `blocks`, temps par étape, erreurs et avertissements.
- Bloc : `block_id`, numéro de page, `polygon`, `bbox`, `bbox_pdf_points`, langue,
  écriture reconnue, candidat sélectionné, texte brut, hypothèses et scores propres
  aux modèles, raison de routage, besoin de relecture et ordre.
- `arabic_spacing_proposal` : proposition facultative et non validée, détails des
  espaces géométriques et segments reconnus ; `raw_text` reste inchangé.

Les boîtes et polygones sont dans le repère du PNG rendu : pixels, origine en haut
à gauche. `bbox_pdf_points` utilise le rectangle de page **après rotation PDF**,
en points ; ce n’est pas une matrice vers les coordonnées PDF non tournées.
Les coordonnées des mots segmentés restent dans le bloc rectifié, explicitement
identifié : elles ne sont pas présentées comme des coordonnées globales exactes.

Une détection correspond à un seul bloc final. Les deux reconnaissances sont ses
hypothèses, pas deux blocs supplémentaires. Seules des détections presque identiques
(IoU >= 0,90) sont regroupées, avec trace des doublons ; les autres recouvrements
sont conservés et signalés. Un même texte à des positions différentes est conservé.

## Langue : hypothèse, pas vérité garantie

Les règles `script_rules.v1` sont **non calibrées**. Elles examinent la dominance
de l’écriture et des seuils propres à chaque reconnaisseur. Les confiances ne sont
ni des taux d’exactitude ni directement comparées pour décider d’une langue.

- `ar` : hypothèse arabe à écriture arabe dominante et score suffisant.
- `fr` : écriture latine, supposée française dans le couple cible français/arabe.
  Ce n’est pas une distinction fiable entre français, anglais et autres langues latines.
- `mixed` : mélange plausible, relecture nécessaire, aucune fusion arbitraire.
- `und` : langue indéterminée, hypothèses conservées. Un nombre identique reconnu
  par les deux modèles peut être exporté sans lui attribuer une langue.

Quand aucune hypothèse n’est sélectionnée, `raw_text` vaut `None`. Le TXT contient
une marque explicite renvoyant au JSON ; il n’introduit pas de texte supposé correct.
`recognition_candidates.txt` conserve toutes les hypothèses, y compris celles des
blocs non résolus. Le tifinagh, les logos et tampons ne sont pas automatiquement
identifiés sur l’image : les modèles peuvent y halluciner du latin ou de l’arabe.
Leurs sorties ne prouvent jamais la langue originale de ces zones.

L’ordre est de haut en bas, puis RTL pour des blocs arabes d’une même rangée et
LTR pour du latin. Les rangées mixtes et les colonnes non résolues portent des
avertissements. Ce package ne reconstruit ni tableaux ni structure documentaire.

## Erreurs et pages sans texte

Le document prend les statuts `completed`, `completed_with_review`, `partial` ou
`failed`. Une page peut être `ok`, `needs_review`, `near_blank`, `no_text_detected`
ou `error`. `near_blank` est une heuristique de pixels, pas une preuve de page vide ;
une absence de détection ne prouve pas non plus l’absence de texte.

Les PDF natifs et scannés suivent le même chemin de rendu OCR : aucune concaténation
avec la couche texte native, pour éviter les doublons. Sa présence est enregistrée.
Les entrées invalides, protégées ou les options invalides lèvent une exception avant
chargement des modèles. Une limite `max_pixels` protège contre les pages trop grandes.

Les erreurs de reconnaissance par bloc restent visibles. Une erreur de page permet
la suite avec `on_error=continue`. Un crash natif ou délai dépassé arrête l’arbre du
worker ; la page concernée conserve ses résultats partiels et les pages suivantes
peuvent reprendre dans un worker neuf. Une erreur d’initialisation arrête le document.
Les délais sont configurables : document, page et initialisation (120 s par défaut).
`on_error=raise` sauvegarde les résultats disponibles puis lève `OCRPipelineError`.

## Fichiers

- `document.json` : résultat structuré principal, hypothèses incluses.
- `document_raw.txt` : texte sélectionné brut et marques des blocs indéterminés.
- `document_spacing_proposals.txt` : mêmes textes, avec seules propositions acceptées.
- `recognition_candidates.txt` : tous les textes bruts des deux modèles, étiquetés.
- `pages/` : sorties progressives et détections ; `images/` : rendus utilisés.
- `models.json`, `request_*.json`, `worker_*.log` : paramètres et diagnostics.

Le temps total renvoyé est mesuré jusqu’avant l’export final ; les temps par page
séparent rendu, détection, reconnaissances, routage et propositions d’espacement.
Le temps de première page comprend le chargement initial, aussi enregistré séparément.
Ne pas additionner une seconde fois ces mesures imbriquées.

## Vérification et limites

```powershell
& .\P2_nlp_extraction\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s .\P2_nlp_extraction\tests -p test_automatic_pipeline.py -v
& .\P2_nlp_extraction\.venv\Scripts\python.exe -B -X utf8 .\P2_nlp_extraction\scripts\run_automatic_ocr_sample.py
```

Le second appel traite seulement les pages 1 et 2, sans zone manuelle. Les tests
techniques créent des fixtures synthétiques temporaires sous `.cache/ocr_pipeline_tests/`,
nettoyées automatiquement ; elles ne constituent pas un corpus de précision.
Aucun CER/WER arabe n’est calculé.

Avant production : calibrer et évaluer le routage sur des documents réels annotés,
tester paragraphes arabes longs, tifinagh/tampons, nombres et noms propres, PDF
tournés, colonnes, tableaux, charge mémoire et robustesse des délais sous Windows.
Les tests unitaires seuls ne valident ni la fidélité OCR ni la couverture des langues.
