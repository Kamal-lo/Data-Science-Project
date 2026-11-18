# T23 — Ingestion de fichiers et archives ZIP

Ce composant prépare des documents locaux pour T24. Il ne convertit pas en
Markdown, ne lance pas d'OCR, ne télécharge rien et ne charge pas Paddle.
Il utilise la bibliothèque standard, PyMuPDF et psutil déjà présents dans P2.

## Appel depuis la racine du dépôt

```python
from pathlib import Path
from P2_nlp_extraction.document_ingestion import ingest_path, IngestionLimits

if __name__ == "__main__":
    result = ingest_path(
        Path("mon_marche.zip"),  # ou un PDF/DOCX individuel
        Path("P2_nlp_extraction/outputs/ingestion"),
        dce_id="DCE-2024-001",
        limits=IngestionLimits(),
    )
    print(result["status"], result["manifest_path"])
    if result["status"] in ("completed", "completed_with_issues"):
        for item in result["files"]:
            if item["eligible_for_t24"]:
                path = Path(result["run_directory"]) / item["artifact_path"]
                print(item["detected_type"], path)  # future entrée de T24
```

Signature : `ingest_path(source_path, output_dir=None, *, dce_id=None, limits=None)`.
La source peut être située ailleurs, mais doit être un fichier régulier sans lien
direct. Les destinations restent dans P2. L'API reçoit un chemin ; aucun endpoint
HTTP ou téléchargement n'est ajouté.

Les paramètres invalides lèvent `ValueError`/`TypeError` ; une source absente lève
`FileNotFoundError`. Les refus documentaires et erreurs du worker sont inscrits
dans le manifeste. Une impossibilité d'écrire le dossier/manifeste peut lever une
exception d'E/S : aucun contrat ne promet un JSON si le stockage est indisponible.

## Traitement et fichiers

Chaque appel crée un dossier inédit, sans écraser de sortie ou de source :

```text
outputs/ingestion/<run_id>/
├── request.json       # requête locale, chemins absolus, hors Git
├── worker.log         # diagnostics locaux, hors Git
├── manifest.json      # inventaire portable, UTF-8
├── files/             # publié uniquement après traitement complet
└── .staging/          # copie de travail/partiels, jamais à envoyer à T24
```

Une copie bornée de la source est contrôlée par taille, date de modification et
SHA-256. L'extension n'est qu'une indication. Les noms français/arabe et les
sous-dossiers valides sont conservés. Les séparateurs Windows sont normalisés en
`/` dans les chemins relatifs ; le nom d'origine est également conservé.
Les permissions et horodatages de l'archive ne sont pas appliqués au système.

Les fichiers réguliers non pris en charge sont conservés, inventoriés et marqués
non éligibles. Les ZIP imbriqués restent des fichiers ZIP : aucun de leurs membres
n'est extrait. Leur structure peut être inspectée pour les distinguer d'un DOCX ;
une structure imbriquée dangereuse/non prise en charge peut refuser toute l'ingestion.
Un ZIP vide est une ingestion terminée sans document éligible.

Les copies de travail restent locales pour diagnostic ; aucune politique de
purge automatique n'est appliquée aux anciennes exécutions. Ne pas parcourir
`.staging/` pour trouver les documents à convertir.

## Détection et contrat T24

- **PDF** : signature et ouverture structurelle PyMuPDF. Un fichier chiffré ou
  réparé à l'ouverture est bloqué ; aucun rendu ni examen complet des pages.
- **DOCX** : ZIP contrôlé, types et relations OPC, partie Word principale locale,
  XML bien formé avec un seul corps cohérent, tailles et CRC des parties vérifiés.
- **DOCM/macros** : DOCM bloqué ; macros cachées dans un DOCX déclaré : refus global.
- **ZIP** : conteneur décompressé uniquement au niveau d'entrée. Extension facultative.
- **Autres** : `unknown`/`ooxml`, non éligibles. TXT/CSV/images ne sont pas convertis.

Une extension trompeuse produit `extension_mismatch`. Les PDF/ZIP polyglottes et
ZIP préfixés/auto-extractibles sont refusés. La validation est structurelle, pas
une preuve de conformité complète PDF/ISO ou de validité de toutes les parties Word.
Les liens externes ne sont jamais suivis ; les documents ne sont jamais exécutés.

Le JSON suit `config/ingestion_manifest.schema.json`, version `p2.ingestion.v1`.
Il contient l'origine, les SHA-256, les tailles, le type réel, le MIME, les chemins,
les dates ZIP (fuseau inconnu), statuts et motifs. `run_directory` et `manifest_path`
sont ajoutés au dictionnaire Python retourné, pas au manifeste enregistré.

Statuts document : `completed`, `completed_with_issues`, `rejected`, `failed` ;
`processing` n'est qu'un état intermédiaire et ne doit jamais être consommé.
Statuts fichier : `ready`, `blocked`, `invalid`, `unsupported`, `directory`,
`not_published`. Un refus global révoque toutes les éligibilités et tous les chemins
publiés dans le manifeste, y compris pour les premiers fichiers déjà inspectés.

T24 devra vérifier **le statut global final ET `eligible_for_t24` par fichier**.
Seuls les types `pdf`/`docx`, avec statut `ready`, sont éligibles. `artifact_path`
est relatif au dossier de l'exécution. Un même contenu sous deux noms différents
n'est pas supprimé : son empreinte permet un rapprochement ultérieur.

## Protections et limites configurables

| Option `IngestionLimits` | Défaut |
|---|---:|
| `max_source_bytes` | 100 Mio |
| `max_file_bytes` | 100 Mio |
| `max_total_bytes` | 500 Mio |
| `max_entries` | 1 000 |
| `max_compression_ratio` | 100 |
| `max_depth` | 16 |
| `max_path_chars` | 180 |
| `max_metadata_bytes` | 8 Mio |
| `max_xml_bytes` | 4 Mio par XML analysé |
| `max_xml_nodes` / `max_xml_depth` | 50 000 / 64 |
| `timeout_seconds` | 60 secondes |
| `max_worker_memory_bytes` | 512 Mio surveillés |

Le budget global compte les octets de copie de la source et les lectures
décompressées, y compris l'inspection des parties DOCX. Il est conservateur et
peut dépasser la somme des tailles des seuls fichiers publiés. Le nombre global
d'entrées inclut les membres Office et les conteneurs imbriqués inspectés.
Les métadonnées ZIP sont bornées avant `ZipFile`. Les flux `stored` et `deflate`
sont lus par blocs, avec taille réelle, fin de flux et CRC contrôlés ; la taille
déclarée ne suffit pas, même avec un CRC falsifié correspondant à un préfixe.

Refus : chemins absolus/lecteurs/UNC/traversées, noms Windows réservés, flux NTFS,
caractères de contrôle, liens/entrées spéciales, collisions Unicode/casse et
fichier/dossier, chiffrement, ZIP64, multidisques, compression autre que 0/8,
chevauchements, disposition non prise en charge et archives corrompues.
L'analyse XML refuse DTD et entités, avec limites de taille, profondeur et nombre
d'éléments. Le worker permet l'arrêt d'un parseur natif bloqué ou en échec.

### Ce qui n'est pas garanti

- Le worker est un processus isolé **sans sandbox de sécurité du système**.
  La surveillance mémoire par échantillonnage n'est pas une limite noyau ; un pic
  bref peut la dépasser avant arrêt. Les délais incluent une marge d'ordonnancement.
- Aucun antivirus, désarmement des documents, nettoyage de JavaScript PDF ou
  suppression des objets embarqués. Un fichier éligible n'est pas une preuve d'innocuité.
- Les dossiers de travail doivent rester privés et non modifiables par un acteur
  local hostile : les contrôles ne garantissent pas l'absence de course système
  si un autre processus remplace simultanément des chemins/jonctions.
- Les XML sont bornés et le processus surveillé, mais les protections ne corrigent
  pas les vulnérabilités des bibliothèques natives. La machine actuelle utilise
  Expat 2.5.0 ; maintenir Python/PyMuPDF à jour devra être validé séparément.
- Politique volontairement restrictive : des archives/documents légitimes peuvent
  être refusés. Les relations Office et parties sont vérifiées selon le sous-ensemble
  décrit ci-dessus, sans validation intégrale du standard Open XML.
- Les tests synthétiques ne remplacent pas un corpus réel ni une revue de sécurité.

## Vérifications

Depuis la racine du dépôt :

```powershell
& .\P2_nlp_extraction\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s .\P2_nlp_extraction\tests -p "test_ingestion_*.py" -v
& .\P2_nlp_extraction\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s .\P2_nlp_extraction\tests -p "test_automatic_pipeline.py" -v
```

Tous les documents de test sont synthétiques et petits ; leurs dossiers
temporaires sont nettoyés. Aucun OCR réel n'est exécuté. La seconde commande
vérifie la non-régression des 17 tests OCR existants.
