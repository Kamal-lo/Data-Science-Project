"""Coordonnées, doublons de détection et ordre géométrique prudent."""
import math


def bbox(polygon):
    return [min(p[0] for p in polygon), min(p[1] for p in polygon),
            max(p[0] for p in polygon), max(p[1] for p in polygon)]


def intersection(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0]))*max(0, min(a[3], b[3])-max(a[1], b[1]))


def detections(polygons, scores, width, height):
    kept, duplicates, conflicts = [], [], []
    for index, polygon in enumerate(polygons):
        points = [[float(x), float(y)] for x, y in polygon]
        if len(points) != 4 or not all(math.isfinite(v) for p in points for v in p):
            raise ValueError('Détection non quadrilatérale ou non finie.')
        clipped = [[max(0, min(width, x)), max(0, min(height, y))] for x, y in points]
        box = bbox(clipped)
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError('Boîte de détection vide.')
        record = {'detection_index': index, 'polygon': clipped, 'bbox': box,
                  'detector_confidence': float(scores[index]) if index < len(scores) else None}
        duplicate = None
        for previous in kept:
            a, b = previous['bbox'], box
            overlap = intersection(a, b)
            union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap
            if overlap/union >= 0.90:
                duplicate = previous['detection_index']
                break
            if overlap/union >= 0.30:
                conflicts.append([previous['detection_index'], index])
        if duplicate is None:
            kept.append(record)
        else:
            duplicates.append(dict(record, duplicate_of=duplicate))
    return kept, duplicates, conflicts


def reading_order(blocks):
    rows = []
    for block in sorted(blocks, key=lambda b: (b['bbox'][1], b['bbox'][0])):
        a = block['bbox']
        anchor = rows[-1][0]['bbox'] if rows else None
        if anchor and abs((a[1]+a[3]-anchor[1]-anchor[3])/2) <= 0.5*min(a[3]-a[1], anchor[3]-anchor[1]):
            rows[-1].append(block)
        else:
            rows.append([block])
    result, warnings = [], []
    for row_index, row in enumerate(rows):
        languages = {b['language'] for b in row if b['language'] != 'und'}
        rtl = languages == {'ar'}
        if len(languages) > 1 or 'mixed' in languages:
            warnings.append({'code': 'ambiguous_mixed_row', 'row': row_index})
            for block in row:
                block['needs_review'] = True
                block['warnings'].append('ambiguous_mixed_row')
        if len(row) > 1:
            warnings.append({'code': 'same_row_columns_order_heuristic', 'row': row_index})
        for block in sorted(row, key=lambda b: b['bbox'][0], reverse=rtl):
            result.append(dict(block, reading_order=len(result), row_index=row_index,
                               direction='rtl' if block['language'] == 'ar' else 'ltr' if block['language'] == 'fr' else 'und'))
    return result, warnings
