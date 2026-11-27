"""Recover closed rectangular grids from scanned pages using existing OCR blocks."""
from .layout import area, intersection, order_blocks
from .models import new_block


def _grid_rows(boxes):
    rows = []
    for box in sorted(boxes, key=lambda cell: cell[1]):
        if not rows or box[1] - rows[-1][0][1] > 8:
            rows.append([])
        rows[-1].append(box)
    for row in rows:
        row.sort()
    if len(rows) < 2 or len(rows[0]) < 2:
        return []
    for row in rows:
        if len(row) != len(rows[0]) or max(c[3] for c in row) - min(c[3] for c in row) > 8:
            return []
        if any(not 0 <= right[0] - left[2] <= 12 for left, right in zip(row, row[1:])):
            return []
        if any(abs(cell[0] - ref[0]) > 12 or abs(cell[2] - ref[2]) > 12
               for cell, ref in zip(row, rows[0])):
            return []
    if any(not 0 <= below[0][1] - above[0][3] <= 12 for above, below in zip(rows, rows[1:])):
        return []
    return rows


def _closed_grids(gray, cv2, budget):
    height, width = gray.shape
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, 31, 8)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, width // 12), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, height // 35))))
    mask = cv2.dilate(horizontal | vertical, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    contours, tree = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if tree is None:
        return
    children = {}
    for index, link in enumerate(tree[0]):
        parent = link[3]
        if parent < 0:
            continue
        x, y, w, h = cv2.boundingRect(contours[index])
        if w >= 18 and h >= 12:
            children.setdefault(parent, []).append((x, y, x + w, y + h))
    for index, boxes in children.items():
        budget.tick()
        x, y, w, h = cv2.boundingRect(contours[index])
        if w < width * .18 or h < height * .035:
            continue
        rows = _grid_rows(boxes)
        if rows or (len(boxes) >= 4 and max(b[0] for b in boxes) - min(b[0] for b in boxes) > 12
                    and max(b[1] for b in boxes) - min(b[1] for b in boxes) > 8):
            yield (x, y, x + w, y + h), rows, boxes


def _short_vertical_rules(gray, boxes, budget):
    """Recover short rulings that the page-wide morphology can miss."""
    starts = {}
    for box in boxes:
        starts.setdefault(box[0], []).append(box)
    axes = set()
    for left, top, right, bottom in boxes:
        for x in range(right, right + 9):
            if any(min(bottom, b[3]) - max(top, b[1]) >= 12 for b in starts.get(x, ())):
                axes.add((right + x) // 2)
    refined, evidence = [], []
    for left, top, right, bottom in boxes:
        budget.tick()
        edges = []
        for axis in sorted(axes):
            if not left + 16 <= axis <= right - 16 or bottom - top < 16:
                continue
            top_trimmed, bottom_trimmed = top + 2, bottom - 2
            # Use the pixels of the observed ruling, not OCR alignment alone.
            dark = gray[top_trimmed:bottom_trimmed, axis - 3:axis + 4] < 150
            quarter = max(3, len(dark) // 4)
            supported = ((dark.mean(axis=0) >= .90)
                         & (dark[:quarter].mean(axis=0) >= .8)
                         & (dark[-quarter:].mean(axis=0) >= .8))
            if not supported.any() or (edges and axis - edges[-1] <= 8):
                continue
            edges.append(axis)
            evidence.append((axis, top, axis, bottom))
        for a, b in zip([left, *edges], [*edges, right]):
            if b > a:
                refined.append((a, top, b, bottom))
    return refined, evidence


def _fits_cell(block, bounds, padded, cv2, np):
    bbox = block['bbox']
    size = area(bbox)
    if size <= 0:
        return False
    if intersection(padded, bbox) >= .85 * size:
        return True
    # A tilted OCR line can have empty corners in its enclosing rectangle.
    # Recheck its actual quadrilateral only for a strong single-cell overlap.
    if intersection(bounds, bbox) < .75 * size:
        return False
    geometry = block.get('ocr_geometry') or {}
    pixels, polygon = geometry.get('bbox'), geometry.get('polygon')
    if not pixels or not polygon or len(polygon) != 4 or area(pixels) <= 0:
        return False
    points = np.asarray(polygon, dtype=np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all() or not cv2.isContourConvex(points):
        return False
    if [*points.min(axis=0), *points.max(axis=0)] != pixels:
        return False
    points -= pixels[:2]
    points *= [(bbox[2] - bbox[0]) / (pixels[2] - pixels[0]),
               (bbox[3] - bbox[1]) / (pixels[3] - pixels[1])]
    points += bbox[:2]
    left, top, right, bottom = padded
    cell = np.float32([[left, top], [right, top], [right, bottom], [left, bottom]])
    covered, _ = cv2.intersectConvexConvex(points, cell)
    return covered >= .85 * cv2.contourArea(points)


def add_scan_tables(page, blocks, limits, budget):
    """Keep unassigned text and never fill a cell from an uncertain hypothesis."""
    import pymupdf
    try:
        import cv2
        import numpy as np
    except ImportError:
        return blocks, ['scan_table_detection_requires_opencv']

    budget.tick()
    if (2 * page.rect.width + 1) * (2 * page.rect.height + 1) > limits.max_pixels:
        return blocks, ['scan_table_raster_pixel_limit']
    image = page.get_pixmap(dpi=144, colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(image.samples, dtype=np.uint8).reshape(image.height, image.width)
    scale_x, scale_y = page.rect.width / image.width, page.rect.height / image.height

    def pdf_box(box):
        x0, y0, x1, y1 = box
        return [round(x0 * scale_x, 4), round(y0 * scale_y, 4),
                round(x1 * scale_x, 4), round(y1 * scale_y, 4)]

    tables, warnings = [], []
    for outer, rows, boxes in _closed_grids(gray, cv2, budget):
        if len(boxes) > limits.max_table_cells:
            warnings.append('scan_table_cell_limit')
            continue
        box = pdf_box(outer)
        candidates = [b for b in blocks if b['method'] == 'ocr' and b.get('render', True) and b.get('bbox')
                      and intersection(box, b['bbox']) > .5 * area(b['bbox'])]
        if not rows:
            if candidates:
                refined, rules = _short_vertical_rules(gray, boxes, budget) if len(boxes) <= 128 else (boxes, [])
                if len(refined) > min(128, limits.max_table_cells):
                    refined, rules = boxes, []
                cell_boxes = [pdf_box(cell) for cell in sorted(refined)]
                for block in candidates:
                    if any(intersection(cell, block['bbox']) >= .85 * area(block['bbox'])
                           for cell in cell_boxes):
                        block['warnings'].append('ambiguous_table_cell')
                table = new_block('table', None, 'ocr', page=page.number + 1, bbox=box,
                                  structure_preserved=False, render_fragments=False,
                                  source_reference={
                                      'grid_method': 'scan_irregular_cell_candidates_v1',
                                      'geometry_dpi': 144,
                                      'candidate_cell_boxes': cell_boxes,
                                      **({'raster_verified_dividers': [pdf_box(rule) for rule in rules],
                                          'original_candidate_cell_boxes': [pdf_box(cell) for cell in sorted(boxes)]}
                                         if rules else {}),
                                      'ocr_block_ids': [b['source_reference'].get('ocr_block_id') for b in candidates],
                                  })
                table['needs_review'] = True
                table['warnings'].append('scan_table_irregular_grid_not_reconstructed')
                tables.append(table)
            continue
        cells, metadata = [], []
        assigned = set()
        for row_index, row in enumerate(rows):
            values = []
            for column, cell in enumerate(row):
                bounds = pdf_box(cell)
                padded = [bounds[0] - 1, bounds[1] - 1, bounds[2] + 1, bounds[3] + 1]
                matches = [b for b in candidates if id(b) not in assigned
                           and _fits_cell(b, bounds, padded, cv2, np)]
                matches = order_blocks(matches)
                value = ('\n'.join(b['raw_text'] for b in matches)
                         if matches and all(b['raw_text'] is not None for b in matches) else None)
                values.append(value)
                metadata.append({'row': row_index, 'column': column, 'bbox': bounds, 'text': value,
                                 'ocr_block_ids': [b['source_reference'].get('ocr_block_id') for b in matches]})
                if value is not None:
                    assigned.update(map(id, matches))
            cells.append(values)
        if not assigned:
            continue
        for block in candidates:
            if id(block) in assigned:
                block['render'] = False
                block['warnings'].append('represented_in_table')
        table = new_block('table', None, 'ocr', page=page.number + 1, bbox=box, cells=cells,
                          structure_preserved=True, cell_metadata=metadata,
                          source_reference={'grid_method': 'scan_closed_rectangular_cells_v1',
                                            'geometry_dpi': 144})
        table['needs_review'] = True
        table['warnings'].append('scan_table_grid_and_header_inferred')
        tables.append(table)
    return (order_blocks(blocks + tables) if tables else blocks), warnings
