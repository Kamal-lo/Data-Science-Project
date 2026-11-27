"""Use explicit T24 matrices; keep uncertain structures as partial artifacts."""
import copy
import csv
import io
import json
from .columns import FIELDS, header_columns, normalize, arithmetic, number
from ..document_conversion.layout import area, intersection


def _edge_indices(edges):
    # Close contours exclude the ruling itself. Collapse the edges on either
    # side of a ruling, allowing small skew in the scanned image.
    indices = {}
    lowest = None
    index = -1
    for edge in sorted(set(edges)):
        if lowest is None or edge - lowest > 5:
            index += 1
            lowest = edge
        indices[edge] = index
    return indices, index


def _recover_grid(table, ocr, max_cells):
    source = table['source_reference']
    if source.get('grid_method') != 'scan_irregular_cell_candidates_v1':
        return None
    boxes = source.get('candidate_cell_boxes')
    ids = source.get('ocr_block_ids')
    if not isinstance(boxes, list) or not 4 <= len(boxes) <= 128 or not isinstance(ids, list) or len(ids) > 512:
        return None
    if not all(isinstance(b, list) and len(b) == 4 and all(type(v) in (int, float) for v in b)
               and area(b) > 0 and intersection(b, table['bbox']) == area(b) for b in boxes):
        return None
    x, width = _edge_indices(v for b in boxes for v in (b[0], b[2]))
    y, height = _edge_indices(v for b in boxes for v in (b[1], b[3]))
    if min(width, height) < 2 or width * height > min(1024, max_cells):
        return None
    positions = {}
    spans = []
    for index, (left, top, right, bottom) in enumerate(boxes):
        row, col, end_row, end_col = y[top], x[left], y[bottom], x[right]
        if row >= end_row or col >= end_col:
            return None
        spans.append((row, col, end_row, end_col))
        for r in range(row, end_row):
            for c in range(col, end_col):
                if (r, c) in positions:
                    return None
                positions[r, c] = index
    assignments = [[] for _ in boxes]
    ambiguous = [[] for _ in boxes]
    unassigned = False
    for ocr_id in dict.fromkeys(i for i in ids if isinstance(i, str)):
        block = ocr.get((table['page'], ocr_id))
        if not block or not block['bbox'] or not area(block['bbox']):
            unassigned = True
            continue
        total = area(block['bbox'])
        coverage = [intersection(box, block['bbox']) / total for box in boxes]
        best = max(range(len(boxes)), key=coverage.__getitem__)
        left, top, right, bottom = boxes[best]
        padded = [left - 1, top - 1, right + 1, bottom + 1]
        if (coverage[best] > .5 and intersection(padded, block['bbox']) >= .85 * total
                and all(part <= .15 for index, part in enumerate(coverage) if index != best)):
            assignments[best].append(block)
        else:
            unassigned = True
            for index, fraction in enumerate(coverage):
                if fraction > .15:
                    ambiguous[index].append(ocr_id)
    if not any(assignments):
        return None
    matrix = [[None] * width for _ in range(height)]
    metadata = []
    for (r, c), index in positions.items():
        row, col, end_row, end_col = spans[index]
        if (r, c) != (row, col):
            metadata.append(dict(row=r, column=c, covered_by=[row, col]))
            continue
        fragments = sorted(assignments[index], key=lambda block: (
            block['reading_order'] if type(block.get('reading_order')) is int else 0))
        texts = [b['raw_text'] for b in fragments]
        if texts and all(value is not None and value.strip() for value in texts):
            matrix[r][c] = '\n'.join(texts)
        alternatives = {b['source_reference']['ocr_block_id']: b['recognition_candidates']
                        for b in fragments if not b['raw_text'] and b.get('recognition_candidates')}
        metadata.append(dict(row=r, column=c, bbox=boxes[index],
                             row_span=end_row-row, column_span=end_col-col,
                             ocr_block_ids=[b['source_reference']['ocr_block_id'] for b in fragments],
                             t24_block_ids=[b['block_id'] for b in fragments],
                             **({'ocr_alternatives': alternatives} if alternatives else {}),
                             **({'ambiguous_ocr_block_ids': ambiguous[index]} if ambiguous[index] else {})))
    return matrix, metadata, unassigned


def _price_number_header(table, columns, ocr):
    """Recognize a split 'Prix / N°' label without transcribing a rejected OCR value."""
    if table['source_reference'].get('grid_method') != 'scan_closed_rectangular_cells_v1':
        return None
    if any('price_number' in c['candidates'] for c in columns):
        return None
    matches = []
    for cell in table.get('cell_metadata', []):
        col = cell.get('column') if isinstance(cell, dict) else None
        if (type(col) is not int or not 0 <= col < len(columns) or cell.get('row') != 0
                or columns[col]['header_raw'] is not None):
            continue
        ids = cell.get('ocr_block_ids', [])
        if len(ids) != 2:
            continue
        label, marker = (ocr.get((table['page'], i)) for i in ids)
        if not label or normalize(label['raw_text']) != 'prix' or not marker or marker['raw_text']:
            continue
        readings = {(v.get('text') or '').strip().casefold()
                    for v in marker.get('recognition_candidates', {}).values()}
        if readings & {'n°', 'nº'} and readings <= {'n°', 'nº', 'no', 'no.'}:
            matches.append(col)
    return matches[0] if len(matches) == 1 else None


def _column_edges(table):
    edges = {}
    for row in table['rows']:
        for cell in row['cells']:
            geometry = cell['source']['cell_metadata'] or {}
            if geometry.get('column_span') == 1 and geometry.get('bbox'):
                left, _, right, _ = geometry['bbox']
                edges.setdefault(cell['column'], (left, right))
    return [edges[index] for index in range(len(table['columns']))] if len(edges) == len(table['columns']) else []


def _continuation_reason(previous, current):
    if (previous['section'] != current['section'] or not previous['pages'] or not current['pages']
            or current['pages'][0] != previous['pages'][0] + 1):
        return None
    if previous['header_row_index'] is not None and current['header_row_index'] is not None:
        previous_labels, current_labels = (
            [normalize(c['header_raw']) for c in table['columns']] for table in (previous, current)
        )
        return 'matching_headers_on_consecutive_pages' if previous_labels == current_labels else None
    if (previous['section'] is None
            or previous['classification'] != current['classification']
            or any(t['source_block']['source_reference'].get('grid_method')
                   != 'scan_irregular_cell_candidates_v1' for t in (previous, current))):
        return None
    left, right = map(_column_edges, (previous, current))
    # The same scan grid can drift by a few points between physical pages.
    if len(left) >= 2 and len(left) == len(right) and all(
            abs(a - c) <= 5 and abs(b - d) <= 5 for (a, b), (c, d) in zip(left, right)):
        return 'aligned_scan_columns_on_consecutive_pages'
    return None


def extract(document, segmentation=None, *, max_cells=200000):
    tables = []
    roots = segmentation['sections'] if segmentation else []
    ocr = {}
    for block in document['blocks']:
        ocr_id = block['source_reference'].get('ocr_block_id')
        if block['method'] == 'ocr' and isinstance(ocr_id, str):
            key = (block['page'], ocr_id)
            ocr[key] = None if key in ocr else block
    remaining = max_cells
    for block in document['blocks']:
        if block['type'] != 'table': continue
        bid = block['block_id']
        associations = [s for s in roots if bid in s['source_block_ids']]
        section = associations[0] if len(associations)==1 else None
        warnings = list(block['warnings'])
        context = (dict(section_id=section['section_id'], category=section['category'],
                        title_raw=section['title_raw'], confidence=copy.deepcopy(section['confidence']),
                        needs_review=True, warnings=copy.deepcopy(section['warnings'])) if section else None)
        if context: warnings.append('section_association_is_unvalidated_hypothesis')
        if len(associations)>1: warnings.append('ambiguous_section_association')
        matrix = block.get('cells')
        recovered = _recover_grid(block, ocr, remaining)
        if recovered:
            matrix, recovered_metadata, unassigned = recovered
            warnings = [warning for warning in warnings if warning != 'scan_table_irregular_grid_not_reconstructed']
            if unassigned:
                warnings.append('ocr_fragments_left_unassigned')
        valid = (isinstance(matrix, list) and bool(matrix) and all(isinstance(r,list) for r in matrix)
                 and bool(matrix[0]) and len({len(r) for r in matrix})==1
                 and all(c is None or isinstance(c,str) for r in matrix for c in r))
        structured = valid and block.get('structure_preserved') is True
        table = dict(table_id=f't{len(tables)+1:06d}', source_block_ids=[bid],
                     pages=[block['page']] if block['page'] is not None else [], bbox=copy.deepcopy(block['bbox']),
                     language=block['language'], source_block=copy.deepcopy(block), section=context,
                     status='completed_with_review' if structured else 'partial',
                     human_validated=False, needs_review=True, classification='undetermined',
                     classification_evidence=[], columns=[], header_row_index=None, rows=[], price_lines=[],
                     continuation_candidates=[], warnings=warnings)
        in_bpu = context and context['category']=='BPU'
        if in_bpu:
            table['classification']='bpu'; table['classification_evidence'].append('t26_bpu_section')
        native_geometry = valid and block['method'] == 'native_pdf' and block.get('cell_metadata')
        if not structured:
            if not native_geometry and not recovered:
                warnings.append('structure_not_reliable_no_cells_reconstructed')
                if not valid: warnings.append('missing_or_invalid_cell_matrix')
                tables.append(table); continue
            warnings.append('irregular_contours_reconstructed_for_review' if recovered
                            else 'native_cells_exported_without_inferring_prices')
        columns, supported = header_columns(matrix[0]) if structured else ([], False)
        header_end = 0
        if structured and len(matrix) >= 3 and not any(number(value) is not None for value in matrix[1]):
            combined = [' '.join(part.strip() for part in pair if part and part.strip())
                        for pair in zip(matrix[0], matrix[1])]
            joined_columns, joined_supported = header_columns(combined)
            if joined_supported and sum(bool(c['field']) for c in joined_columns) > sum(bool(c['field']) for c in columns):
                columns, supported, header_end = joined_columns, True, 1
                warnings.append('multiline_headers_inferred_from_adjacent_rows')
        if supported and header_end == 0:
            col = _price_number_header(block, columns, ocr)
            if col is not None:
                columns[col].update(field='price_number', candidates=['price_number'])
                warnings.append('price_number_from_split_ocr_header')
        fields = {c['field'] for c in columns if c['field']}
        if any(len(c['candidates'])>1 or (c['candidates'] and c['field'] is None) for c in columns):
            warnings.append('ambiguous_or_duplicate_column_labels')
        if supported:
            table['columns'] = columns; table['header_row_index']=header_end
            warnings.append('first_row_header_is_heuristic')
        else:
            table['columns']=[dict(index=i,header_raw=None,field=None,candidates=[]) for i in range(len(matrix[0]))]
            fields=set();warnings.append('header_not_identified_no_price_lines_inferred')
        if not in_bpu:
            if {'designation','unit_price'} <= fields:
                table['classification']='bpu_candidate'
                table['classification_evidence'].append('designation_and_unit_price_headers')
                warnings.append('bpu_candidate_without_confirmed_section')
            elif any(set(c['candidates']) & {'unit_price','amount'} for c in columns):
                table['classification']='price_table'
                table['classification_evidence'].append('price_header')
            else: table['classification']='ordinary'
        if table['classification'] in ('bpu','bpu_candidate'):
            warnings.extend('missing_column_'+f for f in FIELDS if f not in fields)
        remaining -= sum(map(len, matrix))
        if remaining < 0:
            raise ValueError('Limite de cellules dépassée.')
        metadata = recovered_metadata if recovered else block.get('cell_metadata', [])
        metadata = metadata if isinstance(metadata,list) else []
        metadata_index = {}
        for entry in metadata:
            if isinstance(entry,dict) and type(entry.get('row')) is int and type(entry.get('column')) is int:
                key=(entry['row'],entry['column'])
                if key in metadata_index:
                    metadata_index[key]=None
                    warnings.append('duplicate_cell_metadata_not_assigned')
                else:metadata_index[key]=entry
        for row_index, row in enumerate(matrix):
            repeated = supported and row_index > header_end and [normalize(c) for c in row] == [normalize(c['header_raw']) for c in columns]
            kind = 'header_candidate' if row_index <= header_end and supported else 'repeated_header_candidate' if repeated else 'data'
            cells = []
            for col_index, value in enumerate(row):
                source_meta = metadata_index.get((row_index,col_index))
                covered = source_meta and 'covered_by' in source_meta
                status = 'covered' if covered else 'unreadable' if value is None else 'empty' if not value.strip() else 'present'
                cell = dict(row=row_index,column=col_index,value=value,
                            status=status,
                            source=dict(block_id=bid,page=block['page'],bbox=None,
                                        table_bbox=copy.deepcopy(block['bbox']),
                                        source_reference=copy.deepcopy(block['source_reference']),
                                        cell_metadata=copy.deepcopy(source_meta)))
                # Native PDF and DOCX may lack individual cell geometry.
                if source_meta and 'bbox' in source_meta: cell['source']['bbox']=copy.deepcopy(source_meta['bbox'])
                if recovered and source_meta:
                    cell['source']['source_reference'] = {'grid_method': 'scan_irregular_cell_candidates_v1',
                                                          **copy.deepcopy(source_meta)}
                cells.append(cell)
            table['rows'].append(dict(index=row_index,kind=kind,cells=cells))
            if any(c['status'] in ('empty', 'unreadable') for c in cells): warnings.append('empty_or_unreadable_cells')
            if any(c['status']=='unreadable' for c in cells):table['status']='partial'
            if not supported or not fields or kind!='data' or table['classification'] not in ('bpu','bpu_candidate'):continue
            selected = {c['field']:dict(value=row[c['index']],row=row_index,column=c['index'],source_block_id=bid)
                        for c in columns if c['field']}
            line_warnings=[]
            if not any(v is not None and v.strip() for v in row):
                warnings.append('empty_row_retained_without_price_line');continue
            if any(v['value'] is None or not v['value'].strip() for v in selected.values()):line_warnings.append('empty_or_unreadable_mapped_value')
            check=arithmetic(selected)
            if check and check['status']=='mismatch':line_warnings.append('arithmetic_difference_observed_not_corrected')
            table['price_lines'].append(dict(row=row_index,page=block['page'],source_block_id=bid,
                                            fields=selected,missing_fields=[f for f in FIELDS if f not in selected],
                                            arithmetic_check=check,needs_review=True,warnings=line_warnings))
        table['warnings']=list(dict.fromkeys(warnings));tables.append(table)
    # Potential continuations only. Never concatenate or delete repeated rows.
    for previous,current in zip(tables,tables[1:]):
        reason = _continuation_reason(previous, current)
        if reason:
            for a,b in ((previous,current),(current,previous)):
                a['continuation_candidates'].append(dict(table_id=b['table_id'],needs_review=True,
                                                         reason=reason))
                a['warnings'].append('possible_multipage_continuation_not_merged')
    return tables


def _csv(header, rows):
    stream=io.StringIO(newline='')
    writer=csv.writer(stream,delimiter=';',lineterminator='\r\n')
    writer.writerow(header);writer.writerows(rows)
    return stream.getvalue().encode('utf-8-sig')


def tables_csv(tables):
    rows=[]
    for table in tables:
        for row in table['rows']:
            for cell in row['cells']:
                source=cell['source']
                rows.append([table['table_id'],cell['row'],cell['column'],cell['value'],cell['status'],
                             source['page'],source['block_id'],json.dumps(source['bbox']),
                             json.dumps(source['table_bbox']),json.dumps(source['source_reference'],ensure_ascii=False)])
    return _csv(['table_id','row','column','value','cell_status','page','block_id','cell_bbox','table_bbox','source_reference'],rows)


def bpu_csv(tables):
    rows=[]
    for table in tables:
        for line in table['price_lines']:
            rows.append([table['table_id'],line['row'],line['page'],line['source_block_id'],table['classification']]+
                        [line['fields'].get(f,{}).get('value') for f in FIELDS]+
                        [json.dumps(line['missing_fields']),json.dumps(line['warnings'],ensure_ascii=False)])
    return _csv(['table_id','row','page','block_id','classification']+list(FIELDS)+['missing_fields','warnings'],rows)
