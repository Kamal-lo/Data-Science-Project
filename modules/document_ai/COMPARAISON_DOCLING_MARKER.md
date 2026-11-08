# T10 — Comparaison Docling / Marker

Date : 8 novembre 2026. Document : `data/samples/test_dce.pdf`, marché de jardinage de l'Institut Supérieur de la Magistrature, 28 pages scannées.

**Évaluation provisoire sur un seul DCE.** La collecte des documents du projet relève de P1. En attendant ces documents, T10 utilise un PDF public de l'Institut Supérieur de la Magistrature, disponible à son [URL officielle](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf). Le PDF et les images de diagnostic restent uniquement locaux ; les résultats textuels sont conservés pour l'équipe. Cette comparaison ne constitue pas une validation du futur corpus de P1. Le PDF local a été comparé au téléchargement officiel : leurs octets et leur SHA-256 sont identiques. Voir le [README du module](README.md) pour retrouver l'entrée et les prérequis des scripts.

**Recommandation : retenir Docling comme moteur principal pour le projet dans l'environnement actuel.** Son texte français est exploitable, il conserve les clauses contrôlées et son temps observé est beaucoup plus court. Marker restitue mieux certaines cellules complexes, notamment en page 25, mais présente des omissions importantes et une erreur de fermeture. Aucun des deux résultats ne permet d'automatiser tous les tableaux sans validation.

## 1. Méthode et portée

Comparaison des deux Markdown existants, des rapports de diagnostic et des images du PDF déjà générées. Contrôles visuels ciblés sur les pages 1, 18, 25, 27 et 28, avec recherche des passages concernés dans les fichiers complets. Les numéros cités sont ceux des pages physiques du PDF ; les marqueurs Marker commencent à zéro (`{24}` correspond à la page 25).

Aucune extraction OCR n'a été relancée. Aucun texte source n'a été corrigé, aucun script ni aucune dépendance n'a été modifié. L'évaluation porte sur ce document et ces configurations, sans transcription exhaustive des 28 pages : aucun score global CER/WER ni pourcentage de précision n'est annoncé. La présence de 28 pages dans un export ne prouve pas que tous leurs passages sont conservés.

## 2. Tableau comparatif

| Critère | Docling | Marker 2.1.0 |
|---|---|---|
| Configuration documentée | PDFium, RapidOCR français `iso:fr`, ONNX Runtime, OCR de toutes les pages | Mode `fast`, OCR forcé, Surya / llama.cpp sur CPU, une requête à la fois ; `use_llm=False` |
| Pages | 28 converties selon le diagnostic | 28 présentes ; métadonnées `surya` sur les 28 pages |
| Français et accents | Globalement lisibles ; erreurs ponctuelles de mots et d'espacement | Globalement lisibles ; quelques espacements mieux conservés, mais erreurs ponctuelles et omissions |
| Titres et sections | Nombreux titres Markdown ; article 46 et introduction présents | Titres, gras et pagination explicite ; article 46 et introduction absents du corps du document |
| Paragraphes et listes | Lisibles ; certains retours et contenus de cellules aplatis | Paragraphes et retours de cellules souvent mieux présentés ; puces parfois doublées (`- ▪`, `- -`) |
| Tableaux exportés | 9 blocs Markdown | 8 blocs Markdown ; journal : `tables_ocr=8`, `tables_total=8` |
| Page 25 : matériel | Déplacements de cellules, accessoires mélangés aux quantités, quantité parasitée | Désignations, quantités et accessoires mieux séparés ; cellules fusionnées simplifiées |
| Page 27 : prix | Deux prestations et trois totaux contrôlés corrects | Mêmes valeurs correctes et affectées aux bonnes colonnes |
| Consignes sous le bordereau | Deux consignes présentes | Deuxième consigne omise |
| Caractères Markdown | 87 609 | 90 150 |
| Lettres françaises accentuées / ligatures, selon les diagnostics | 2 443 | 2 453 |
| `�` / caractères de contrôle anormaux | 0 / 0 | 0 / 0 |
| Temps de conversion consigné | 350,77 s, soit **5 min 51 s**, hors import initial | 10 949,72 s, soit **3 h 02 min 30 s** |
| Fin d'exécution | Succès selon le rapport existant | Markdown et rapport enregistrés, puis exception de nettoyage à la fermeture ; code de commande 1 observé |

Les nombres de caractères et d'accents sont des indicateurs descriptifs, **pas des scores de fidélité**. Le balisage HTML, le gras, les descriptions d'images et les séparateurs de pages augmentent aussi la taille de Marker. Son export plus long contient pourtant des omissions.

Les comptes de tableaux ne sont pas directement équivalents : Docling exporte deux formulaires de la page 2 comme tableaux ; Marker les rend en texte et exporte le formulaire de signature de la page 28. Les continuations sur plusieurs pages comptent séparément. Le dernier formulaire Marker comporte aussi deux lignes de séparation successives, ce qui fragilise son rendu Markdown.

## 3. Fidélité du français et de la structure

Les deux sorties conservent des mots tels que « marché », « exécution », « sécurité » et « végétaux ». En page 18, la phrase « Ces traitements doivent être exécutés selon les règles de l'art et en toute précaution, par des jardiniers expérimentés. » correspond au scan dans les deux exports.

Erreurs et différences confirmées :

- **Espacement des titres :** Docling produit `DEJARDINAGE`, `ENLOT` en page 1 et `DERNIERFEUILLET` en page 28. Marker conserve les espaces de ces expressions.
- **Confusions de lettres :** en page 25, le scan porte « pour l'hiver » et « des casquets ». Docling donne `P'hiver` et `des casquettes` ; Marker donne `Phiver` et `des casquettes`. Un mot français plausible peut donc rester infidèle au document.
- **Omission de section dans Marker :** en bas de la page 25, le scan porte « ARTICLE 46 : RAPPORT D'INTERVENTION », suivi de « Le Prestataire produit à la fin de chaque mois de travail un rapport technique qui : ». Les deux passages sont présents dans Docling et absents du fichier Marker complet. Marker conserve la puce suivante, mais sans son introduction. La mention « ARTICLE 46 : MALFAÇONS » dans le sommaire ne remplace pas cette section du corps du document.
- **Omission d'une consigne dans Marker, page 27 :** « Limiter le montant de la majoration et le montant total TTC après majoration à 2 chiffres après la virgule sans arrondir. » est visible dans le PDF et présente dans Docling, mais absente de Marker. Cette perte concerne une règle de présentation des montants.
- **Caractères parasites :** Docling transforme une puce de la page 18 en `と`. Marker conserve une flèche à cet endroit, mais produit des fragments incohérents dans les en-têtes multilingues de la page 1. Les en-têtes arabe/tifinagh ne sont pas validés dans les deux résultats.
- **Dernière page :** Marker récupère du texte du cachet nominatif et le cadre de signature que Docling laisse comme image. Il ajoute aussi une description anglaise de l'image dans un attribut `alt` ; cette description ne doit pas être assimilée au texte contractuel du PDF. Les signatures et cachets ne sont pas authentifiés par cette comparaison.

Les titres et paragraphes restent globalement reconnaissables, mais leur hiérarchie Markdown ne reproduit pas toujours exactement celle du scan. L'absence de `�` ne détecte ni les omissions, ni les mots incorrects, ni les erreurs de colonnes.

## 4. Tableaux et valeurs numériques

### Page 25 — Matériel et quantités

| Élément du PDF original | Docling | Marker |
|---|---|---|
| Sécateur : désignation à gauche, quantité `01` au centre | `Sécateur` déplacé dans la troisième colonne | Bonne colonne de désignation et quantité `01` |
| Tuyaux flexibles : `02 Rouleau de (50m)` ; accessoires à droite | Accessoires et quantité mélangés dans la colonne quantité | Quantité distincte ; accessoires placés à droite sur la ligne de catégorie |
| Tourniquet `02`, arrosoir `01` | Valeurs conservées | Valeurs conservées |
| Pulvérisateurs et poudreuse : `01` chacun | Valeurs conservées ; accessoires répétés sur plusieurs lignes | Valeurs conservées ; accessoires regroupés sur la catégorie |
| Houe, binette, pelle, râteau, pioche : `01` chacun | Valeurs conservées | Valeurs conservées |
| Véhicule et brouettes : `01` ; sac : `Forfait` | Valeurs conservées | Valeurs conservées |
| Balais à gazon : `01` | Cellule erronée `01 de 13` | Cellule correcte `01` |

**Avantage Marker sur ce tableau.** Il reste une limite commune : les cellules fusionnées du scan sont aplaties en Markdown. Marker ne conserve pas explicitement leur étendue sur plusieurs lignes ; un lecteur automatique ne doit pas interpréter les cellules accessoires vides comme une absence d'accessoires. La ligne « Sécateur », continuation du tableau de la page précédente, est utilisée comme en-tête Markdown dans les deux exports.

### Page 27 — Bordereau des prix

Les valeurs suivantes correspondent au PDF **dans les deux exports**, avec les bonnes unités et colonnes :

| Prestation | Unité | Quantité | Prix unitaire HT | Prix total HT |
|---|---|---|---|---|
| Entretien quotidien, 8 heures du lundi au vendredi, 1 agent | Jours | 260 | 208,66 | 54 251,60 |
| Entretien trimestriel, 8 heures le dernier samedi du trimestre, 2 agents | Jours | 8 | 208,66 | 1 669,28 |

| Total du PDF | Docling | Marker |
|---|---|---|
| HT : `55 920,88` | Conforme | Conforme |
| TVA 20 % : `11 184,17` | Conforme | Conforme |
| TTC : `67 105,05` | Conforme | Conforme |

Contrôle arithmétique : `260 × 208,66 = 54 251,60` ; `8 × 208,66 = 1 669,28` ; leur somme vaut `55 920,88`. La TVA arrondie au centime et le TTC correspondent aux montants imprimés. Les trois champs de majoration laissés vides dans le scan restent vides dans les deux sorties. Aucun de ces montants n'a été corrigé dans les fichiers.

**Égalité sur les cellules financières contrôlées ; avantage Docling sur la complétude de la page**, grâce à la seconde consigne conservée.

### Autre limite constatée, page 18

Dans le tableau d'engrais, Marker sépare « NPK » de « Apport d'engrais complet » en une ligne autonome et décale les périodes associées. Docling conserve les textes mais regroupe plusieurs désignations et périodes dans une seule cellule, ce qui perd les associations ligne par ligne. La valeur `30 à 50 g/m²` reste lisible dans les deux. Aucun outil ne restitue donc uniformément tous les tableaux du document.

## 5. Temps d'exécution et limites techniques

**Le temps de Docling est disponible** dans le rapport DCE : 350,77 secondes de conversion, hors import initial. Son temps total de lancement n'y est pas consigné.

Le rapport Marker indique 10 949,72 secondes de conversion et 10 984,09 secondes au total, soit **3 h 03 min 04 s**, imports, initialisation et nettoyage mesuré compris. Le premier lancement a téléchargé et chargé les modèles ; une partie de ces opérations intervient pendant la conversion. L'environnement documenté utilise llama.cpp CPU, une requête à la fois et environ 8 Go de RAM, dont moins de 1 Go libre au départ.

Ces temps décrivent les essais existants : ils ne proviennent pas d'un protocole identique avec caches et ressources contrôlés. Ils montrent une différence opérationnelle importante sur ce poste, mais ne permettent ni de comparer les seules vitesses OCR, ni de prévoir le temps de Marker sur GPU.

Après l'enregistrement du Markdown, Marker affiche `Exception ignored in atexit callback`, dans `surya/inference/backends/spawn.py`, ligne 327, fonction `_cleanup`. La commande a renvoyé le code 1. Le rapport indique pourtant `status: converted`, les 28 pages et les métriques du fichier. Il a été écrit avant cette exception de sortie : son statut ne garantit donc pas une fermeture sans erreur. La trace conservée est incomplète ; la cause exacte n'est pas établie et aucun manque de mémoire n'est explicitement signalé. Les processus associés étaient terminés lors du diagnostic final.

Cette anomalie n'annule pas les fichiers produits, mais constitue une limite pour un pipeline automatisé : l'existence d'un résultat et la réussite du processus doivent être contrôlées séparément. Aucune correction ni nouvelle exécution n'a été effectuée pour ce rapport.

## 6. Choix proposé pour le projet

Retenir **Docling pour l'extraction principale des documents français**, au vu de son délai observé, de sa fin d'exécution sans erreur rapportée et de la conservation des clauses contrôlées. Sa qualité suffit à une première lecture et à la recherche de passages, sous réserve de conserver le PDF comme référence.

Conserver **Marker comme candidat complémentaire pour les tableaux complexes**, car la page 25 démontre un gain réel de placement des cellules. Son export actuel ne doit toutefois pas remplacer automatiquement celui de Docling : les omissions des pages 25 et 27 et l'erreur de fermeture doivent être résolues avant un usage principal. Un éventuel essai GPU ferait l'objet d'un test séparé et autorisé ; aucun gain n'est supposé acquis ici.

Pour les quantités, prix et totaux, prévoir un contrôle des cellules et de leur cohérence arithmétique, avec validation humaine des cas ambigus. Les deux outils réussissent le bordereau contrôlé, mais échouent sur certains autres tableaux. Cette recommandation reste limitée à ce DCE ; sa généralisation à d'autres marchés, notamment bilingues, demanderait un échantillon plus large.

## Sources locales

- [PDF public de référence, à télécharger séparément](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf) ; emplacement local attendu : `data/samples/test_dce.pdf` (exclu de Git).
- [Markdown Docling](../../data/outputs/docling_dce_result.md) et [Markdown Marker](../../data/outputs/marker_dce_result.md)
- [Rapport DCE Docling : temps et observations](../../data/outputs/dce_diagnostics/rapport.md) ; [diagnostic structuré Docling](../../data/outputs/dce_diagnostics/verification.json)
- [Diagnostic Marker : configuration, temps, pages et métriques](../../data/outputs/marker_diagnostics/20261108T174743218178Z/verification.json) ; [conditions d'exécution](../../data/outputs/marker_diagnostics/20261108T174743218178Z/runtime_conditions.json)
- Pages comparées visuellement, consultables dans le PDF officiel : [page 1](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf#page=1), [page 18](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf#page=18), [page 25](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf#page=25), [page 27](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf#page=27), [page 28](https://ism.ma/wp-content/uploads/2024/02/CPS.pdf#page=28). Les images locales `data/outputs/dce_diagnostics/original_page*.png` ne sont pas versionnées ; leur absence après un clone est volontaire. La prise en charge de `#page=` dépend du lecteur PDF ; à défaut, ouvrir le document et aller à la page indiquée.
- [Journal du test Marker : statistiques de tableaux et exception de fermeture](../../data/outputs/marker_diagnostics/20261108T174743218178Z/extraction_dce.log) — copie à l'identique du journal local ; original conservé dans `.venv-marker/extraction_dce.log`. Le journal est encodé en UTF-16 LE.

Traçabilité : le SHA-256 du PDF actuel correspond à celui du rapport Marker (`e7b529f09720b63c07f6fb728d51a8ded9e8c527162d91591770241cf08e5bb1`). Celui du Markdown Docling correspond à l'empreinte enregistrée avant le test Marker (`e46fdd00cfe887948ec09e7473f5204899fb87ddc6e2d56f2e2804ffec73b739`).
