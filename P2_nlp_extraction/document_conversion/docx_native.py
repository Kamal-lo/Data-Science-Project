"""Lecture DOCX après précontrôle ZIP/XML borné ; pagination physique inconnue."""
from dataclasses import replace

from ..document_ingestion.models import Budget as IngestionBudget, IngestionLimits
from ..document_ingestion.zip_extraction import checked_zip, read_member
from ..document_ingestion.detection import _xml, _part_name
from .layout import language
from .models import ConversionFailure, new_block


def preflight(path, limits, budget):
    ilimits = replace(IngestionLimits(), max_file_bytes=limits.max_docx_expanded_bytes,
                      max_total_bytes=limits.max_docx_expanded_bytes + limits.max_xml_part_bytes,
                      max_xml_bytes=limits.max_xml_part_bytes,
                      timeout_seconds=max(.01, budget.remaining))
    ibudget = IngestionBudget(ilimits)
    xml_total = 0
    with checked_zip(path, ibudget) as (archive, entries):
        total = sum(e['info'].file_size for e in entries)
        if total > limits.max_docx_expanded_bytes:
            raise ConversionFailure('docx_expansion_limit', 'DOCX décompressé trop volumineux.')
        # Les parties XML OPC peuvent avoir une extension quelconque. Ne pas
        # limiter le contrôle aux noms *.xml avant le parsing par python-docx.
        content = next(e for e in entries if e['relative_path'] == '[Content_Types].xml')
        types_data = read_member(archive, content['info'], ibudget, cap=limits.max_xml_part_bytes)['data']
        xml_parts, xml_extensions = set(), set()
        def content_type(name, attrs, depth):
            mime = attrs.get('ContentType', '').lower()
            if 'xml' not in mime:
                return
            if name.endswith('|Override'):
                xml_parts.add(str(_part_name(attrs['PartName'], ilimits, absolute=True)))
            elif name.endswith('|Default'):
                xml_extensions.add(attrs['Extension'].lower())
        _xml(types_data, ibudget, content_type)
        for entry in entries:
            budget.tick()
            if entry['is_directory']:
                continue
            name = entry['relative_path']
            is_xml = name.lower().endswith(('.xml', '.rels')) or name in xml_parts or name.rsplit('.', 1)[-1].lower() in xml_extensions
            if is_xml:
                xml_total += entry['info'].file_size
                if xml_total > limits.max_xml_total_bytes:
                    raise ConversionFailure('docx_xml_limit', 'Somme des parties XML trop volumineuse.')
                data = read_member(archive, entry['info'], ibudget, cap=limits.max_xml_part_bytes)['data']
                _xml(data, ibudget, lambda *args: None)
            else:
                read_member(archive, entry['info'], ibudget)


def _style_numpr(paragraph):
    props = paragraph._p.pPr
    if props is not None and props.numPr is not None:
        return props.numPr
    style, seen = paragraph.style, set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        props = style.element.pPr
        if props is not None and props.numPr is not None:
            return props.numPr
        style = style.base_style
    return None


def _list_info(paragraph, document):
    from docx.oxml.ns import qn
    props = _style_numpr(paragraph)
    if props is None or props.numId is None or props.numId.val == 0:
        return None
    num_id = props.numId.val
    level = props.ilvl.val if props.ilvl is not None else 0
    result = {'num_id': num_id, 'level': level, 'format': None, 'label_template': None}
    try:
        numbering = document.part.numbering_part.element
        number = next(n for n in numbering.findall(qn('w:num')) if int(n.get(qn('w:numId'))) == num_id)
        abstract_id = number.find(qn('w:abstractNumId')).get(qn('w:val'))
        abstract = next(a for a in numbering.findall(qn('w:abstractNum')) if a.get(qn('w:abstractNumId')) == abstract_id)
        lvl = next(l for l in abstract.findall(qn('w:lvl')) if int(l.get(qn('w:ilvl'))) == level)
        fmt, label = lvl.find(qn('w:numFmt')), lvl.find(qn('w:lvlText'))
        result.update(format=fmt.get(qn('w:val')) if fmt is not None else None,
                      label_template=label.get(qn('w:val')) if label is not None else None)
    except (AttributeError, StopIteration, KeyError):
        pass
    # Ne pas inventer une numérotation Word : overrides/restarts non rendus par v1.
    result['numbering_rendered'] = False
    return result


def extract_docx(path, options, limits, budget):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    preflight(path, limits, budget)
    document = Document(str(path))
    blocks, sections, warnings = [], [], ['docx_physical_pagination_unavailable']
    characters = 0

    def paragraph_block(p, role):
        text = p.text
        if not text and not p._p.xpath('.//w:br | .//w:drawing | .//w:fldChar'):
            return None
        style = p.style.name if p.style is not None else None
        level = None
        prop = p._p.pPr
        if prop is not None and prop.find(qn('w:outlineLvl')) is not None:
            level = int(prop.find(qn('w:outlineLvl')).get(qn('w:val'))) + 1
        elif style and style.lower().startswith('heading '):
            try:
                level = int(style.split()[-1])
            except ValueError:
                pass
        if level is None:
            candidate, visited = p.style, set()
            while candidate is not None and candidate.style_id not in visited:
                visited.add(candidate.style_id)
                candidate_prop = candidate.element.pPr
                outline = candidate_prop.find(qn('w:outlineLvl')) if candidate_prop is not None else None
                if outline is not None:
                    level = int(outline.get(qn('w:val'))) + 1
                    break
                candidate = candidate.base_style
        listing = _list_info(p, document)
        kind = 'heading' if level and level <= 6 else 'list_item' if listing else 'paragraph'
        b = new_block(kind, text, 'docx_xml', source_reference={
            'part': str(p.part.partname), 'xml_path': p._p.getroottree().getpath(p._p)},
                      role=role, style=style, runs=[{'text': r.text, 'bold': r.bold, 'italic': r.italic} for r in p.runs])
        b['language'] = language(text)
        b['direction'] = 'rtl' if p._p.xpath('./w:pPr/w:bidi') or b['language'] == 'ar' else 'ltr'
        if level:
            b['heading_level'] = min(6, max(1, level))
        if listing:
            b['list'] = listing
            if listing['format'] != 'bullet':
                b['warnings'].append('word_numbering_not_reconstructed')
                b['needs_review'] = True
        if p._p.xpath('.//w:br[@w:type="page"] | .//w:lastRenderedPageBreak'):
            b['warnings'].append('explicit_page_break_not_a_physical_page_number')
            b['page_break'] = True
        if p._p.xpath('.//w:drawing | .//w:pict'):
            b['warnings'].append('embedded_image_not_ocr_processed')
            b['needs_review'] = True
        if p._p.xpath('.//w:fldChar | .//w:instrText'):
            b['warnings'].append('field_cached_text_only_not_recomputed')
        return b

    def table_block(table, role):
        row_nodes = table._tbl.findall(qn('w:tr'))
        if sum(len(r.findall(qn('w:tc'))) for r in row_nodes) > limits.max_table_cells:
            raise ConversionFailure('table_limit', 'Table DOCX trop volumineuse.')
        cells, grid, simple = [], [], True
        grid_node = table._tbl.find(qn('w:tblGrid'))
        grid_width = len(grid_node.findall(qn('w:gridCol'))) if grid_node is not None else None
        nested = False
        for row_index, row in enumerate(row_nodes):
            values = []
            row_props = row.find(qn('w:trPr'))
            before = row_props.find(qn('w:gridBefore')) if row_props is not None else None
            after = row_props.find(qn('w:gridAfter')) if row_props is not None else None
            column = int(before.get(qn('w:val'))) if before is not None else 0
            if before is not None or after is not None:
                simple = False
            for cell in row.findall(qn('w:tc')):
                budget.tick()
                prop = cell.find(qn('w:tcPr'))
                span_node = prop.find(qn('w:gridSpan')) if prop is not None else None
                span = int(span_node.get(qn('w:val'))) if span_node is not None else 1
                if span < 1 or span > limits.max_table_cells:
                    raise ConversionFailure('table_limit', 'Fusion de cellules excessive ou invalide.')
                vmerge = prop.find(qn('w:vMerge')) if prop is not None else None
                # Les paragraphes de cellules sont conservés dans l'ordre XML ;
                # le texte de tableaux imbriqués reste explicitement un fragment.
                text = '\n'.join(''.join(t.text or '' for t in child.iter(qn('w:t')))
                                 for child in cell if child.tag in (qn('w:p'), qn('w:tbl')))
                nested_tables = cell.findall(qn('w:tbl'))
                if nested_tables:
                    nested = True
                grid.append({'row': row_index, 'column': column, 'column_span': span,
                             'vertical_merge': vmerge.get(qn('w:val'), 'continue') if vmerge is not None else None,
                             'text': text})
                simple = simple and span == 1 and vmerge is None and not nested_tables
                values.append(text)
                column += span
            cells.append(values)
            if grid_width is None or column != grid_width:
                simple = False
        simple = simple and bool(cells) and len({len(r) for r in cells}) == 1 and bool(cells[0])
        b = new_block('table', '\n'.join('\t'.join(r) for r in cells), 'docx_xml',
                      cells=cells, cell_metadata=grid, structure_preserved=simple, role=role,
                      source_reference={'part': str(table.part.partname), 'xml_path': table._tbl.getroottree().getpath(table._tbl)})
        b['language'] = language(b['raw_text'])
        b['needs_review'] = True
        b['warnings'].append('table_first_row_used_as_markdown_header' if simple else 'complex_table_structure_not_preserved')
        if nested:
            b['warnings'].append('nested_table_retained_as_fragments')
        return b

    def collect(container, role):
        nonlocal characters
        for element in container.iter_inner_content():
            budget.tick()
            b = paragraph_block(element, role) if isinstance(element, Paragraph) else table_block(element, role)
            if b:
                blocks.append(b)
                characters += len(b['raw_text'] or '')
            if len(blocks) > limits.max_blocks or characters > limits.max_output_bytes:
                raise ConversionFailure('block_limit', 'Document DOCX trop volumineux.')

    collect(document, 'body')
    seen_parts = set()
    for number, section in enumerate(document.sections, 1):
        budget.tick()
        entry = {'section': number, 'page': None, 'headers': [], 'footers': []}
        for role in ('header', 'footer', 'first_page_header', 'first_page_footer', 'even_page_header', 'even_page_footer'):
            container = getattr(section, role)
            # L'accès à .part pourrait créer un en-tête absent : ne rien créer.
            if container.is_linked_to_previous:
                continue
            part = str(container.part.partname)
            entry['headers' if 'header' in role else 'footers'].append(part)
            if part not in seen_parts:
                seen_parts.add(part)
                collect(container, role)
        sections.append(entry)
    root = document.element
    if root.xpath('.//w:ins | .//w:del | .//w:sdt | .//w:txbxContent'):
        warnings.append('revisions_content_controls_or_text_boxes_may_be_omitted')
    part_names = [str(p.partname) for p in document.part.package.parts]
    if any('footnotes' in n or 'endnotes' in n or 'comments' in n for n in part_names):
        warnings.append('notes_or_comments_not_rendered')
    return blocks, sections, warnings
