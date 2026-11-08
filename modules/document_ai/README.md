# Module Document AI / OCR — T10

Ce module teste l'extraction de texte et de tableaux avec Docling et Marker pour le projet de traitement des marchés publics marocains. La collecte du corpus relève de **P1**. Les documents de ce corpus n'étant pas encore disponibles, les essais T10 constituent une **évaluation provisoire sur un seul DCE public**, sans garantie de généralisation.

## Lire les résultats sans relancer l'OCR

| Élément | Fichier |
|---|---|
| Comparaison et recommandation T10 | [COMPARAISON_DOCLING_MARKER.md](COMPARAISON_DOCLING_MARKER.md) |
| Extraction Docling | [docling_dce_result.md](../../data/outputs/docling_dce_result.md) |
| Extraction Marker | [marker_dce_result.md](../../data/outputs/marker_dce_result.md) |
| Rapport de l'essai Docling | [rapport.md](../../data/outputs/dce_diagnostics/rapport.md) |
| Métriques Docling | [verification.json](../../data/outputs/dce_diagnostics/verification.json) |
| Métriques et temps Marker | [verification.json](../../data/outputs/marker_diagnostics/20261108T174743218178Z/verification.json) |
| Conditions d'exécution Marker | [runtime_conditions.json](../../data/outputs/marker_diagnostics/20261108T174743218178Z/runtime_conditions.json) |
| Messages et erreur de fermeture Marker | [extraction_dce.log](../../data/outputs/marker_diagnostics/20261108T174743218178Z/extraction_dce.log) |

Les deux outils ont exporté les 28 pages. Docling a produit 87 609 caractères et 9 tableaux en 350,77 s de conversion ; Marker a produit 90 150 caractères et 8 tableaux en 10 949,72 s. Les conditions de cache diffèrent : ces durées ne constituent pas un benchmark strict. Marker améliore certaines colonnes du matériel en page 25, mais omet des passages des pages 25 et 27. Les deux restituent les montants financiers contrôlés en page 27. Le nombre de caractères ne mesure pas la fidélité.

Marker a enregistré son Markdown avant une exception de nettoyage à la fermeture ; la commande a renvoyé le code 1 malgré le statut `converted` du rapport. La trace est incomplète. L'intégration doit donc distinguer la présence d'un résultat, sa qualité et la réussite de la commande. Docling est le moteur principal recommandé à ce stade ; les tableaux et clauses importantes restent à contrôler.

## Retrouver le document de test

Source : [CPS public de l'Institut Supérieur de la Magistrature](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf), appel d'offres n° 02/ISM/2024, 28 pages. Le fichier `test_dce.pdf` et **toutes les images de diagnostic restent uniquement sur le PC** ; ils sont exclus par `.gitignore`. Le dépôt ne fournit pas le corpus attendu de P1.

Le 8 novembre 2026, le PDF de cette URL a été lu en mémoire et comparé au fichier local : contenu identique, **2 223 941 octets**, SHA-256 :

```text
e7b529f09720b63c07f6fb728d51a8ded9e8c527162d91591770241cf08e5bb1
```

Après un clone, télécharger le document officiel et l'enregistrer sous `data/samples/test_dce.pdf`. Depuis la racine du dépôt, ces commandes PowerShell récupèrent uniquement le PDF ; elles n'installent rien et ne lancent pas l'OCR :

```powershell
New-Item -ItemType Directory -Force -Path data/samples | Out-Null
if (Test-Path -LiteralPath data/samples/test_dce.pdf) {
    throw 'Le PDF local existe deja : il est conserve.'
}
Invoke-WebRequest -Uri 'https://ism.ma/wp-content/uploads/2024/02/CPS.pdf' -OutFile data/samples/test_dce.pdf
Get-FileHash -LiteralPath data/samples/test_dce.pdf -Algorithm SHA256
```

Comparer l'empreinte obtenue à celle ci-dessus avant tout nouvel essai. Si la source change ou devient indisponible, la reproduction du même essai n'est plus garantie ; ne pas substituer silencieusement un autre DCE. Les références aux pages du PDF officiel utilisent parfois `#page=25` : si le lecteur ignore ce fragment, aller manuellement à la page indiquée. Les images intermédiaires ne sont pas nécessaires aux scripts d'extraction actuels.

## Données contenues dans les preuves

Le contrôle du PDF public, de la planche existante et des sorties textuelles n'a pas repéré de RIB renseigné ni d'identifiants de candidats renseignés dans les formulaires contrôlés. Aucun jeton d'accès ou mot de passe n'a été détecté dans les fichiers préparés par les contrôles ciblés ; ce contrôle ne garantit pas une absence exhaustive de données personnelles.

La page 28 contient **le nom, le cachet et une signature institutionnelle**. Le Markdown Marker en conserve le nom et une description textuelle du cachet. Il ne contient pas l'image de la signature. Le choix retenu pour le dépôt est de conserver les Markdown/JSON techniques, y compris ce nom public, et de laisser le PDF et toutes les images uniquement en local. Il ne s'agit donc pas d'un jeu de résultats anonymisé. Les journaux et diagnostics conservent aussi des chemins locaux d'exécution, sans valeur d'identification des candidats. L'accessibilité publique du PDF établit sa provenance, sans constituer à elle seule une licence de réutilisation du document source.

## Environnements et dépendances Python

Deux environnements distincts ont été utilisés sur Windows :

| Outil | Environnement local | Python vérifié | Dépendances principales |
|---|---|---|---|
| Docling | `.venv` | 3.14.0 | [requirements-docling.txt](requirements-docling.txt) |
| Marker | `.venv-marker` | 3.12.0 | [requirements-marker.txt](requirements-marker.txt) |

Les versions de ces fichiers ont été lues dans les métadonnées des environnements existants le 8 novembre 2026. Elles figent les paquets principaux, dont les moteurs OCR et bibliothèques de rendu, et non toutes les dépendances transitives. L'installation dans un environnement vierge n'a pas été retestée pendant cette préparation. Ne pas fusionner les deux fichiers : les versions de Pillow et de PDFium diffèrent. PyMuPDF est indiqué dans le fichier Docling pour conserver les prérequis de l'archive historique ; le script Docling actuel ne l'importe pas.

Sur un nouveau poste Windows disposant des versions Python correspondantes et du lanceur `py`, la création et l'installation peuvent se faire séparément, depuis la racine du dépôt :

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r modules/document_ai/requirements-docling.txt

py -3.12 -m venv .venv-marker
.\.venv-marker\Scripts\python.exe -m pip install -r modules/document_ai/requirements-marker.txt
```

Ces commandes sont des instructions d'installation, pas des opérations réalisées lors de cette préparation. Des modèles peuvent être téléchargés au premier usage. Aucun environnement Python, modèle ou exécutable n'est inclus dans Git.

## Prérequis externes de Marker : configuration CPU testée

L'installation Python seule ne suffit pas. Sur ce poste, Surya utilise le serveur **llama.cpp Windows CPU, build b12211**, version annoncée `0.9.0-dev`, commit `7d7f02875`.

- Source officielle : [release llama.cpp b12211](https://github.com/ggml-org/llama.cpp/releases/tag/b12211).
- Archive utilisée : [llama-b12211-bin-win-cpu-x64.zip](https://github.com/ggml-org/llama.cpp/releases/download/b12211/llama-b12211-bin-win-cpu-x64.zip).
- SHA-256 consigné de l'archive : `23729000408c6968faf5e322afc99319d3b8c576ba872ef7663d9b89810090f3`.
- Emplacement local testé : `.venv-marker/tools/llama.cpp-b12211/llama-server.exe`. Conserver les bibliothèques de l'archive avec l'exécutable ; ne pas copier seulement le fichier `.exe`.
- Le premier lancement peut télécharger les poids Surya depuis les sources du moteur, notamment `datalab-to/surya-ocr-2.5-gguf` sur Hugging Face. Le cache utilisé est `.venv-marker/model-cache`, exclu de Git.

La configuration CPU mesurée ne requiert pas Docker. Aucun environnement GPU/Colab n'a été validé dans T10. Les sources du moteur et de ses modèles ont leurs propres conditions d'utilisation ; aucun modèle ou binaire n'est redistribué ici.

## Commandes des scripts existants

Les deux scripts attendent le PDF local au chemin indiqué plus haut. Sans ce fichier, ils s'arrêtent explicitement. Depuis la racine du dépôt :

```powershell
# Docling : remplace docling_dce_result.md si ce resultat existe.
.\.venv\Scripts\python.exe modules/document_ai/test_docling.py
```

```powershell
# Marker : conserve le resultat existant et refuse de l'ecraser.
$env:LLAMA_CPP_BINARY = (Resolve-Path -LiteralPath '.venv-marker/tools/llama.cpp-b12211/llama-server.exe').Path
$env:SURYA_INFERENCE_BACKEND = 'llamacpp'
$env:SURYA_INFERENCE_PARALLEL = '1'
$env:HF_HOME = Join-Path (Get-Location).Path '.venv-marker/model-cache'
$env:PYTHONIOENCODING = 'utf-8'
.\.venv-marker\Scripts\python.exe -u modules/document_ai/test_marker.py
```

**Ne pas utiliser ces commandes pour écraser les preuves T10 conservées.** Un clone contenant les résultats fera refuser une nouvelle extraction par Marker ; Docling, lui, remplacerait sa sortie. Pour un nouvel essai, travailler dans une copie de travail distincte et y sauvegarder séparément les résultats existants avant de libérer les chemins de sortie. Les scripts actuels n'offrent pas d'option de sortie personnalisée.

Une extraction Marker réussie crée un nouveau dossier horodaté sous `data/outputs/marker_diagnostics/`. Les nouveaux essais et leurs extraits `page_25.md` / `page_27.md` restent ignorés par défaut ; seules les preuves textuelles sélectionnées de l'essai T10 sont autorisées par `.gitignore`. Le script Marker ne capture pas lui-même le terminal dans `extraction_dce.log` : le journal publié est une copie historique de la capture PowerShell, non une sortie automatique du script. Il est conservé à l'identique en UTF-16 LE ; pour le lire localement :

```powershell
Get-Content -LiteralPath data/outputs/marker_diagnostics/20261108T174743218178Z/extraction_dce.log -Encoding Unicode
```

## Ancien diagnostic archivé

[OCR_DIAGNOSTIC.md](archives/ancien_test_pdf/OCR_DIAGNOSTIC.md) et [diagnose_ocr.py](archives/ancien_test_pdf/diagnose_ocr.py) concernent un autre PDF, ancien et corrompu, de 12 pages. Ce PDF et ses preuves sont indisponibles. Le script vérifie cette absence avant de créer une sortie. Cette archive ne reproduit pas T10 et ne doit pas être redirigée vers le DCE provisoire.
