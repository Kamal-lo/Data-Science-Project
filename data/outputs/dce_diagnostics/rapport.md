# Test Docling sur le DCE scanné

Test réalisé le 8 novembre 2026 avec l'environnement Python existant, sans installation de dépendance.

## Fichiers et configuration

- Le fichier fourni s'appelait `data/samples/test_dce.pdf.pdf`. Sa double extension a été corrigée en `data/samples/test_dce.pdf`.
- Le script `modules/document_ai/test_docling.py` lit désormais ce PDF et écrit dans `data/outputs/docling_dce_result.md`.
- L'ancien chemin de sortie `docling_result.md` n'est pas utilisé. Ce fichier était absent du dossier au début du test.
- Configuration conservée : PDFium, OCR RapidOCR français `iso:fr`, ONNX Runtime, toutes les pages, échelle 3 (216 dpi), correction d'orientation des lignes désactivée.
- Les commentaires du script ne présentent plus le nouveau PDF comme un document aux polices corrompues. Le nombre de tableaux est maintenant affiché.

## Résultat de l'exécution

| Contrôle | Résultat |
|---|---|
| Pages du PDF | 28 |
| Pages sans couche texte native | 28 : document scanné |
| Pages converties par Docling | 28 |
| Statut de conversion | Succès |
| Temps de conversion, hors import initial | 350,77 secondes, soit environ 5 min 51 s |
| Caractères Markdown | 87 609 |
| Lettres de la liste française `FRENCH_LETTERS` | 2 443, accents et ligatures compris |
| Caractères de remplacement `�` | 0 |
| Caractères de contrôle anormaux | 0 |
| Tableaux détectés et exportés | 9, formulaires et continuations sur plusieurs pages compris |

## Qualité du français et des accents

Des passages ont été comparés aux images originales, notamment les pages 1, 3, 18, 25, 27 et 28. Le texte français est globalement lisible et les accents sont effectivement reconnus.

Exemples trouvés dans le résultat : `marché`, `supérieur`, `exécution`, `réception`, `sécurité`, `préventif`, `végétaux`, `coopérative`, `précautions`, `règles`, `expérimentés`.

Le passage de la page 18 « Ces traitements doivent être exécutés selon les règles de l'art et en toute précaution, par des jardiniers expérimentés. » est lisible dans le Markdown et correspond au scan. Le titre et le texte de la dernière page sont également présents.

Il subsiste des erreurs de segmentation, par exemple `DEJARDINAGE`, `ENLOT` et `DERNIERFEUILLET`. Une puce de la page 18 est reconnue à tort comme le caractère japonais `と`. Zéro caractère `�` ne signifie donc pas zéro erreur OCR.

Les en-têtes arabe/tifinagh, ainsi que les cachets et signatures, ne sont pas validés avec cette configuration française. Certaines de ces zones restent des marqueurs d'image ; d'autres produisent des fragments incohérents comme `all21al`.

## Contrôle des tableaux

Le tableau technique de la page 18 conserve ses colonnes et des contenus accentués tels que `30 à 50 g/m²`, `Périodes (mois)` et `Fréquence`. Les lignes multiples d'une cellule sont aplaties dans le Markdown ; la poursuite du tableau sur la page suivante est exportée séparément.

Le bordereau des prix de la page 27 est correctement structuré en six colonnes et deux lignes de prestations. Les valeurs suivantes ont été comparées visuellement au scan et vérifiées dans les cellules Markdown :

| Ligne | Unité | Quantité | P.U. HT | P.T. HT |
|---|---|---|---|---|
| 1 | Jours | 260 | 208,66 | 54 251,60 |
| 2 | Jours | 8 | 208,66 | 1 669,28 |

Les trois totaux contrôlés sont également corrects : HT `55 920,88`, TVA `11 184,17`, TTC `67 105,05`. Les champs de majoration laissés vides dans le PDF restent vides dans le Markdown.

Des défauts de structure ont été confirmés sur la page 25 :

- `Sécateur`, situé dans la colonne de désignation du scan, se retrouve dans la troisième colonne de la première ligne exportée, qui est aussi traitée comme un en-tête.
- Les accessoires d'arrosage sont mélangés à la quantité des tuyaux flexibles, au lieu de rester dans la colonne Accessoires.
- Certaines cellules fusionnées sont dupliquées ou aplaties ; des fragments parasites apparaissent, par exemple `01 de 13` pour la quantité de « Balais à gazon ».

Le résultat convient à une première lecture et à une recherche textuelle. L'exploitation automatique des cellules de tous les tableaux nécessite une validation supplémentaire. Aucun taux global de précision CER/WER n'est annoncé faute de transcription complète de référence.

## Preuves et portée

Note de préparation GitHub : ce test sur un DCE public est provisoire, dans l'attente du corpus collecté par P1. Le PDF et les images restent locaux ; les pages de référence sont consultables dans le PDF officiel ci-dessous. Les observations et métriques historiques sont conservées.

- [Résultat Markdown](../docling_dce_result.md)
- [Contrôles structurés et cellules des neuf tableaux](verification.json)
- Planche des 28 pages : fichier local `data/outputs/dce_diagnostics/contact_pages.png`, non versionné.
- [PDF officiel de référence](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf) : [page 18](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf#page=18), [page 25](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf#page=25), [page 27](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf#page=27). Si le lecteur ignore le fragment `#page=`, aller manuellement à la page indiquée.

Aucune correction artificielle d'accents ou de mots n'a été appliquée. Aucun autre module n'a été modifié ; aucun commit ni push n'a été effectué.

Pour relancer depuis la racine du projet :

```powershell
.\.venv\Scripts\python.exe modules\document_ai\test_docling.py
```
