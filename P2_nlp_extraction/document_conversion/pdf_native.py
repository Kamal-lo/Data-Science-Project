"""Extraction native progressive PyMuPDF (aucune rasterisation haute résolution)."""
import re
from statistics import median
import unicodedata

from .layout import area, intersection, language, order_blocks
from .models import ConversionFailure, new_block
from .routing import choose_route, native_quality


def canonical_box(page, box):
    """Points PDF, origine haut-gauche de la page affichée, rotation comprise.

    get_text / find_tables renvoient des coordonnées non tournées ; le pipeline
    OCR existant renvoie déjà des points de la page affichée.
    """
    import pymupdf
    rect = pymupdf.Rect(box) * page.rotation_matrix
    return [round(v, 4) for v in rect]


def _arabic_form(char):
    return '\ufb50' <= char <= '\ufdff' or '\ufe70' <= char <= '\ufefc'


def _suspect_arabic_mapping(span):
    """Detect a broken Arabic-font mapping that yields unrelated Latin glyphs."""
    text = span['text']
    return ('arabic' in span['font'].lower()
            and any(_arabic_form(char) for char in text)
            and any(ord(char) > 255 and unicodedata.name(char, '').startswith('LATIN') for char in text))


def extract_page(page, options, limits, budget):
    import pymupdf
    budget.tick()
    # TEXTFLAGS_DICT sans images : ne pas charger les bitmaps dans le dictionnaire.
    data = page.get_text('dict', flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    text_blocks = [b for b in data['blocks'] if b.get('type') == 0]
    if len(text_blocks) > limits.max_blocks_per_page:
        raise ConversionFailure('block_limit', 'Trop de blocs natifs sur la page.')
    chars = sum(len(s['text']) for b in text_blocks for line in b['lines'] for s in line['spans'])
    if chars > limits.max_characters_per_page:
        raise ConversionFailure('character_limit', 'Trop de caractères natifs sur la page.')
    sizes = [s['size'] for b in text_blocks for l in b['lines'] for s in l['spans'] if s['text'].strip()]
    body_size = median(sizes) if sizes else 12
    blocks = []
    for index, source in enumerate(text_blocks):
        budget.tick()
        text = '\n'.join(''.join(s['text'] for s in line['spans']) for line in source['lines'])
        if not text.strip():
            continue
        spans = [dict(text=s['text'], font=s['font'], size=s['size'], flags=s['flags'],
                      bbox=canonical_box(page, s['bbox'])) for l in source['lines'] for s in l['spans']]
        size = max(s['size'] for s in spans)
        kind = 'heading' if size >= max(body_size * 1.25, 14) and len(text) < 250 else 'paragraph'
        bullet = re.match(r'^\s*(?:[•●▪\-–]|\d+[.)]|[A-Za-z][.)])\s+', text)
        if bullet:
            kind = 'list_item'
        block = new_block(kind, text, 'native_pdf', page=page.number + 1,
                          bbox=canonical_box(page, source['bbox']),
                          source_reference={'native_block_index': index, 'spans': spans},
                          native_usable=(native_quality(text)['usable']
                                         and not any(_suspect_arabic_mapping(span) for span in spans)))
        block['language'] = language(text)
        block['direction'] = 'rtl' if block['language'] == 'ar' else 'ltr'
        if block['native_usable'] and any(_arabic_form(char) for char in text):
            block['text'] = ''.join(unicodedata.normalize('NFKC', char) if _arabic_form(char) else char
                                    for char in text)
        if kind == 'heading':
            block['heading_level'] = 1 if size >= body_size * 1.7 else 2
            block['warnings'].append('heading_inferred_from_font_size')
        if not block['native_usable']:
            block['needs_review'] = True
            block['warnings'].append('unusable_native_encoding')
            block['render'] = False
        blocks.append(block)
    warnings = []
    if options.extract_tables:
        try:
            tables = page.find_tables()
            candidates_tables = tables.tables
            borderless = not candidates_tables and 9 <= len(sizes) <= 200
            if borderless:
                candidates_tables = page.find_tables(strategy='text').tables
            for table_index, table in enumerate(candidates_tables):
                budget.tick()
                if table.row_count * table.col_count > limits.max_table_cells:
                    raise ConversionFailure('table_limit', 'Table PDF trop volumineuse.')
                cells = table.extract()
                geometry = table.rows
                if borderless:
                    from ..table_extraction.columns import header_columns
                    # The text strategy inserts empty rows into vertical whitespace.
                    nonempty = [i for i, row in enumerate(cells) if any(c and c.strip() for c in row)]
                    cells = [cells[i] for i in nonempty]
                    geometry = [geometry[i] for i in nonempty]
                    headers, _ = header_columns(cells[0] if cells else [])
                    if len(cells) < 2 or sum(column['field'] is not None for column in headers) < 3:
                        continue
                box = canonical_box(page, table.bbox)
                candidates = [b for b in blocks if b['type'] != 'table']
                contained = [b for b in candidates if intersection(box, b['bbox']) / max(1e-9, area(b['bbox'])) >= .95]
                partial = any(intersection(box, b['bbox']) > 0 and b not in contained for b in candidates)
                simple = bool(cells) and table.col_count > 0 and all(len(r) == table.col_count and all(c is not None for c in r) for r in cells) and not partial
                table_block = new_block('table', '\n'.join('\t'.join(c or '' for c in row) for row in cells),
                                        'native_pdf', page=page.number + 1, bbox=box,
                                        cells=cells, structure_preserved=simple,
                                        cell_metadata=[
                                            {'row': row_index, 'column': column, 'bbox': canonical_box(page, rect)}
                                            for row_index, row in enumerate(geometry)
                                            for column, rect in enumerate(row.cells) if rect is not None
                                        ],
                                        source_reference={'native_table_index': table_index})
                table_block['needs_review'] = True
                table_block['warnings'].append('table_detection_and_header_are_inferred' if simple else 'complex_table_structure_not_preserved')
                if borderless:
                    table_block['warnings'].append('borderless_grid_inferred_from_text_alignment')
                if simple:
                    for b in contained:
                        b['render'] = False
                        b['warnings'].append('represented_in_table')
                else:
                    # Garder les fragments natifs et une notice, sans deuxième texte plat.
                    table_block['fragments'] = [b['raw_text'] for b in contained]
                    table_block['render_fragments'] = False
                blocks.append(table_block)
        except ConversionFailure:
            raise
        except Exception:
            warnings.append('table_detection_failed_native_fragments_kept')
    embedded = page.get_image_info()
    images = [canonical_box(page, item['bbox']) for item in embedded]
    graphics = [
        dict(kind='raster', index=index, bbox=box, pixel_size=[item['width'], item['height']])
        for index, (item, box) in enumerate(zip(embedded, images))
        if area(box) > 0
    ]
    for index, (operator, bounds) in enumerate(page.get_bboxlog()):
        if operator not in ('fill-path', 'stroke-path', 'fill-shade'):
            continue
        box = canonical_box(page, bounds)
        if box[2] - box[0] >= 12 and box[3] - box[1] >= 12:
            graphics.append(dict(kind='vector', index=index, bbox=box, operator=operator))
    if len(graphics) > limits.max_blocks_per_page:
        graphics = graphics[:limits.max_blocks_per_page]
        warnings.append('graphics_inventory_limit')
    # Distinguer une page vide d'un tracé vectoriel ou d'un scan sans texte.
    ink = False
    if not blocks and not images:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(.15, .15), colorspace=pymupdf.csGRAY, alpha=False)
        ink = any(v < 240 for v in pix.samples)
    routing = choose_route([b for b in blocks if b['type'] != 'table'], images, list(page.rect), ink)
    if len(blocks) > limits.max_blocks_per_page:
        raise ConversionFailure('block_limit', 'Trop de blocs natifs et de tableaux sur la page.')
    return {'page': page.number + 1, 'label': page.get_label() or None,
            'width': page.rect.width, 'height': page.rect.height,
            'rotation': page.rotation, 'status': 'native_ready', 'routing': routing, 'graphics': graphics,
            'warnings': warnings + routing['warnings'], 'errors': [],
            'blocks': order_blocks(blocks)}
