# P2 — OCR français–arabe et extraction NLP

`ocr_pipeline.extract_pdf()` extrait automatiquement les lignes d'un PDF avec
les modèles PaddleOCR français/latin et arabe locaux. Le résultat conserve les
coordonnées, les hypothèses des deux reconnaisseurs et les cas à relire.
Le pipeline reste expérimental : deux pages ne valident pas sa précision générale.

## Installation

Configuration testée : **Windows 10, Python 3.12 x64, CPU**. Pour une nouvelle
machine uniquement, depuis la racine du dépôt :

```powershell
py -3.12 -m venv .\P2_nlp_extraction\.venv
& .\P2_nlp_extraction\.venv\Scripts\python.exe -m pip install -r .\P2_nlp_extraction\requirements.txt -c .\P2_nlp_extraction\requirements-lock.txt
& .\P2_nlp_extraction\.venv\Scripts\python.exe -m pip check
```

L'environnement existant n'a pas besoin d'être recréé. Le verrou contient les
versions installées des dépendances d'exécution ; l'installation sur une machine
vierge reste à vérifier. Aucun paquet n'est installé par l'API.

Les poids sont absents de Git et ne sont **jamais téléchargés automatiquement**.
Copier les trois dossiers complets de modèles existants vers :

```text
P2_nlp_extraction/.cache/paddlex/official_models/
├── PP-OCRv5_mobile_det/
├── latin_PP-OCRv5_mobile_rec/
└── arabic_PP-OCRv3_mobile_rec/
```

Les neuf fichiers inference.json, inference.yml et inference.pdiparams sont
contrôlés avec `config/model_inventory.json` avant l'inférence. L'adaptateur exige
PaddlePaddle 3.2.2, PaddleOCR 3.3.2 et PaddleX 3.3.13. Le détecteur server est exclu.

## Utilisation par les autres modules

Exécuter depuis la racine du dépôt avec le Python de P2, ou utiliser les mêmes
dépendances et rendre la racine du dépôt importable :

```python
from pathlib import Path
from P2_nlp_extraction.ocr_pipeline import extract_pdf

if __name__ == "__main__":
    result = extract_pdf(
        Path("mon_document.pdf"),
        Path("P2_nlp_extraction/outputs/ocr/mon_module"),
        pages=None,  # toutes les pages ; [1, 2] pour un essai limité
        arabic_spacing="suggest",
        on_error="continue",
    )
    for page in result["pages"]:
        for block in page["blocks"]:
            print(page["page"], block["language"], block["bbox"], block["raw_text"])
            if block["needs_review"]:
                print(block["recognition_candidates"])
```

Le PDF peut être ailleurs. Les exports restent dans P2, dans un dossier unique :
JSON, TXT UTF-8 brut, propositions d'espacement séparées, hypothèses et journaux.
Aucune région manuelle n'est demandée. Voir [le contrat de l'API](ocr_pipeline/README.md).

## Tests essentiels

Les tests découverts ci-dessous couvrent le pipeline OCR et l'ingestion T23.

```powershell
& .\P2_nlp_extraction\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s .\P2_nlp_extraction\tests -v
& .\P2_nlp_extraction\.venv\Scripts\python.exe -B -X utf8 .\P2_nlp_extraction\scripts\run_automatic_ocr_sample.py
```

Les tests techniques utilisent des modèles simulés, sans poids, et nettoient
leurs fixtures temporaires. Le second appel effectue une vraie extraction des
**seules pages 1 et 2** de `data/pdf/test_dce.pdf`, conservé localement et ignoré
par Git. Il exige les modèles locaux et échoue si l'extraction est incomplète,
si le français/arabe attendu manque ou si les exports ne sont pas lisibles.
Les sorties sont dans `outputs/ocr/automatic_sample/`. Aucun benchmark de 28 pages.

## Comparaison et références

Une seule [synthèse de comparaison](reports/comparaison_paddleocr_tesseract.md)
explique le choix provisoire de PaddleOCR. Vitesse historique : **28 pages** ;
précision : **zones françaises des pages 1 et 2**, validées humainement.
Ces scores ne mesurent ni l'arabe ni le routage automatique actuel.
Les références restent dans `data/ground_truth/pages_1_2/`.
Les anciens benchmarks, interfaces et diagnostics ont été retirés après sauvegarde
vérifiée hors de P2.

## T23 — Préparation des documents

`document_ingestion.ingest_path()` reçoit un ZIP ou un fichier individuel, détecte
son type réel et produit un manifeste JSON `p2.ingestion.v1` dans
`outputs/ingestion/<run_id>/`. Il conserve les noms, chemins et empreintes et ne
marque éligibles à T24 que les PDF/DOCX acceptés. Aucun OCR ni conversion Markdown.

```python
from P2_nlp_extraction.document_ingestion import ingest_path, IngestionLimits

if __name__ == "__main__":
    result = ingest_path(
        "marche.zip",
        "P2_nlp_extraction/outputs/ingestion",
        dce_id="DCE-2024-001",
        limits=IngestionLimits(),
    )
    print(result["status"], result["manifest_path"])
```

Les ZIP imbriqués ne sont pas extraits récursivement. Les types non pris en charge
restent inventoriés sans éligibilité. Les contrôles de chemins, CRC et ressources
ne constituent ni un antivirus ni une sandbox système. Voir le
[contrat T23, les limites et les tests](document_ingestion/README.md).
Le pipeline OCR existant reste indépendant.

## T24 — Conversion Markdown et JSON

Le package [document_conversion](document_conversion/README.md) consomme les
fichiers `ready` et `eligible_for_t24` d'une ingestion T23 terminée. Il vérifie
les chemins, tailles, empreintes et types réels avant conversion.

```python
from P2_nlp_extraction.document_conversion import convert_ingestion, ConversionOptions

result = convert_ingestion(
    "P2_nlp_extraction/outputs/ingestion/<run_id>/manifest.json",
    options=ConversionOptions(ocr_mode="never"),
)
print(result["status"], result["manifest_path"])
```

PyMuPDF extrait les PDF textuels ; la décision est prise **page par page**.
`ocr_mode="auto"` raccorde les pages scannées/mixtes au pipeline Paddle existant ;
`never` signale les pages nécessitant encore l'OCR sans l'exécuter ; `reuse_only`
consomme des résultats OCR locaux compatibles. Les DOCX passent par python-docx,
avec pagination inconnue et pertes éventuelles explicitement signalées.
Les textes bruts, hypothèses, coordonnées, pages PDF et provenance restent dans
`outputs/conversion/<run_id>/documents/<file_id>/document.json`, avec son
`document.md` UTF-8. Aucune sortie n'est validée humainement automatiquement.

Installer l'extension avec `requirements-conversion.txt` et ses contraintes
`requirements-conversion-lock.txt` ; voir la documentation T24 pour l'API
`convert_document()`, la CLI, le schéma, les limites et les tests sans OCR réel.
T26/T27 et les extractions métier ne sont pas implémentées par ce composant.

## Prochaines tâches P2

- [ ] Extraction des clauses importantes des RC/CPS.
- [ ] NER des marchés publics.
- [ ] Extraction de caution, délais et qualifications requises.
- [ ] JSON métier dans `outputs/extractions/`.
- [ ] Validation du routage et de l'espacement sur des paragraphes arabes annotés.

Données d'équipe en lecture seule : `shared/dataset/dce/`,
`shared/dataset/annotations/` et `shared/schemas/ground_truth.schema.json`.
Les futurs modèles NLP et notebooks seront ajoutés au démarrage de ces tâches ;
aucun modèle NLP/NER existant n'a été supprimé.

Exemple de sortie métier future, distincte de l'OCR actuel :

```json
{"dce_id": "DCE-2024-001", "entites_extraites": {"caution_provisoire": "50000 MAD", "delai_execution": "12 mois", "qualification_requise": "Secteur I - Classe 3"}}
```

