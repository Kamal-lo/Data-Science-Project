# P2 — Lire et préparer les documents DCE

P2 reçoit un PDF, DOCX ou ZIP et produit du texte Markdown, des sections DCE,
des tableaux/BPU et des résultats d'évaluation en JSON/CSV. Les textes incertains,
les erreurs et leur provenance restent visibles. Aucune sortie n'est validée
humainement de façon automatique. Ce module prépare les données ; il ne rédige
pas le dossier final de réponse au marché.

## Organisation

```text
P2_nlp_extraction/
├── app.py                  Interface locale : dépôt, suivi, téléchargements
├── pipeline.py             Un appel pour enchaîner les étapes
├── storage.py              Objets locaux identifiés par SHA-256 (contrat P6)
├── document_ingestion/     T23 : ZIP, PDF/DOCX, contrôles d'entrée
├── document_conversion/    T24 : extraction native ou raccordement OCR
├── ocr_pipeline/           T25 : modèles français/arabe, repli, protections
├── document_segmentation/  T26 : RC, CPS, CCAP, CCTP, BPU, articles
├── table_extraction/       T27 : cellules et lignes de prix
├── quality_evaluation/     T28 : CER et qualité des sections
├── config/                 Schémas JSON et empreintes des modèles
├── scripts/                Utilitaires communs des traitements
├── tests/                  Tests synthétiques et réutilisation de résultats réels
├── data/                   PDF et références humaines à préserver
└── outputs/                Bibliothèque, traitements et preuves locales
```

Les anciens résultats restent à leur emplacement pour conserver les liens de
provenance. Les nouveaux traitements sont regroupés dans `outputs/runs/` ;
`outputs/library/` conserve les originaux. Un dossier par traitement est nécessaire
pour éviter les écrasements. Les tests nettoient leurs propres temporaires.
Modèles, données confidentielles, outputs et environnement restent hors de Git.
Les contrats API sont réunis ci-dessous. Le rapport de comparaison historique
reste dans `reports/`.

## Installation

Pour vérifier le parcours sans OCR après installation, déposer
`P2_nlp_extraction/data/examples/BPU-synthetique.docx` dans l'interface.
L'onglet **Tableaux et BPU** affiche le nombre de cellules et de lignes de prix
exportées, avec un aperçu limité à 20 lignes par fichier. Le DOCX contient
une ligne fictive de béton (« خرسانة ») dont le montant attendu est `250,50`.

Depuis la racine du dépôt : Windows 10, Python 3.12 x64.
L'environnement `.venv` existant peut être réutilisé sur la même machine.
Sur une autre machine, recréer l'environnement à partir des commandes ci-dessous.
Pour le parcours OCR, installer d'abord le Microsoft Visual C++ Redistributable
v14 **x64** pour Windows 10/11 x64. Il fournit le runtime natif utilisé par
Paddle. [Téléchargement officiel Microsoft](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).

```powershell
py -3.12 -m venv P2_nlp_extraction/.venv
$python = '.\P2_nlp_extraction\.venv\Scripts\python.exe'
$lock = 'P2_nlp_extraction/requirements-lock.txt'
& $python -m pip install --no-deps paddlepaddle==3.2.2 --index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/ -c $lock
& $python -m pip install -r P2_nlp_extraction/requirements.txt -c $lock
& $python -m pip check
& $python -I -B -c "from paddle.base import libpaddle"
```

Pour une installation réduite, utiliser le même fichier de contraintes avec
`requirements-core.txt` (API natives), `requirements-ui.txt` (interface et
API natives) ou `requirements-conversion.txt` (conversion avec PaddleOCR).
L'installation complète ci-dessus réunit l'interface et la conversion.

Aucune installation ni aucun téléchargement de modèle n'est lancé par le programme.
Les dépendances natives, Streamlit et Paddle CPU ont été installés et vérifiés
avec `pip check` sous Python 3.12 x64 sur Windows. S'il faut réinstaller le
projet, préférer un chemin racine court : certains fichiers du paquet Paddle
dépassent la limite de Windows lorsque les chemins longs sont désactivés.
Streamlit reste facultatif pour les appels aux API Python.

Sous Windows x64, la bibliothèque `mkldnn.dll` de Paddle dépend du runtime
Microsoft OpenMP `VCOMP140.DLL`. Il doit être accessible au processus enfant
depuis une session Windows ordinaire. Le test `test_libpaddle_import_without_developer_path`
vérifie cet import en limitant le PATH au dossier système. Sur la machine de
validation, une copie locale signée par Microsoft se trouve dans
`.venv/Lib/site-packages/paddle/libs/`. En recréant l'environnement, vérifier
à nouveau ce prérequis natif, distinct des dépendances contrôlées par `pip check`.

L'OCR exige PaddlePaddle 3.2.2, PaddleOCR 3.3.2 et PaddleX 3.3.13. Copier les trois
modèles déjà disponibles dans `P2_nlp_extraction/.cache/paddlex/official_models/` :
`PP-OCRv5_mobile_det`, `latin_PP-OCRv5_mobile_rec`, `arabic_PP-OCRv3_mobile_rec`.
Leurs fichiers sont vérifiés par `config/model_inventory.json`. Aucun détecteur server.
Pour vérifier les versions et les empreintes avant un premier OCR, exécuter
`& $python -B -c "from P2_nlp_extraction.ocr_pipeline.models import preflight; preflight()"`.

## Docker Linux · CPU

Depuis la racine du dépôt, sélectionner le moteur **Linux/amd64** de Docker
Desktop. Le contexte de construction est uniquement `P2_nlp_extraction`.
Les modèles, PDF, références de relecture, sorties et environnements locaux
sont exclus par la liste d'inclusion de `.dockerignore`.

```powershell
docker build --platform linux/amd64 -t p2-streamlit:cpu-3.12 P2_nlp_extraction
$modeles = (Resolve-Path P2_nlp_extraction/.cache/paddlex/official_models).Path
$documents = (Resolve-Path P2_nlp_extraction/data/pdf).Path
docker run -d --name p2-streamlit --init --platform linux/amd64 `
  --cgroupns=private --memory=4g --memory-swap=4g --cpus=2 `
  -p 127.0.0.1:8501:8501 `
  --mount "type=bind,source=$modeles,target=/srv/P2_nlp_extraction/.cache/paddlex/official_models,readonly" `
  --mount "type=bind,source=$documents,target=/documents,readonly" `
  --mount type=volume,source=p2-resultats,target=/srv/P2_nlp_extraction/outputs `
  p2-streamlit:cpu-3.12
docker exec p2-streamlit python -c "from P2_nlp_extraction.ocr_pipeline.models import preflight; print(preflight()['versions'])"
```

Sur un nouveau poste, recevoir les **trois répertoires** de modèles via le
canal privé de l'équipe. Placer leurs neuf fichiers sous le répertoire
`$modeles` en conservant les noms de `config/model_inventory.json`.
La commande `preflight` vérifie les empreintes des poids, configurations
et graphes. Pour `$documents`, choisir un répertoire existant de PDF,
DOCX ou ZIP autorisés. L'interface permet toujours le téléversement depuis
le navigateur. Elle est accessible sur [localhost:8501](http://localhost:8501).
L'image utilise le compte non privilégié `p2` (UID 10001).

Pour exécuter le pipeline et lire un suivi depuis le conteneur :

```powershell
docker exec p2-streamlit python -m P2_nlp_extraction.pipeline /documents/test_dce.pdf --ocr auto --pages 1
# Remplacer <id> par le job_id que la commande précédente affiche.
docker exec p2-streamlit python -c "from P2_nlp_extraction.pipeline import load_delivery; print(load_delivery('outputs/runs/<id>/job.json')['status'])"
docker stop p2-streamlit
docker start p2-streamlit
```

Le volume `p2-resultats` conserve originaux, suivis et exports JSON/CSV
après recréation du conteneur. Il peut contenir des données confidentielles.
Les autres modules peuvent monter ce même volume en lecture seule au chemin
`outputs` du paquet P2 et utiliser `load_delivery` et `resolve_export` pour
vérifier identité, taille et SHA-256. Les API Python restent les points
d'intégration. Le Compose de P6 sur `feature/socle-t08` orchestre PostgreSQL,
Redis, une API et un worker. L'ajout de P2 à cette orchestration reste à
convenir avec P6.

Sous Linux, l'OCR requiert un **cgroup v2 privé avec une limite mémoire finie**.
Le noyau borne tout le conteneur. Le superviseur mesure séparément la mémoire
proportionnelle (PSS) du worker OCR et de ses descendants et interrompt son
groupe de processus si le budget OCR de 1 536 Mio est dépassé. Cette mesure
échantillonnée peut manquer un pic bref. Les délais d'initialisation, de page,
de repli et de document restent actifs. Sous Windows la protection reste le
Job Object. Prévoir de la mémoire pour Docker Desktop et le système hôte en
plus des 4 Gio alloués au conteneur.

## Lancer et utiliser

```powershell
.\P2_nlp_extraction\.venv\Scripts\python.exe -B -m streamlit run P2_nlp_extraction/app.py --server.address 127.0.0.1 --server.maxUploadSize 25 --browser.gatherUsageStats false
# Ou, sans interface et sans OCR réel :
.\P2_nlp_extraction\.venv\Scripts\python.exe -B -m P2_nlp_extraction.pipeline chemin/vers/document.pdf --pages 1
```

L'interface accepte 25 Mio maximum, affiche les étapes et leurs erreurs, permet
de reprendre un suivi depuis `outputs/.../job.json` et de télécharger les exports.
L'historique présente les 20 traitements les plus récents. Un traitement repris
affiche son lien d'origine à côté de son état courant.
Elle montre le texte, les sections et un aperçu des tableaux et du BPU.
Sélectionner un export pour le préparer au téléchargement (64 Mio par fichier).
Le mode `auto`, sélectionné par défaut dans l'interface, choisit page par page.
PyMuPDF extrait directement le texte natif exploitable. PaddleOCR reconnaît
le français et l'arabe si la page est scannée, si le texte natif est
inexploitable ou si la page contient aussi de l'image à lire. Pour une page
hybride, P2 conserve le texte natif utile et rapproche les blocs OCR.
Le repli par prétraitement réutilise PaddleOCR, seul moteur OCR de P2.
L'API de haut niveau garde son mode sans OCR par défaut. Passer
`ConversionOptions(ocr_mode="auto")` en Python ou `--ocr auto` en ligne de
commande pour activer le même routage. Les scans sont traités par lots de
quatre dans l'interface, avec repli borné. Une sélection
vide couvre toutes les pages, dans la limite de 30 pages nécessitant un OCR
par PDF. Chaque page OCR dispose au plus de 240 s et le plafond du worker
reste à 1 536 Mio. Il faut 2 Gio de RAM disponible pour démarrer sur l'interface.
Le mode `reuse_only` permet de reprendre un résultat OCR du même PDF.
La détection est limitée à 1 280 pixels ; les crops de reconnaissance restent
issus du rendu original à 200 dpi. Les rendus de scans sont conservés dans
les sorties OCR avec leurs coordonnées et les hypothèses de reconnaissance.
Pour DOCX/ZIP contenant des DOCX, laisser les numéros de pages vides : un DOCX
n'a pas de pagination physique stable. Streamlit est local, sans authentification ;
ne pas exposer cette interface sur Internet.

```python
from P2_nlp_extraction.pipeline import load_job, run_pipeline
from P2_nlp_extraction.storage import resolve_export

job = run_pipeline("mon_document.pdf")  # Également DOCX ou ZIP. OCR désactivé.
print(job["status"], job["job_path"])
for document in load_job(job["job_path"])["documents"]:
    export = document["outputs"].get("bpu_json")
    if export:
        print(resolve_export(export))  # Vérifie la taille et le SHA-256.
```

Pour lire un PDF scanné avec PaddleOCR, utiliser le profil Windows du mode
automatique. Une page disposant d'un texte natif utilisable suit la voie native.

```python
from P2_nlp_extraction.document_conversion import ConversionOptions
from P2_nlp_extraction.document_conversion.models import AUTO_LIMITS, DELIVERY_OCR_MAX_SIDE
from P2_nlp_extraction.pipeline import run_pipeline

job = run_pipeline(
    "mon_document.pdf",
    options=ConversionOptions(ocr_mode="auto", ocr_detector_max_side=DELIVERY_OCR_MAX_SIDE),
    conversion_limits=AUTO_LIMITS,
)
```

Pour rejouer une page à partir d'un résultat OCR existant du même PDF,
utiliser `reuse_only`. Le chemin du résultat est relatif à P2.

```python
from P2_nlp_extraction.document_conversion import ConversionOptions

options = ConversionOptions(
    ocr_mode="reuse_only", pdf_pages=(1,),
    ocr_results=("outputs/mon_ocr/document.json",),
)
# run_pipeline("mon_document.pdf", options=options)
```

Le suivi `load_job(path)` se lit sans réexécuter le pipeline.
`resume_job(path)` crée un nouveau suivi pour la source stockée. Les budgets
d'ingestion et de conversion du suivi sont conservés pour un PDF comme pour
un ZIP. L'appelant peut fournir un nouveau budget de conversion. Pour un ZIP,
P2 enregistre le manifeste puis chaque membre terminé. La reprise vérifie les
empreintes et réutilise les exports des membres terminés et compatibles.
Un membre partiel peut reprendre avec les pages OCR disponibles et compatibles.
`resume_job(path, source_path="dce_corrige.zip")` compare les chemins et les
empreintes pour identifier les membres ajoutés, supprimés et modifiés.
Cette option est aussi disponible dans l'interface. Conserver les anciens
exports référencés par le nouveau suivi.
Si le suivi initial utilisait des références humaines, conserver ses métriques
et relancer l'évaluation séparément sur les sorties compatibles. La reprise
automatique ne reprend pas les annotations humaines du suivi initial.

## API publiques

Importer les fonctions depuis `P2_nlp_extraction.<package>` ou
`P2_nlp_extraction.pipeline`, depuis la racine du dépôt. Les options et budgets
sont regroupés dans les objets `*Options` et `*Limits` des packages.

| API | Entrée et paramètres usuels | Résultat |
|---|---|---|
| `store_document(source_path)`, `resolve_document(record)` | Fichier local ou descripteur SHA-256 | Descripteur portable ou chemin vérifié |
| `ingest_path(source_path, output_dir=None, dce_id=None, limits=None)` | PDF, DOCX ou ZIP | Manifeste T23, éligibilité et chemins relatifs |
| `convert_ingestion(manifest_path, options=...)`, `convert_document(manifest_path, file_id, options=...)` | Manifeste T23 et, si nécessaire, identifiant de fichier | Documents JSON/Markdown, textes natifs/OCR, erreurs et provenance |
| `extract_pdf(pdf_path, output_dir=None, pages=..., detector_max_side=...)` | PDF, pages physiques à partir de 1, réglages OCR | JSON OCR et diagnostics, boîtes image et PDF, hypothèses bilingues |
| `segment_document(document_json, output_dir=None, markdown_path=None)` | Document finalisé T24, Markdown facultatif | Sections JSON/Markdown et blocs sources |
| `extract_tables(conversion_json_path, segmentation_json_path=None, output_dir=None)` | T24 et contexte T26 vérifié facultatif | Tableaux et BPU JSON/CSV |
| `evaluate_quality(ocr_json_path=..., reference_manifest_path=..., segmentation_json_path=..., section_annotations_path=...)` | Sorties finalisées et références approuvées compatibles | CER par page/langue, précision/rappel/F1 de découpage et rapport |
| `run_pipeline(source_path, options=..., progress=...)` | PDF/DOCX/ZIP. OCR désactivé par défaut | Suivi `job.json`, états et descripteurs d'exports |

Les options après les chemins principaux se passent par nom. Les sorties des
étapes sont confinées à P2. Les documents restent des entrées non fiables :
les contrôles de formats, d'intégrité, de taille et de temps restent actifs.
Le worker OCR tourne dans un Job Object Windows, avec repli borné et
conservation des points de reprise. Les sorties d'un document partiel restent
accessibles et signalées comme telles.

Les grilles fermées reconnues sur un scan gardent les boîtes et identifiants
OCR par cellule. Une cellule indéterminée reste `null`. Les continuations
multipages sont des candidats et restent séparées. Importer les valeurs CSV
comme texte pour conserver les zéros initiaux et éviter les formules de tableur.
Pour une grille irrégulière, le JSON conserve les boîtes candidates et les
identifiants OCR. Si les bords concordent, JSON et CSV livrent les lignes et
les cellules observées avec leurs coordonnées. Les fusions indiquent
`row_span` et `column_span`. Une position couverte pointe vers l'ancre via
`covered_by` et garde une valeur nulle. Seuls les fragments attribuables à
une seule boîte contribuent au texte. Le tableau reste partiel et les prix
ne sont pas déduits de ces grilles.
Les traits courts confirmés sur le scan sont conservés dans
`raster_verified_dividers` avec les contours initiaux. Les fragments proches
de plusieurs cellules sont signalés par `ambiguous_ocr_block_ids`. Quand
PaddleOCR s'abstient, les propositions figurent dans `ocr_alternatives` et la
valeur reste nulle dans le JSON et vide dans le CSV.
Le CER compare uniquement une référence de même PDF, page, langue et périmètre.
Les annotations de découpage doivent correspondre au document T24 et à son
empreinte. Une métrique indisponible reste `not_evaluated`.

## Les étapes et les échanges avec l'équipe

1. `storage.store_document()` conserve l'original sans écrasement, calcule son
   SHA-256 et retourne `p2.storage.v1` : identifiant, nom original, taille, empreinte
   et chemin relatif à P2. `resolve_document()` revérifie l'identité avant lecture.
2. T23 contrôle les chemins ZIP, tailles, compression, corruption et formats réels.
   Seuls les fichiers `ready` et `eligible_for_t24` d'une ingestion terminée vont à T24.
   Les fichiers ignorés d'une archive traitée restent nommés dans les avertissements.
3. T24 extrait le texte natif. Pour les scans, il réutilise les résultats fournis
   ou signale qu'un OCR est nécessaire. Une erreur conserve les résultats partiels.
4. T26 repère titres et articles, sans promouvoir les fragments masqués des tableaux.
5. T27 exporte les cellules déjà structurées ; il n'invente ni prix ni cellule manquante.
6. T28 compare aux références humaines validées, si disponibles. Une page OCR
   `processing` reste non évaluée ; une page finalisée d'un document partiel peut
   être évaluée. Les évaluations de plusieurs lots OCR restent séparées.

Chaque job fournit `document.md/json`, `sections.md/json`, `tables.json/csv`,
`bpu.json/csv` et les métriques disponibles. Son `job.json` contient les chemins
relatifs, empreintes, identifiants, étapes, durées, erreurs et avertissements.
Le format est défini dans `config/pipeline.schema.json` ; il ne remplace pas les
schémas T23 à T28. Les exports gardent coordonnées, textes bruts et provenance.
Les propositions d'espacement arabe restent séparées et non appliquées arbitrairement.

`load_delivery(job_path)` fournit le suivi après vérification de l'original et
des exports. La conversion doit correspondre au membre annoncé et les JSON
de sections, tableaux et BPU doivent référencer l'empreinte de cette conversion.
Si le suivi contient les deux formats, le CSV des tableaux ou du BPU doit
correspondre au contenu de son JSON.
Pour accéder à un fichier, transmettre son descripteur à
`resolve_export()`. L'identifiant du traitement est `job_id`. Dans un ZIP,
`member_id` dépend du chemin du membre et de son SHA-256 et reste stable si ces
deux valeurs sont inchangées. Chaque consommateur conserve le statut, les
avertissements et les erreurs avec les résultats. Les descripteurs restent
relatifs à la racine P2 et ne font pas office d'autorisation d'accès.

Le JSON de conversion fournit `pages[].graphics` avec les rectangles,
les dimensions des images raster et les indices des objets raster ou des
opérations vectorielles repérées. Le PDF original conserve les pixels et
les tracés. Le tableau de repères `text_locators` indexe les dates numériques
et les références à libellé explicite. `span` donne des indices de caractères
dans `raw_text` du bloc source (fin exclue) et `bbox` correspond au bloc
entier. La date ou le numéro doit être interprété selon son contexte.
Ces deux champs facultatifs préservent la lecture des anciennes conversions.

Pour brancher un lecteur sur un traitement existant :

```python
import json
from P2_nlp_extraction.pipeline import load_delivery
from P2_nlp_extraction.pipeline import resolve_member_source
from P2_nlp_extraction.storage import resolve_export

job = load_delivery("outputs/runs/identifiant/job.json")
for document in job["documents"]:
    original = resolve_member_source(job["job_path"], document["member_id"])
    print(document["member_id"], original.name)
    if entry := document["outputs"].get("bpu_json"):
        bpu = json.loads(resolve_export(entry).read_text(encoding="utf-8"))
        print(document["member_id"], document["status"], len(bpu["tables"]))
```

| Équipe | À transmettre ou à définir |
|---|---|
| P1 | Le CER peut consommer les textes comparés de P2. Pour Exact Match et F1, P1 doit convenir avec P2 d'un mapping des blocs, sections et BPU vers le dictionnaire plat des champs métier et les valeurs normalisées du référentiel. |
| P3/P5 | P3 doit associer son identifiant DCE au SHA-256 de la source et au `job_id`, puis exposer les statuts, erreurs et exports via son API. P5 doit brancher sa consultation sur cette API et signaler les résultats partiels ou en échec. |
| P4 | Fournir les PDF, DOCX ou ZIP et l'identifiant de collecte. Les fichiers TXT/CSV de `shared` restent hors des formats d'ingestion. |
| P6 | Le job fournit `p2.storage.v1` et des descripteurs d'exports `path`, `size_bytes`, `sha256`. Reste à définir le stockage partagé et les autorisations. Les chemins P2 sont locaux au déploiement. |

P1 dispose de `evaluation/eval_suite.py` et du schéma commun
`shared/schemas/ground_truth.schema.json`. Pour son évaluateur de champs,
transmettre un dictionnaire plat avec les mêmes clés que
`champs_cles_extraits`, par exemple `caution_provisoire_mad` (nombre) et
`date_limite_remise_plis` (date ISO avec fuseau). Conserver séparément le
fichier, la page ou l'article et la citation d'où provient chaque valeur.
Une valeur sans preuve reste inconnue. Les champs d'une ligne du BPU ne
sont pas les champs contractuels du DCE.

Le dépôt contient le profil entreprise SQL/Pydantic de P3. Son API DCE
et le consommateur P5 sont décrits dans leurs README. Le branchement proposé
pour `GET /api/dce/{id}` porte `job_id`, SHA-256 source, statut, erreurs,
avertissements et membres identifiés par `member_id`. P3 peut délivrer les
exports via un lien autorisé construit côté serveur après `resolve_export()`.
P6 doit monter l'espace des sources et résultats pour le producteur et
donner un accès en lecture au backend autorisé. Les chemins internes P2
restent côté serveur. Le socle P6 de la branche `origin/feature/socle-t08`
expose `/health` et `/debug/ping`. Il reste à y raccorder le stockage DCE.
Les services disponibles ne permettent pas de tester cet échange de bout en bout.

### Contrat T95 côté P2

- **P1.** Pour chaque résultat OCR évalué, transmettre `page`, `language`,
  `scope_sha256`, `reference_sha256`, `reference_text_original`,
  `hypothesis_text_original`, `metrics.normalization` et
  `metrics.word_metrics` depuis `p2.ocr_metrics.v1`. Pour reproduire le CER
  et le WER avec P1, appliquer la même normalisation aux deux textes.
  Le WER découpe sur les espaces Unicode et conserve les signes, la casse et
  les diacritiques. Si `metrics` vaut `null`, transmettre
  le motif dans `warnings`. Pour les champs, P1 appelle
  `evaluate_dce_extraction(predictions, ground_truth)` avec des valeurs
  normalisées indexées par les clés de `champs_cles_extraits`. Les preuves
  accompagnent le dictionnaire séparément. La production des champs métier
  reste à raccorder.
- **P3.** Enregistrer `dce_id`, `job_id` et `source_sha256`
  (issu de `job.source.sha256`). Consommer le suivi via `load_delivery`.
  Identifier un export par le triplet `job_id`, `member_id`, nom exact
  dans `document.outputs`. Vérifier les droits du demandeur sur le DCE,
  l'appartenance du membre au suivi et le descripteur via `resolve_export`
  avant le téléchargement. Une nouvelle source ou un nouveau traitement
  reçoit sa propre association de suivi.
- **P5.** Le détail `GET /api/dce/{id}` est à brancher dans P3. Il expose
  `dce_id`, `source_sha256`, `job_id`, `status`, `errors`, `warnings`
  et `documents`. Chaque membre porte `member_id`, `status` et une
  liste `exports` avec `name`, `size_bytes`, `sha256` et `url`
  autorisée. Afficher l'état `processing`, `partial`, `failed` ou
  `completed_with_review`, avec les exports déjà disponibles et le
  résultat de chaque membre. `completed_with_review` indique une
  extraction encore à relire.
- **P6.** Pour le mode `p2.storage.v1` avec `backend=local`, conserver
  l'arborescence relative à P2 dans le volume partagé. Le producteur écrit
  et le backend lit les objets contrôlés par SHA-256 et taille. Le client
  reçoit uniquement des URL autorisées. Conserver les anciens objets tant
  qu'un suivi les référence, y compris lors d'une reprise.

Le CER français page 1 a été reproduit avec l'évaluateur réel P1. Le
format de ses champs a été vérifié avec une fixture de vérité terrain.
La livraison du DCE et ses exports ont été contrôlés sur le stockage
local. Les intégrations HTTP P3/P5 et le volume déployé P6 restent à
brancher et à tester ensemble.

#### Exemples de lancement

Depuis la racine du dépôt, le DOCX synthétique fourni permet de tester le BPU.
Pour tester un scan avec les modèles locaux, définir `$pdf` sur un PDF autorisé.

```powershell
$python = '.\P2_nlp_extraction\.venv\Scripts\python.exe'
& $python -B -m P2_nlp_extraction.pipeline P2_nlp_extraction/data/examples/BPU-synthetique.docx
& $python -B -m P2_nlp_extraction.pipeline $pdf --ocr auto --pages 1
```

La CLI renvoie `{"status":"partial","job_path":"outputs/runs/<job_id>/job.json"}`
pour une extraction utilisable limitée à une page. Codes de sortie
locaux : `0` pour `completed_with_review`, `2` pour `partial`,
`1` pour `failed`. Consulter `steps[].errors`, `errors` et
`warnings` pour le diagnostic. Les descripteurs accessibles restent présents
dans `documents[].outputs`.

Le mode automatique de la CLI et de Streamlit utilise un côté de détection
maximal de 1 280 pixels et un délai maximal de conversion de 8 500 secondes
par document. Les plafonds mémoire et les délais par page restent actifs.
Pour reproduire ce profil depuis l'API Python, passer
`ConversionOptions(ocr_mode="auto", ocr_detector_max_side=1280)` et
`conversion_limits=ConversionLimits(timeout_seconds=8500)` à `run_pipeline`.

Le serveur P3 pourra utiliser le détail `GET /api/dce/{id}` décrit
ci-dessus. Exemple d'URL proposée pour un export :
`GET /api/dce/{id}/jobs/{job_id}/members/{member_id}/exports/tables_csv`.
Pour un export identifié par `job_id`, `member_id` et
`name`, les réponses proposées sont `200` si l'objet est autorisé et
vérifié, `403` si le demandeur n'est pas autorisé, `404` si l'objet
n'existe pas et `409` si la livraison publiée a perdu son intégrité.
Un DCE autorisé dont le traitement est `partial` ou `failed` reste
consultable avec une réponse de détail `200` et son statut métier.
Les chemins internes et les diagnostics système restent côté serveur.

Transférer séparément les modèles et documents autorisés. Pour reprendre un
suivi sur un autre PC, conserver l'arborescence relative des sources, des jobs,
des exports et des caches OCR utilisés. Les anciens suivis qui contiennent un
chemin OCR absolu peuvent demander de fournir à nouveau le cache via
`ConversionOptions.ocr_results`. Les diagnostics historiques sont conservés
comme preuves locales.

## Tests et limites

```powershell
.\P2_nlp_extraction\.venv\Scripts\python.exe -B -m unittest discover -s P2_nlp_extraction/tests -p "test_*.py" -v
.\P2_nlp_extraction\.venv\Scripts\python.exe -B -m pip check
```

Les moteurs OCR des tests sont simulés ; certains tests relisent des résultats
réels locaux et sont ignorés si ces données ne sont pas présentes chez un collègue.
Le scénario DOCX/BPU synthétique teste les vrais parseurs, pas un vrai BPU de marché.

- **T25, exécution réelle sous Windows.** Les 28 pages du DCE ont été
  traitées en un lancement de 48 min 38 s, sans cache OCR, en sept lots.
  Les 28 pages sont à relire. Avec la détection limitée à 1 280 pixels et le
  rendu à 200 dpi, le Job Object a mesuré un pic de 976,4 Mio de mémoire
  privée engagée pour l'arbre du worker OCR, sous la limite de 1 536 Mio.
  Le suivi local est `outputs/audit/validation-claude/10ab2793a2ea43a7/job.json`.
  Sur le périmètre français approuvé de la page 1, l'essai hors pipeline
  du filtre médian et de la binarisation Otsu a porté le CER de 1,083 %
  à 24,188 % et le WER de 2,198 % à 24,176 %. L'estimateur de redressement
  a retenu 0°. La variante reste expérimentale. Le rapport local se trouve
  dans `outputs/audit/preprocessing/comparison.json`.
- Le parcours complet a réutilisé les 28 résultats OCR en une conversion.
  Les six types d'exports JSON ont passé la validation de schéma. Le suivi
  reste partiel à cause des cellules et métriques qui demandent une revue.
- T26 : les sections CPS et BPU ont été retrouvées sur le DCE réel. Les limites
  de section restent partielles lorsque seules certaines pages sont converties.
- T27 : la géométrie rattache les numéros de prix et les fragments de désignation
  à leur cellule. La provenance conserve les coordonnées et les identifiants
  OCR. Une quantité sans confirmation documentaire reste `null`.
  Sur les pages 19, 24 et 25, les cellules couvertes par une fusion portent
  le statut `covered` et le renvoi `covered_by` vers leur cellule d'origine.
  Les quatre transcriptions visuelles des pages 24 et 25 sont conservées dans
  `data/ground_truth/dce_table_cells.json` pour comparaison humaine. La
  production extrait les cellules à partir de la géométrie et du texte
  disponibles. Elle garde `null` en cas d'abstention.
  Un modèle spécialisé de structure de tableaux pourrait être comparé sur
  un corpus annoté de grilles complexes. Aucun essai TSR n'a été réalisé.
  Pour réexporter aussi les grilles des pages 19, 24 et 25 sans relancer l'OCR,
  utiliser `python -m P2_nlp_extraction.tools.audit_p2 tables --job <suivi-relatif-à-P2>`.
- T28 : au nouvel essai, CER français page 1 = 6/554, soit **1,083 %**, sur
  le périmètre humain approuvé. La page 2 contient encore des blocs non résolus
  dans ce périmètre. Le CER arabe et les métriques de découpage réel restent
  indisponibles faute de références compatibles approuvées.
  Pour les compléter, préparer les références arabes avec
  `config/ocr_references.schema.json` et les annotations de découpage avec
  `config/section_annotations.schema.json`, avec empreintes et approbation humaine.
  Le dossier local de relecture `data/ground_truth/dce_review/`
  contient les brouillons à relire selon la procédure ci-dessous.
  Les références arabes doivent transcrire les régions de la page réellement
  comparées. Pour mesurer les articles et sous-sections, annoter les bornes
  avec les identifiants de blocs T24 dans `scope.hierarchy` et faire approuver
  le périmètre après calcul de son empreinte.
- Le RSS affiché par étape concerne le superviseur après l'étape, pas le pic global
  des processus. Les budgets de T23/T24 restent surveillés ; le plafond OCR strict
  relève du Job Object Windows. Les tests ne prouvent pas la précision sur tous les DCE.

### Ajouter une référence humaine

Les références approuvées, les brouillons et les preuves sources restent privés.
Pour reproduire les mesures historiques sur un poste autorisé, restaurer
`data/ground_truth/` et les sources et sorties correspondantes depuis la
sauvegarde privée en conservant leurs chemins et leurs octets. Les empreintes
et les approbations du manifeste sont vérifiées par l’évaluateur.

1. Pour l'OCR, ouvrir la page au DPI du résultat enregistré. Délimiter les
   régions en pixels et transcrire leur texte dans un fichier UTF-8.
   Renseigner le PDF, la page et la langue dans le manifeste.
2. Pour le découpage, ouvrir le JSON T24 et relever les identifiants des blocs
   au début et à la fin de chaque section, article et sous-section du périmètre.
3. Faire relire la référence et le périmètre. Ajouter le nom du relecteur,
   la date ISO avec fuseau et les empreintes du document, de la référence
   et du périmètre. Utiliser `scope_hash(scope)` dans
   `P2_nlp_extraction.quality_evaluation.references` pour le périmètre.
4. Appeler `P2_nlp_extraction.quality_evaluation.evaluate_quality` avec
   `ocr_json_path` et `reference_manifest_path` pour l'OCR, et avec
   `segmentation_json_path` et `section_annotations_path` pour le découpage.
   Réutiliser le JSON T26 issu du JSON T24 annoté. Vérifier les états et les
   motifs dans `ocr_metrics.json` et `segmentation_metrics.json`.

L'outil d'audit prépare les brouillons, calcule les empreintes après relecture
et vérifie les annotations face aux sorties existantes. Depuis la racine du
dépôt, définir `$ocr` et `$sections` sur les JSON OCR et T26 à comparer, puis
utiliser un nouveau nom pour le dossier de brouillons. Le relecteur renseigne
`$relecteur` avec son nom après vérification du texte et du périmètre.

```powershell
$python = '.\P2_nlp_extraction\.venv\Scripts\python.exe'
$drafts = 'P2_nlp_extraction/outputs/references-relecture'
& $python -m P2_nlp_extraction.tools.audit_p2 reference-draft --draft-dir $drafts --ocr-result $ocr --sections $sections --pages 1 --language ar
# Après transcription, délimitation de la région et annotation humaine
& $python -m P2_nlp_extraction.tools.audit_p2 reference-approve --reference "$drafts/ocr-draft.json" --reviewer $relecteur
& $python -m P2_nlp_extraction.tools.audit_p2 reference-approve --annotations "$drafts/sections-draft.json" --reviewer $relecteur
& $python -m P2_nlp_extraction.tools.audit_p2 reference-check --ocr-result $ocr --sections $sections --reference "$drafts/ocr-draft-approved.json" --annotations "$drafts/sections-draft-approved.json"
```

Le brouillon OCR couvre initialement toute la page. Réduire la zone à la
langue relue et éviter de couper un bloc OCR. Dans le brouillon T26, garder
des identifiants de blocs contigus, renseigner `sections` et, le cas échéant,
`scope.hierarchy`, puis confirmer `exhaustive`. L'approbation écrit une
copie avec les empreintes et le nom du relecteur. La vérification indique
les motifs si la référence reste non comparable.

## Évaluations expérimentales hors pipeline

**T10, protocole prêt à exécuter.** Aucun résultat comparatif sur le corpus du
projet n'a été retrouvé. T03 prévoit les PDF natifs DCE-2024-001, 004 et 005.
Les PDF correspondants sont absents de la copie locale de `shared/dataset`.
Le transfert ZIP et l'historique Git local ne contiennent pas ces trois PDF.
Demander les PDF à P1. Le DCE scanné local peut servir à un essai complémentaire
distinct. Ne pas mélanger ses résultats avec ceux des PDF natifs.

T10 figure dans le périmètre transmis et dans T03 comme comparaison
expérimentale séparée. Pour la reproduire lorsque les PDF seront disponibles,
utiliser deux environnements dédiés sur la même machine CPU, avec
`docling==2.151.1` et `marker-pdf==1.10.1`. Archiver `pip freeze` pour chaque
environnement, la révision ou les empreintes des modèles et le SHA-256 de
chaque PDF. Une fois les outils disponibles, renseigner `$docling` et
`$marker` avec les exécutables `docling` et `marker_single`.

```powershell
$bench = 'P2_nlp_extraction/outputs/benchmark-t10'
Get-FileHash -Algorithm SHA256 -LiteralPath $pdf
$env:TORCH_DEVICE = 'cpu'
& $docling convert $pdf --device cpu --to json --output "$bench/docling-json"
if ($LASTEXITCODE -ne 0) { throw 'Échec Docling' }
& $marker $pdf --output_format json --output_dir "$bench/marker-json"
if ($LASTEXITCODE -ne 0) { throw 'Échec Marker' }
```

Répéter trois fois par PDF et par moteur après échauffement, en alternant l'ordre.
Chronométrer les mêmes commandes JSON avec `Measure-Command` et conserver leur
code de retour. Pour le pic RSS, échantillonner toutes les 100 ms avec
`psutil` la somme du RSS du processus et de ses descendants. Produire aussi
le Markdown avec `--to md` et
`--output_format markdown` dans des dossiers distincts pour l'inspection.
Pour chaque page de référence, comparer l'ordre de lecture, les tableaux,
les fusions, les cellules et la provenance avec le PDF. Conserver les
valeurs attendues validées séparément, signaler les cellules non évaluables,
et rapporter les erreurs et les médianes par document. Pour un test scanné,
noter l'OCR appliqué par chaque outil et mesurer séparément. Les résultats
publiés sur d'autres corpus ne remplacent pas ces mesures.
[CLI Docling](https://docling-project.github.io/docling/reference/cli/)
[Marker 1.10.1](https://pypi.org/project/marker-pdf/1.10.1/)

**T11, essai historique.** PaddleOCR est le moteur retenu dans P2.
Les mesures sur les mêmes zones françaises des
pages 1 et 2 ont donné un CER de 1,9293 % pour PaddleOCR et de 9,3707 %
pour Tesseract 5. Tesseract était plus rapide sur le DCE. La comparaison
ne fournit pas de score arabe. Voir le [protocole et les mesures](reports/comparaison_paddleocr_tesseract.md).
