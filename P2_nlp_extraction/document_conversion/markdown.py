"""Rendu Markdown UTF-8 traçable ; le JSON conserve toujours les données brutes."""
import html
import re


def escape(text):
    text = html.escape(text or '', quote=False)
    return re.sub(r'([\\`*_\[\]{}#!|>])', r'\\\1', text)


def render_block(block):
    if not block.get('render', True):
        return []
    text = escape(block.get('text')).replace('\n', '  \n')
    if block['type'] == 'unresolved':
        return ['> [Texte OCR indéterminé — hypothèses conservées dans le JSON.]']
    if block['type'] == 'table':
        rows = block.get('cells', [])
        if block.get('structure_preserved') and rows and rows[0]:
            def line(row):
                return '| ' + ' | '.join(escape(c).replace('\n', '<br>') for c in row) + ' |'
            return [line(rows[0]), '| ' + ' | '.join('---' for _ in rows[0]) + ' |', *[line(r) for r in rows[1:]]]
        notice = '> [Tableau complexe : structure non restituée ; cellules et positions disponibles dans le JSON.]'
        if block.get('render_fragments', True):
            return [notice, '', *['> ' + escape(c['text']).replace('\n', ' / ') for c in block.get('cell_metadata', [])]]
        return [notice]
    if block['type'] == 'heading':
        return ['#' * block.get('heading_level', 2) + ' ' + text]
    if block['type'] == 'list_item':
        listing = block.get('list')
        if listing:
            # La numérotation Word exacte reste dans le JSON : pas de faux 1,2,3.
            prefix = '  ' * min(8, listing['level']) + '- '
            if listing.get('format') != 'bullet':
                prefix += '[liste Word : numérotation non reconstruite] '
            return [prefix + text]
        # Le marqueur PDF est imprimé et fait partie du texte brut.
        return [text]
    return [text] if text else ['<!-- Élément sans texte : voir métadonnées JSON. -->']


def render(document):
    lines = ['<!-- T24 : extraction automatique non validée humainement. -->', '']
    if document['status'] in ('partial', 'failed', 'rejected', 'processing'):
        lines += ['> [Conversion incomplète : consulter les erreurs du JSON.]', '']
    current_role = 'body'
    def append_block(b):
        nonlocal current_role
        if not b.get('render', True):
            b['markdown_lines'] = None
            return
        role = b.get('role', 'body')
        if role != current_role:
            current_role = role
            lines.extend(['<!-- DOCX : ' + role + ', sans attribution de page physique -->', ''])
        start = len(lines) + 1
        content = render_block(b)
        lines.extend(content)
        b['markdown_lines'] = [start, len(lines)] if content else None
        lines.append('')
    if document['pages']:
        grouped = {}
        for b in document['blocks']:
            grouped.setdefault(b['page'], []).append(b)
        for page in document['pages']:
            lines.extend([f'<!-- Page physique {page["page"]} -->', ''])
            if page['status'] in ('needs_ocr', 'awaiting_ocr', 'ocr_incomplete'):
                lines.extend(['> [Page incomplète : OCR nécessaire ou en échec, voir JSON.]', ''])
            elif page['status'] == 'apparently_blank':
                lines.extend(['<!-- Page apparemment blanche, non vérifiée humainement. -->', ''])
            structures = {g['source_block_ids'][0]: g for g in page.get('structure', [])}
            members = {bid for g in page.get('structure', []) for bid in g['source_block_ids']}
            originals = {b['block_id']: b for b in grouped.get(page['page'], [])}
            for b in grouped.get(page['page'], []):
                group = structures.get(b['block_id'])
                if group:
                    append_block(group)
                    for bid in group['source_block_ids']:
                        originals[bid]['markdown_lines'] = group['markdown_lines']
                elif b['block_id'] not in members:
                    append_block(b)
    else:
        for b in document['blocks']:
            append_block(b)
    return '\n'.join(lines).rstrip() + '\n'
