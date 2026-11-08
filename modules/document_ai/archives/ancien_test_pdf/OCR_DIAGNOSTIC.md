# Diagnostic historique Docling / RapidOCR de l'ancien PDF de test

> **Archive historique — diagnostic non reproductible en l'état.** Ce rapport conserve les observations des essais du 8 novembre 2026 sur l'ancien document de 12 pages, `data/samples/test.pdf`, aujourd'hui indisponible. Les preuves locales citées ci-dessous sont également indisponibles dans le projet actuel ; leurs anciens chemins, relatifs à la racine du projet, sont conservés comme références historiques, sans liens cliquables. Les mesures et conclusions décrivent les essais de l'époque et ne peuvent pas être revérifiées à partir de cette archive seule. Elles ne concernent pas le DCE de 28 pages utilisé pour T10.

Le script associé est conservé dans [diagnose_ocr.py](diagnose_ocr.py). Anciens emplacements : `modules/document_ai/OCR_DIAGNOSTIC.md` et `modules/document_ai/tests/diagnose_ocr.py`. Le script reste spécifique à l'ancien PDF : objets PDF numérotés, dépendances de l'époque et police Windows `C:/Windows/Fonts/arial.ttf`. Son archivage ne le transforme pas en diagnostic générique.

Diagnostic réalisé le 8 novembre 2026, uniquement sur le module Document AI et les fichiers de test associés.

**Conclusion : deux problèmes distincts sont établis.** Le PDF possède des flux de polices et de correspondance Unicode corrompus, ce qui fait disparaître des lettres avant l'OCR. En plus, la classification d'orientation de RapidOCR dégrade certaines lignes horizontales. Désactiver cette classification améliore la lecture, mais ne restitue pas les lettres absentes du rendu.

## 1. Preuve que l'OCR traite toutes les pages

Lors de ces essais, le test désormais archivé dans [diagnose_ocr.py](diagnose_ocr.py) instrumentait le modèle RapidOCR pendant une conversion complète avec la configuration initiale du script : PDFium, `FULL_PAGE`, `iso:fr`, ONNX Runtime, échelle 3.

- 12 pages effectivement passées dans le modèle OCR.
- Un rectangle couvrant exactement toute la page pour chacune des 12 pages.
- Images transmises au modèle : 1786 × 2526 pixels, soit environ 216 dpi.
- 792 cellules de texte conservées à la sortie de l'étape OCR : toutes portent `from_ocr=True`, aucune cellule native conservée à cette étape.
- Les images effectivement transmises à RapidOCR pour les pages 1 et 2 ont été enregistrées.

Références historiques indisponibles : audit complet, `data/outputs/ocr_diagnostics/baseline_216dpi.json` ; image OCR de la page 2, `data/outputs/ocr_diagnostics/baseline_216dpi_ocr_input_page2.png`.

## 2. Modèle français réellement disponible

Versions installées lors des essais : Docling 2.148.0, RapidOCR 3.10.0, ONNX Runtime 1.31.1, PDFium 5.15.1 et docling-parse 7.24.2.

La langue `iso:fr` est résolue en `fr`. Le modèle chargé est `PP-OCRv6_rec_small.onnx`, un modèle multilingue prenant notamment en charge le français ; il ne s'agit pas d'un modèle exclusivement français. Son alphabet comporte 18 710 entrées et contient notamment `é è à ç ê ô ù î œ`.

Son SHA-256 est `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884`, identique à celui du registre livré avec RapidOCR. Le fichier est présent et effectivement chargé dans une session ONNX Runtime.

Un test indépendant du PDF utilise une image nette contenant trois lignes françaises. Le même modèle reconnaît les 11 lettres accentuées attendues, notamment dans « Répartition de l'équipe », « marchés publics » et « Mémoire technique ». Il subsiste une confusion `IA` / `lA` : ce contrôle prouve la prise en charge des accents, sans certifier une précision parfaite sur tous les documents.

Références historiques indisponibles : image témoin, `data/outputs/ocr_diagnostics/french_control.png` ; texte témoin reconnu, `data/outputs/ocr_diagnostics/baseline_216dpi_french_control.txt` ; rubrique `model` de l'audit complet cité plus haut.

## 3. Cause des lettres manquantes dans le PDF

Un second moteur de rendu déjà installé, PyMuPDF, affiche lui aussi « R partition », « march s » et « M moire ». Il signale des erreurs `zlib error: incorrect header check` et `FT_New_Memory_Face ... unknown file format`.

Les polices DejaVuSans intégrées et leurs tables `ToUnicode` sont stockées dans les objets 16, 17, 20, 21, 24 et 25 du PDF. Ces six flux déclarés `FlateDecode` échouent tous à la décompression zlib. Ils contiennent des milliers de séquences binaires `EF BF BD`, représentant le caractère Unicode de remplacement `�` en UTF-8.

Cela est compatible avec un traitement incorrect de données binaires comme du texte, avec remplacement d'octets invalides. Le diagnostic ne permet pas d'établir quand ni par quel logiciel cette corruption a été introduite. Le nom « ReportLab » dans les métadonnées ne suffit pas à attribuer la faute à ce logiciel.

Le rendu PDFium réellement transmis à l'OCR et le rendu PyMuPDF indépendant présentent les mêmes trous à la place des lettres. Une partie de l'information nécessaire n'est donc plus visible dans les images. Modifier l'encodage du Markdown ne la restitue pas.

Références historiques indisponibles : inspection des flux, `data/outputs/ocr_diagnostics/source_pdf.json` ; page 1 rendue indépendamment, `data/outputs/ocr_diagnostics/original_mupdf_page1.png` ; page 2 rendue indépendamment, `data/outputs/ocr_diagnostics/original_mupdf_page2.png`.

## 4. Cause supplémentaire des lignes presque illisibles

Un test contrôlé réutilise exactement la même image de la page 2 avec le même modèle, les mêmes paramètres et la même détection de texte. La seule différence est `use_cls=False`, qui désactive le classifieur retournant certaines lignes de 180 degrés.

| Correction d'orientation par défaut | Correction désactivée |
|---|---|
| `Lm e      d me    d     rd.` | `La commande publique marocaine d passe 250 milliards de MAD par an, mais y r pondre est lourd.` |
| `Fia,  ni  ns  , e 'e u ie  i : aiset` | `Fiabilit : le m moire n'invente rien, il s'appuie uniquement sur le corpus de l'entreprise.` |

Ces deux lignes sont lisibles et horizontales dans le rendu original. Les autres lignes du test restent identiques. La désactivation corrige donc une dégradation produite par l'OCR, sans remplacement de texte. Elle est adaptée à ce PDF aux lignes horizontales ; un futur document contenant des lignes retournées nécessitera une nouvelle évaluation.

Référence historique indisponible : comparaison à image identique, `data/outputs/ocr_diagnostics/orientation_comparison.json`.

## 5. Résolution et tableaux

Deux configurations supplémentaires compatibles avec Docling ont été testées sur les pages 1 et 2 :

- OCR à 300 dpi : aucun accent récupéré, certaines lignes changent ou se dégradent.
- OCR à 300 dpi avec limite d'image de 4000 pixels, détection de texte à 1280 pixels et classification d'orientation désactivée : aucun accent récupéré ; le titre est davantage fragmenté.

Ces variantes ne sont pas retenues dans le script principal. La correction minimale retenue conserve PDFium et 216 dpi et désactive uniquement la classification d'orientation.

Le tableau « Les 6 modules » de la page 2 a été comparé visuellement : les trois colonnes et les six lignes de modules, plus l'en-tête, sont conservées. Les lettres manquantes du document source restent absentes dans les cellules. L'audit initial détecte douze tableaux sur l'ensemble du document ; ce nombre ne constitue pas une validation de toutes leurs cellules. Certains autres tableaux présentent aussi des regroupements de texte imparfaits.

Références historiques indisponibles : 300 dpi, `data/outputs/ocr_diagnostics/alternative_300dpi.json` ; 300 dpi avec davantage de détails, `data/outputs/ocr_diagnostics/alternative_300dpi_detail.json`. Ces fichiers JSON contenaient les tableaux exportés et les lignes OCR brutes.

## 6. Portée et suite nécessaire

À la date de ces essais, le script principal avait été modifié pour désactiver la classification d'orientation et avertir explicitement si aucun accent n'était extrait. Aucun dictionnaire correcteur, remplacement de mots ou ajout artificiel d'accents n'était utilisé.

Le test complet final s'est terminé avec succès sur les 12 pages en environ 152 secondes de conversion, hors import initial des bibliothèques. Le Markdown régénéré contient 26 571 caractères, contre 25 858 avant la correction d'orientation, et douze tableaux Markdown. Les deux lignes contrôlées ci-dessus sont redevenues lisibles. Il ne contient ni caractère `�` ni caractère de contrôle anormal, mais toujours aucun accent français : **la qualité française complète n'est donc pas validée**. Le PDF original est inchangé, ce qui a été vérifié par SHA-256. La syntaxe des deux scripts a également été vérifiée.

Références historiques finales indisponibles : vérification structurée, `data/outputs/ocr_diagnostics/final_verification.json` ; Markdown régénéré, `data/outputs/docling_result.md`.

Une extraction française complète et fidèle ne peut pas être validée à partir de ce PDF corrompu. Il faut retrouver le fichier binaire intact ou réexporter le document depuis sa source avec des polices valides, puis relancer l'OCR et vérifier les mots, accents, symboles et cellules des tableaux. Aucune précision globale CER/WER n'est annoncée faute de transcription de référence complète.

Aucune dépendance n'a été installée. Aucun autre module n'a été modifié ; aucun commit ni push n'a été effectué.

Référence de configuration : [documentation officielle Docling OCR](https://docling-project.github.io/docling/concepts/OCR/).

## Statut de reproduction de cette archive

L'ancienne procédure de reproduction a été retirée : elle appelait l'ancien emplacement de `diagnose_ocr.py`, puis `modules/document_ai/test_docling.py`, qui traite désormais le DCE de T10. Ces commandes ne reproduisent donc plus le diagnostic décrit ici.

Le script archivé conserve sa source `data/samples/test.pdf` et son ancien dossier de sortie `data/outputs/ocr_diagnostics`. Il vérifie explicitement la présence du PDF avant toute création de sortie. La restauration du PDF exact et la vérification des prérequis historiques seraient nécessaires avant une nouvelle expérience. Aucun remplacement par `test_dce.pdf`, aucune reconstruction des preuves manquantes et aucune relance OCR n'ont été effectués pour cet archivage.
