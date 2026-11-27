"""Ordre géométrique prudent, coordonnées canoniques et fusion des hypothèses."""
import re
import unicodedata


def intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def overlap(a, b):
    return intersection(a, b) / max(1e-9, min(area(a), area(b)))


def language(text):
    ar = sum(unicodedata.name(c, '').startswith('ARABIC') and c.isalpha() for c in text)
    latin = sum('LATIN' in unicodedata.name(c, '') and c.isalpha() for c in text)
    return 'mixed' if ar and latin else 'ar' if ar else 'fr' if latin else 'und'


def normalize(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text)).strip()


def order_blocks(blocks):
    """Tri haut-bas ; même ligne droite-gauche si ses blocs sont arabes.

    Les colonnes / chevauchements restent explicitement ambigus (pas d'analyse métier).
    """
    # Signaler aussi deux colonnes dont les sommets ne sont pas alignés.
    ambiguous = set()
    for i, a in enumerate(blocks):
        for j in range(i + 1, len(blocks)):
            b = blocks[j]
            x, y = a.get('bbox'), b.get('bbox')
            if x and y and (x[2] + 12 < y[0] or y[2] + 12 < x[0]) and min(x[3], y[3]) - max(x[1], y[1]) > 6:
                ambiguous.update((i, j))
    for index in ambiguous:
        blocks[index]['needs_review'] = True
        if 'possible_columns_reading_order_ambiguous' not in blocks[index]['warnings']:
            blocks[index]['warnings'].append('possible_columns_reading_order_ambiguous')
    rows = []
    for block in sorted(blocks, key=lambda b: (b.get('bbox') or [0, 0, 0, 0])[1]):
        box = block.get('bbox')
        if not box:
            rows.append([block]); continue
        row = next((r for r in rows if r[0].get('bbox') and abs(r[0]['bbox'][1] - box[1]) <= 4), None)
        if row is None:
            rows.append([block])
        else:
            row.append(block)
    result = []
    for row in rows:
        rtl = all(b.get('language') == 'ar' for b in row)
        row.sort(key=lambda b: (b.get('bbox') or [0])[0], reverse=rtl)
        if len(row) > 1:
            for b in row:
                b['needs_review'] = True
                b['warnings'].append('reading_order_columns_or_same_row')
        result.extend(row)
    for i, b in enumerate(result, 1):
        b['reading_order'] = i
    return result


def merge_native_ocr(native, ocr):
    """Déduplique seulement si texte identique ET chevauchement spatial.

    Une divergence reste dans les hypothèses JSON ; le texte natif exploitable
    garde la priorité d'affichage et la décision est signalée.
    """
    result = list(native)
    for candidate in ocr:
        matches = [b for b in native if b.get('bbox') and candidate.get('bbox')
                   and overlap(b['bbox'], candidate['bbox']) >= .75]
        same = next((b for b in matches if normalize(b['raw_text'] or '') == normalize(candidate['raw_text'] or '')), None)
        if same:
            same.setdefault('alternative_recognitions', []).append(candidate)
            same['warnings'].append('duplicate_ocr_suppressed')
        elif matches:
            # Un gros bloc OCR peut recouvrir plusieurs paragraphes natifs : ne pas le jeter.
            contained = next((b for b in matches if intersection(b['bbox'], candidate['bbox']) / max(area(candidate['bbox']), 1e-9) >= .85), None)
            if contained and contained.get('native_usable', True):
                contained.setdefault('alternative_recognitions', []).append(candidate)
                contained['needs_review'] = True
                contained['warnings'].append('native_ocr_conflict_native_displayed')
            else:
                candidate['needs_review'] = True
                candidate['warnings'].append('possible_overlap_or_conflicting_native_text')
                result.append(candidate)
        else:
            result.append(candidate)
    return order_blocks(result)
