# T24 — Conversion PDF/DOCX en Markdown structuré

T24 consomme exclusivement un `manifest.json` T23 sur disque. Il ne convertit
ni un fichier arbitraire hors ingestion, ni une entrée non admissible. T23 et
`ocr_pipeline` restent indépendants et inchangés. Aucun découpage DCE (T26) ni
extraction métier BPU (T27) n'est effectué.

## Installation Windows / Python 3.12 x64

Depuis la racine du dépôt, dans le même environnement que P2 :

```powershell
& .\P2_nlp_extraction\.venv\Scripts\python.exe -m pip install -r .\P2_nlp_extraction\requirements-conversion.txt -c .\P2_nlp_extraction\requirements-conversion-lock.txt
```

PyMuPDF et psutil sont déjà des dépendances OCR. T24 ajoute python-docx, son
parseur lxml et jsonschema pour valider le contrat T23. Les verrous supplémentaires
ne remplacent pas le verrou OCR. Aucun Docling/Marker, Tesseract ou nouveau modèle
n'est requis. Les trois modèles Paddle locaux restent sous
`P2_nlp_extraction/.cache/paddlex/official_models/` ; voir le README OCR et
`config/model_inventory.json`. Les modes `never`/`reuse_only` n'utilisent pas Paddle.

## API depuis la racine du projet

```python
from P2_nlp_extraction.document_ingestion import ingest_path
from P2_nlp_extraction.document_conversion import (
    convert_ingestion, convert_document, ConversionOptions, ConversionLimits,
    ConversionInputError,
)

if __name__ == '__main__':
    ingestion = ingest_path('P2_nlp_extraction/data/pdf/document.pdf')
    # Choisir un fichier ready + eligible ; les IDs incluent aussi les répertoires.
    selected = next(f['file_id'] for f in ingestion['files']
                    if f['status'] == 'ready' and f['eligible_for_t24'])
    document = convert_document(
        ingestion['manifest_path'], selected,
        'P2_nlp_extraction/outputs/conversion',
        options=ConversionOptions(ocr_mode='auto'),
        limits=ConversionLimits(),
    )
    print(document['status'], document['markdown_path'], document['document_json_path'])
    # Pour tout le manifeste :
    # batch = convert_ingestion(ingestion['manifest_path'], options=ConversionOptions())
```

`convert_ingestion(manifest_path, output_dir=None, *, file_ids=None, options=None,
limits=None)` retourne le manifeste de conversion et les chemins runtime
`run_directory`/`manifest_path`. `file_ids=None` sélectionne tous les fichiers
admissibles ; une sélection explicite non admissible est refusée.

`convert_document(manifest_path, file_id, output_dir=None, *, options=None,
limits=None)` retourne le document JSON et les chemins runtime `run_directory`,
`manifest_path`, `document_json_path`, `markdown_path`. Les chemins absolus runtime
ne sont pas enregistrés dans les exports documentaires portables.

Une entrée/options/manifeste invalide lève `ConversionInputError`, `ValueError`,
`TypeError` ou une erreur de fichier. Un refus documentaire, un échec ou un résultat
incomplet devient un statut explicite ; vérifier **le manifeste ET les documents,
pages, blocs, erreurs et avertissements**, pas seulement l'absence d'exception.

### CLI

Après préparation du PDF individuel par T23 (le manifeste réel remplace `<run_id>`) :

```powershell
& .\P2_nlp_extraction\.venv\Scripts\python.exe -B -X utf8 -m P2_nlp_extraction.document_conversion "P2_nlp_extraction/outputs/ingestion/<run_id>/manifest.json" --file-id f000001 --ocr-mode never
```

`never` permet une première vérification sans OCR : une page qui en a besoin
reste `needs_ocr` et le document `partial`. Utiliser `--ocr-mode auto` pour autoriser
l'adaptateur du pipeline existant, ou `--ocr-mode reuse_only --ocr-result <JSON>`
pour des résultats déjà enregistrés. `--pages 1 2` sélectionne explicitement un
échantillon PDF, consigné dans `coverage`. Codes de sortie : 0 conversion terminée
(éventuellement à revoir), 2 entrée refusée ou conversion incomplète/échouée.

## Choix extraction native / OCR

Chaque page est examinée séparément. PyMuPDF lit les blocs/spans sans embarquer
les bitmaps dans son dictionnaire de texte. Texte exploitable : présence de
caractères et moins de 5 % de caractères suspects (remplacement, zone privée,
contrôle). Une page contenant moins de 30 caractères visibles reste insuffisante
pour conclure : vérification OCR proposée. Une image occupant au moins 8 % de la
page et recouverte par moins de 15 % de blocs natifs exploitables déclenche un
traitement hybride/OCR, même avec un pied de page natif. Les images sont repérées
par leur géométrie sans décompression intégrale. Une page sans texte/images reçoit
un petit rendu gris pour distinguer contenu vectoriel et blanc apparent.

Ces seuils sont **heuristiques, non calibrés** : ni détection de langue fiable,
ni preuve de lisibilité. Une image décorative peut déclencher un OCR inutile ;
une couche de texte plausible mais erronée peut ne pas être reconnue comme telle.
Les pages blanches restent seulement « apparemment blanches » et à revoir.

Seules les pages nécessitant l'OCR sont transmises à
`ocr_pipeline.extract_pdf()`, par lots de 4 par défaut et avec 2 threads CPU.
L'adaptateur ne change aucun modèle. Les PDF mixtes sont fusionnés spatialement :
texte identique normalisé + chevauchement = doublon supprimé de l'affichage mais
conservé comme hypothèse. Divergence dans le même bloc : priorité au natif
exploitable, alternatives conservées et avertissement ; gros chevauchements
ambigus conservés et signalés. Aucun doublon n'est supprimé uniquement sur le texte.

Les résultats OCR réutilisés doivent correspondre au SHA-256 du PDF, à ses indices
de pages, au DPI et à des coordonnées valides. Aucun chemin `image`, `source_pdf`
ou `exports` fourni par un JSON OCR n'est suivi. L'empreinte assure la correspondance
documentaire, **pas l'authenticité de la reconnaissance** : seuls des JSON locaux
de confiance doivent être fournis. Les hypothèses français/arabe, le texte brut et
les propositions d'espacement arabes restent distincts ; ces dernières ne sont
jamais appliquées au Markdown. `human_validated` reste toujours `false`.

## Structure et traçabilité

```text
outputs/conversion/<run_id>/
  manifest.json                  # p2.conversion.v1, résumé des documents
  documents/<file_id>/
    document.md
    document.json                # p2.conversion_document.v1
    request.json / worker.log    # données locales d'exécution, non partageables
    .source.pdf ou .source.docx  # instantané vérifié privé
    ocr/                        # uniquement si OCR réellement exécuté
```

Le [schéma JSON](../config/conversion.schema.json) accepte les deux exports.
Le document contient sa source T23 (run, ID, chemin relatif, taille, empreintes
source/manifeste), les versions, la couverture, les pages PDF physiques (1-based),
leurs labels éventuels et les blocs. `blocks` est la liste canonique globale ;
`pages[].blocks` est une vue des **mêmes** blocs, pas des blocs supplémentaires.
Chaque bloc a un ID unique dans le document, une méthode, le texte brut, le texte
d'affichage, la langue heuristique, les positions, les avertissements, la référence
source et les lignes Markdown 1-based (`null` si représentation supprimée).
La clé complète pour T26/T27 est `(ingestion_run_id, file_id, block_id)`.

Les coordonnées sont des points sur la page PDF affichée, origine haut-gauche,
rotation appliquée. Les coordonnées natives sont transformées ; celles de l'OCR
existant sont déjà dans ce repère. Les spans natifs et hypothèses OCR restent dans
le JSON. L'ordre haut-bas / droite-gauche pour des blocs arabes sur une même ligne
est une approximation ; les colonnes et chevauchements sont signalés.

### Structure déduite des blocs OCR

`pages[].structure` ajoute une vue de présentation sans remplacer `blocks` ni
`pages[].blocks`. Chaque groupe possède `group_id`, `source_block_ids`, les
`raw_texts` exacts, le texte assemblé, la boîte englobante, la direction et les
éléments ayant motivé l'inférence (`p2.ocr_structure.v1`). Les originaux gardent
leur ID, leur type, texte brut, propositions arabes, positions, avertissements et
hypothèses ; seul le lien `structure_group_id` et le repérage Markdown sont ajoutés.
Les lignes Markdown d'un groupe sont aussi référencées par ses blocs sources.
Cette vue ne représente pas de nouvelles reconnaissances : ne pas additionner
ses groupes au nombre de blocs OCR.

Le module `ocr_structure.py` utilise des hauteurs de lignes dans les boîtes OCR,
**pas des tailles de police connues**. Avec au moins trois longues lignes de corps,
il estime une hauteur de référence dans la moitié basse des hauteurs. Un titre
dominant, centré, isolé et sensiblement plus grand dans la moitié supérieure de
la page peut devenir `#`. Ses lignes consécutives sont réunies si leurs hauteurs,
centres et espacements concordent. Des titres centrés plus petits et isolés après
cette racine peuvent devenir `##`. En arabe, sans casse, l'écart de hauteur exigé
est plus important. Des dominantes concurrentes, des informations absentes ou des
colonnes ambiguës font renoncer à la hiérarchie. Aucun `###` n'est actuellement
inféré faute d'indice suffisant de troisième niveau. Les titres PDF natifs et
DOCX suivent leurs règles existantes.

Les paragraphes réunissent seulement des blocs OCR contigus, proches, de même
langue/direction et de hauteur comparable, avec fort recouvrement horizontal et
alignement à gauche en français, à droite en arabe, ou centrage concordant.
Les titres, listes, fins de phrase, grands intervalles, colonnes/chevauchements
signalés, changements de page ou de langue interrompent le regroupement. Les
lignes essentiellement numériques et les blocs mixtes incertains restent séparés.
Ces règles sont prudentes : certaines lignes d'une vraie colonne ou paragraphes
complexes resteront fragmentés. Elles n'authentifient pas la structure métier.

Le texte assemblé insère un espace entre les blocs ; il ne corrige aucune lettre,
date, ponctuation ou proposition d'espacement arabe. Les zones indéterminées et
fragments de tampon restent tels quels. Les inférences conservent les
avertissements sources et `human_validated=false`, avec une indication spécifique
de structure déduite par géométrie.

Deux rectangles d'images identiques ne suffisent pas à conclure à un doublon.
Sur la page 1 du DCE local, les images xref 17 et 18 ont des empreintes différentes,
et l'une possède un masque. Leurs emprises superposées sont donc conservées.

Titres PDF : inférés des tailles de police. Listes PDF : marqueurs imprimés
conservés. Tableaux PDF simples : `find_tables()` et grille rectangulaire ; en-tête
inféré. Fusions/ambiguïtés : notice de perte structurelle et fragments/cellules
dans le JSON, sans prétendre restituer une table fidèle.

DOCX : paragraphes et tableaux dans l'ordre XML, styles/outline pour les titres,
numPr et styles hérités pour les listes. Les numéros exacts Word (redémarrages,
overrides) ne sont pas inventés : métadonnées conservées, notice dans le Markdown.
Tables simples rendues, fusions et tables imbriquées conservées comme fragments.
En-têtes/pieds séparés par rôle et partie, dédupliqués, sans attribution physique
aux pages. Sauts explicites conservés comme métadonnées. **Pages et coordonnées
DOCX restent nulles**. Champs non recalculés ; images intégrées non OCRisées ;
révisions, contrôles de contenu, notes/commentaires et zones de texte peuvent
être omis, avec avertissements et statut `partial` si détectés.

## Sécurité, ressources et erreurs

Le schéma T23 est validé, puis les invariants supplémentaires : ingestion globale
`completed`/`completed_with_issues`, éligibilité globale, item `ready` et éligible,
ID unique, chemin canonique exact `files/<relative_path>`, confinement P2, absence
de lien/jonction, absence d'alias d'artefact. Le répertoire réel du manifeste est
la racine d'ingestion ; aucun `run_directory` déclaré par le JSON n'est suivi.
Une copie privée est vérifiée par taille/SHA-256, puis redétectée avec les outils
T23. Pour DOCX, toutes les parties XML sont bornées et analysées sans DTD/entités
avant l'ouverture par python-docx. Aucun lien externe DOCX n'est téléchargé.

Par défaut : 20 documents par appel, 100 Mio source, 200 pages sélectionnées,
30 pages OCR, 2 000 blocs/page, 50 000 blocs/document, 200 000 caractères/page,
128 Mio DOCX décompressé, 4 Mio/partie XML et 32 Mio XML total, 10 000 cellules,
64 Mio par export, 12 Mpx de rendu OCR, 600 s et 1,5 Gio RSS surveillé par document.
Les protections T23 (formats ZIP, ratios, XML…) s'appliquent aussi à la redétection.
Les documents sont traités **séquentiellement**, chacun dans un processus séparé.
Le parent surveille le temps et la somme des RSS du worker et de ses descendants,
y compris l'OCR. Les exports sont remplacés atomiquement et checkpointés par page.

Ce n'est **pas une sandbox système** : RSS/temps sont échantillonnés, un pic mémoire
entre deux relevés reste possible ; PyMuPDF/python-docx peuvent allouer avant qu'un
contrôle applicatif intervienne. python-docx charge le paquet DOCX en mémoire
après précontrôle. L'écriture MD + JSON n'est pas une transaction à deux fichiers ;
après arrêt brutal, un checkpoint peut être incomplet et le statut devient
`partial`/`failed`. Le dossier local doit rester privé : les vérifications de
chemins ne garantissent pas l'absence d'une course contre un autre processus
malveillant modifiant les répertoires. Aucun antivirus intégré.

Les erreurs d'un document n'empêchent pas le suivant. Les résultats inachevés ne
deviennent jamais des transcriptions validées. Un lot de pages sélectionnées peut
être terminé sans couvrir le PDF complet : consulter `coverage`. Tous les fichiers
d'exécution, instantanés, JSON OCR, données synthétiques et logs restent ignorés
par Git sous `outputs/` ou `.cache/`. Les fichiers `request.json` et logs sont
locaux et peuvent contenir des chemins absolus : ne pas les partager.

## Vérifications

```powershell
& .\P2_nlp_extraction\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s .\P2_nlp_extraction\tests -p "test_conversion_*.py" -v
& .\P2_nlp_extraction\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s .\P2_nlp_extraction\tests -p "test_*.py" -v
```

Fixtures synthétiques seulement : PDF natif, scan simulé, page hybride, rotation,
page vide/vectorielle, tables, DOCX français/arabe, ZIP multi-document T23, chemins,
empreintes, limites, échec d'un worker, CLI, schéma et traçabilité. L'adaptateur OCR
est testé avec un callable simulé et des JSON explicitement synthétiques ; cela
ne valide pas la précision Paddle, le routage bilingue réel ou les performances
sur un DCE. Avant production : essai DCE réel autorisé, vérification humaine des
pages mixtes, colonnes, tableaux, fusions, notes DOCX et texte arabe, puis mesures
temps/RAM avec modèles et documents représentatifs.
