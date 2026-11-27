"""Structure OCR inférée dans T24, distincte des reconnaissances originales.

Les boîtes donnent une hauteur de ligne, pas une taille de police réelle. Une
hiérarchie n'est proposée qu'avec un corps de texte de référence et un titre
dominant isolé. Aucun dictionnaire de corrections, modèle ou règle métier DCE.
"""
import math
import re
from statistics import median


RULE_VERSION = 'p2.ocr_structure.v1'
AMBIGUOUS = ('columns', 'overlap', 'ambiguous', 'unresolved')
LIST_MARKER = re.compile(r'^\s*(?:[-•▪●]|\d+[.)]|[A-Za-z][.)])\s+')


def _eligible(block):
    box = block.get('bbox')
    return (block.get('method') == 'ocr' and block.get('type') == 'paragraph'
            and block.get('render', True) and isinstance(block.get('raw_text'), str)
            and bool(block['raw_text'].strip()) and block.get('language') in ('fr', 'ar')
            and isinstance(box, list) and len(box) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box)
            and box[2] > box[0] and box[3] > box[1]
            and not any(any(word in warning for word in AMBIGUOUS) for warning in block.get('warnings', [])))


def _height(block):
    return (block['bbox'][3] - block['bbox'][1]) / max(1, len(block['raw_text'].splitlines()))


def _center(block):
    return (block['bbox'][0] + block['bbox'][2]) / 2


def _uppercase(text):
    return sum(c.isalpha() for c in text) >= 5 and text.isupper()


def _heading_line(block, body_height, width):
    if not _eligible(block) or body_height is None or not width:
        return False
    text, h = block['raw_text'], _height(block)
    if not 5 <= len(text) <= 140 or '\n' in text or LIST_MARKER.match(text):
        return False
    if abs(_center(block) - width / 2) > .045 * width or text.rstrip().endswith(('.', ';', ':', '?', '!')):
        return False
    if block['language'] == 'fr':
        return _uppercase(text) and h >= body_height * 1.15
    # L'arabe n'a pas de casse : exiger une différence de hauteur plus forte.
    return h >= body_height * 1.65 and sum(c.isalpha() for c in text) >= 5


def _same_heading(a, b):
    ha, hb = _height(a), _height(b)
    gap = b['bbox'][1] - a['bbox'][3]
    return (a.get('page') == b.get('page') and a['language'] == b['language']
            and max(ha, hb) / min(ha, hb) <= 1.18
            and -.1 * min(ha, hb) <= gap <= .65 * min(ha, hb)
            and abs(_center(a) - _center(b)) <= .65 * min(ha, hb))


def _paragraph_pair(a, b):
    if not (_eligible(a) and _eligible(b)):
        return False
    if a.get('page') != b.get('page') or a['language'] != b['language'] or a.get('direction') != b.get('direction'):
        return False
    ta, tb = a['raw_text'], b['raw_text']
    if min(len(ta.strip()), len(tb.strip())) < 25 or _uppercase(ta) or _uppercase(tb):
        return False
    if LIST_MARKER.match(ta) or LIST_MARKER.match(tb) or ta.rstrip().endswith(('.', '!', '?', ':', ';', '؟', '؛', '：')):
        return False
    if any(sum(c.isdigit() for c in t) / max(1, len(t.replace(' ', ''))) > .35 for t in (ta, tb)):
        return False
    x, y = a['bbox'], b['bbox']
    ha, hb = _height(a), _height(b)
    gap = y[1] - x[3]
    horizontal = max(0, min(x[2], y[2]) - max(x[0], y[0])) / min(x[2] - x[0], y[2] - y[0])
    edge = 2 if a['language'] == 'ar' else 0
    aligned = abs(x[edge] - y[edge]) <= 1.5 * min(ha, hb)
    centered = abs(_center(a) - _center(b)) <= .5 * min(ha, hb)
    return (max(ha, hb) / min(ha, hb) <= 1.25
            and -.15 * min(ha, hb) <= gap <= .6 * min(ha, hb)
            and horizontal >= .8 and (aligned or centered))


def _union(sources):
    boxes = [s['bbox'] for s in sources if s.get('bbox')]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None


def structure_page(page, document_id):
    """Retourne les groupes OCR seulement ; ne remplace aucun bloc source.

    Les IDs des blocs doivent avoir été attribués avant cet appel. Les groupes
    référencent des blocs contigus de la liste fournie : aucune permutation ni
    fusion à travers un bloc natif, inconnu, masqué ou d'une autre langue.
    """
    blocks = page['blocks']
    for b in blocks:
        b.pop('structure_group_id', None)
    reference = [_height(b) for b in blocks if _eligible(b) and len(b['raw_text']) >= 45
                 and not _uppercase(b['raw_text']) and not LIST_MARKER.match(b['raw_text'])]
    # Les longues lignes peuvent aussi être des sous-titres : estimer le corps
    # dans la moitié basse des hauteurs, avec au moins trois références.
    body = median(sorted(reference)[:max(3, (len(reference) + 1) // 2)]) if len(reference) >= 3 else None
    candidates, i = [], 0
    while i < len(blocks):
        if not _heading_line(blocks[i], body, page.get('width')):
            i += 1
            continue
        end = i + 1
        while end < len(blocks) and _heading_line(blocks[end], body, page.get('width')) and _same_heading(blocks[end - 1], blocks[end]):
            end += 1
        sources = blocks[i:end]
        h = median(_height(b) for b in sources)
        previous_box = blocks[i - 1].get('bbox') if i else None
        before = sources[0]['bbox'][1] - previous_box[3] if previous_box else None
        isolated = before is None or before >= body
        candidates.append({'start': i, 'end': end, 'height': h, 'isolated': isolated,
                           'preceding_gap': before, 'bbox': _union(sources)})
        i = end
    primary = [c for c in candidates if c['isolated'] and c['bbox'][1] < page.get('height', 0) * .5
               and c['height'] >= body * (1.5 if c['end'] - c['start'] > 1 else 1.75)]
    # Deux dominantes de taille comparable ne prouvent aucune racine unique.
    primary.sort(key=lambda c: c['height'], reverse=True)
    anchor = primary[0] if primary and (len(primary) == 1 or primary[0]['height'] >= primary[1]['height'] * 1.2) else None
    headings = {}
    if anchor:
        headings[anchor['start']] = (anchor, 1)
        for c in candidates:
            if c['start'] >= anchor['end'] and c['isolated'] and c['height'] < anchor['height'] * .95:
                headings[c['start']] = (c, 2)
    candidate_indices = {j for c in candidates for j in range(c['start'], c['end'])}
    groups, i = [], 0
    while i < len(blocks):
        b = blocks[i]
        if b.get('method') != 'ocr' or b.get('type') == 'table' or not b.get('render', True):
            i += 1
            continue
        start, level, evidence = i, None, {}
        if i in headings:
            c, level = headings[i]
            i = c['end']
            kind, rule = 'heading', 'isolated_centered_height_hierarchy'
            evidence = {'body_line_height': body, 'line_height': c['height'], 'preceding_gap': c['preceding_gap'],
                        'height_is_font_size': False, 'root_source_block_ids': [s['block_id'] for s in blocks[anchor['start']:anchor['end']]]}
        else:
            i += 1
            while i < len(blocks) and i not in candidate_indices and i - 1 not in candidate_indices and _paragraph_pair(blocks[i - 1], blocks[i]):
                i += 1
            kind = b['type']
            rule = 'aligned_adjacent_lines' if i - start > 1 else 'original_ocr_block'
        sources = blocks[start:i]
        texts = [s.get('raw_text') for s in sources]
        group_id = f'{document_id}_p{page["page"]:04d}_s{len(groups) + 1:06d}'
        warnings = list(dict.fromkeys(w for s in sources for w in s['warnings']))
        if rule != 'original_ocr_block':
            warnings.append('structure_inferred_from_geometry_not_human_validated')
        elif start in candidate_indices:
            warnings.append('possible_heading_hierarchy_insufficient')
        group = {'group_id': group_id, 'type': kind, 'method': 'ocr', 'page': page['page'],
                 'source_block_ids': [s['block_id'] for s in sources], 'raw_texts': texts,
                 'text': ' '.join(texts) if all(t is not None for t in texts) else None,
                 'bbox': _union(sources), 'language': b['language'],
                 'direction': b.get('direction') if b.get('direction') in ('ltr', 'rtl', 'und') else 'und',
                 'join_policy': 'space_between_source_blocks', 'human_validated': False,
                 'needs_review': True, 'warnings': warnings, 'markdown_lines': None,
                 'inference': {'version': RULE_VERSION, 'rule': rule, 'evidence': evidence}}
        if level is not None:
            group['heading_level'] = level
        groups.append(group)
        for s in sources:
            s['structure_group_id'] = group_id
    return groups
