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

