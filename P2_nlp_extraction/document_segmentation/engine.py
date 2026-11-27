"""Boundaries over the canonical T24 block order, retaining every original block."""
import copy
import re

from ..document_conversion.markdown import escape

from .rules import normalize, title_matches, article, masked_fragment, NUMBERED, TOC, VERSION


def _units(document, markdown, warnings):
    blocks = document['blocks']
    lookup = {b['block_id']: i for i, b in enumerate(blocks)}
    groups = {}
    for page in document['pages']:
        for group in page.get('structure', []):
            ids = group['source_block_ids']
            indices = [lookup.get(bid, -1) for bid in ids]
            if (indices[0] < 0 or indices != list(range(indices[0], indices[0]+len(ids)))
                    or group['raw_texts'] != [blocks[i]['raw_text'] for i in indices]
                    or group['text'] != (' '.join(group['raw_texts']) if all(t is not None for t in group['raw_texts']) else None)
                    or any(blocks[i]['page'] != page['page'] for i in indices)
                    or any(i in groups for i in indices)):
                raise ValueError('Groupe T24 incohérent ou non contigu.')
            for i in indices: groups[i] = group
    units, i = [], 0
    while i < len(blocks):
        group = groups.get(i)
        count = len(group['source_block_ids']) if group else 1
        sources = blocks[i:i+count]
        text = ' '.join(b['raw_text'] for b in sources if b['raw_text'] is not None)
        unit = {'start': i, 'end': i+count, 'blocks': sources, 'text': text,
                'page': sources[0]['page'], 'heading': (group or sources[0])['type']=='heading',
                'level': (group or sources[0]).get('heading_level', 2), 'group': group}
        # Markdown is a cue only if its mapped heading agrees with the JSON text.
        lines = (group or sources[0]).get('markdown_lines')
        if markdown is not None and lines and 1 <= lines[0] <= lines[1] <= len(markdown):
            match = re.match(r'^(#{1,6})\s+(.+)$', markdown[lines[0]-1])
            if match:
                if normalize(match[2]) == normalize(text):
                    unit.update(heading=True, level=len(match[1]))
                else: warnings.append('markdown_heading_text_mismatch')
        units.append(unit); i += count
    return units


def _table_fragment(block):
    return masked_fragment(block) or 'ambiguous_table_cell' in block.get('warnings', [])


def _join_title(a, b):
    if a['page'] != b['page'] or a['end'] != b['start']: return False
    if any(x['type'] not in ('heading','paragraph') or _table_fragment(x)
           for x in a['blocks']+b['blocks']): return False
    if a['heading'] and b['heading']: return True
    x, y = a['blocks'][-1].get('bbox'), b['blocks'][0].get('bbox')
    if not x or not y or not (a['text'].isupper() and b['text'].isupper()): return False
    height = min(x[3]-x[1], y[3]-y[1])
    return height > 0 and -.1*height <= y[1]-x[3] <= 1.0*height and abs((x[0]+x[2]-y[0]-y[2])/2) <= height


def segment(document, markdown=None):
    warnings = []
    coverage = document['coverage']
    processed = coverage.get('processed_pages', [])
    total = coverage.get('source_page_count')
    incomplete = (document['status'] in ('partial','failed') or bool(document['errors'])
                  or any(p.get('errors') or p['status'] in ('partial','failed') for p in document['pages']))
    complete_pages = (type(total) is int and total > 0 and len(processed)==total
                      and all(type(p) is int for p in processed)
                      and sorted(processed)==list(range(1,len(processed)+1))
                      and sorted(p['page'] for p in document['pages'])==sorted(processed))
    if document['source']['detected_type']=='pdf' and not complete_pages:
        incomplete = True; warnings.append('only_converted_pages_available')
    if incomplete: warnings.append('source_conversion_incomplete')
    warnings.append('heuristic_segmentation_not_human_validated')
    units = _units(document, markdown, warnings)
    # Legacy T24 OCR can have a two-line heading without a structure group.
    combined, i = [], 0
    while i < len(units):
        a = units[i]
        if i+1 < len(units):
            b=units[i+1]; joined=a['text']+' '+b['text']
            if not title_matches(a['text'])[0] and len(joined)<=220 and title_matches(joined)[0] and _join_title(a,b):
                a=dict(a, end=b['end'], blocks=a['blocks']+b['blocks'], text=joined,
                       heading=a['heading'] and b['heading'], joined_title=True)
                i+=1
        combined.append(a);i+=1
    sections, candidates, unassigned, stack = [], [], [], []
    root=None; toc_page=object();toc=False
    node_count=0;decorations={}

    def candidate(u, categories, reason):
        candidates.append({'text':u['text'],'category_candidates':categories,
                           'source_block_ids':[b['block_id'] for b in u['blocks']],
                           'page':u['page'],'reason':reason,'needs_review':True,
                           'confidence':{'score':.4,'basis':reason,'calibrated':False}})

    def node(u, kind, level, category=None, number=None, basis='structural_heading'):
        nonlocal node_count
        node_count+=1
        result={'section_id':f's{node_count:06d}','kind':kind,'category':category,
                'title_raw':u['text'],'title_block_ids':[b['block_id'] for b in u['blocks']],
                'level':level,'number':number,'source_block_ids':[],'pages':[],'children':[],
                'confidence':{'score':.95 if u['heading'] else .8,'basis':basis,'calibrated':False},
                'human_validated':False,'needs_review':True,'warnings':[],
                'start_block_index':u['start'],'end_block_index':u['end']-1,
                'extent_complete':not incomplete}
        if incomplete: result['warnings'].append('section_extent_limited_by_source_coverage')
        if any(b.get('method')=='ocr' for b in u['blocks']):result['warnings'].append('ocr_title_unvalidated')
        if any(b.get('language')=='ar' for b in u['blocks']):result['warnings'].append('arabic_title_alias_requires_review')
        decorations[u['start']]={'node_id':result['section_id'],'level':level,'text':u['text'],
                                  'end':u['end'],'category':category}
        return result

    for u in combined:
        if toc and u['page']!=toc_page: toc=False
        structural = not any(_table_fragment(b) for b in u['blocks'])
        if structural and normalize(u['text']) in TOC:
            toc=True;toc_page=u['page']
        categories, acronym=title_matches(u['text']) if structural else ([], False)
        header=any(b.get('role','body')!='body' for b in u['blocks'])
        table=not structural or any(b['type'] in ('table','image','unresolved') for b in u['blocks'])
        dotted=bool(re.search(r'\.{2,}\s*\d+\s*$',u['text']))
        chosen=False
        if categories:
            reason=None
            if toc or dotted: reason='table_of_contents_reference'
            elif header: reason='header_or_footer_reference'
            elif table: reason='non_heading_block_type'
            elif len(categories)!=1: reason='multiple_possible_categories'
            elif acronym and not u['heading']: reason='acronym_without_heading_evidence'
            elif len(u['text'])>220: reason='title_too_long'
            if reason: candidate(u,categories,reason)
            elif root and root['category']==categories[0]:
                root['warnings'].append('repeated_section_title_kept_as_continuation')
                candidate(u,categories,'repeated_title_or_distinct_same_category_document')
            else:
                root=node(u,'section',1,category=categories[0],basis='exact_title_with_structure' if u['heading'] else 'standalone_full_title')
                sections.append(root);stack=[];chosen=True
        if not chosen and not categories and root and not toc and not header and not table:
            art=article(u['text'],u['heading'])
            if art and art['reliable']:
                while stack and stack[-1]['kind']=='article':stack.pop()
                parent=stack[-1] if stack else root
                child=node(u,'article',min(6,parent['level']+1),number=art['number'],basis='article_marker')
                parent['children'].append(child);stack.append(child)
            elif art:
                candidate(u,[],'article_marker_in_possible_prose')
            elif u['heading'] or NUMBERED.match(u['text']):
                match=NUMBERED.match(u['text'])
                level=min(6,max(2,len(match[1].split('.'))+1 if match else u['level']))
                while stack and (stack[-1]['kind']=='article' or stack[-1]['level']>=level):stack.pop()
                parent=stack[-1] if stack else root
                child=node(u,'subsection',level,number=match[1] if match else None)
                parent['children'].append(child);stack.append(child)
        ids=[b['block_id'] for b in u['blocks']]
        if root:
            for item in [root]+stack:
                item['source_block_ids'].extend(ids);item['end_block_index']=u['end']-1
                if u['page'] is not None and u['page'] not in item['pages']:item['pages'].append(u['page'])
        else: unassigned.extend(ids)
    if not sections:warnings.append('no_dce_section_confidently_identified')
    if candidates:warnings.append('ambiguous_titles_require_review')
    return {'schema_version':'p2.segmentation.v1','status':'partial' if incomplete else 'completed_with_review',
            'human_validated':False,'rule_version':VERSION,'source_status':document['status'],
            'sections':sections,'candidates':candidates,'unassigned_block_ids':unassigned,
            'blocks':copy.deepcopy(document['blocks']),
            'pages':[dict({k:copy.deepcopy(v) for k,v in p.items() if k != 'blocks'},
                          source_block_ids=[b['block_id'] for b in p['blocks']]) for p in document['pages']],
            'coverage':copy.deepcopy(coverage),'warnings':list(dict.fromkeys(warnings)),
            'source_errors':copy.deepcopy(document['errors']),
            'source_warnings':copy.deepcopy(document['warnings'])}, decorations, combined


def render(result, decorations, units):
    lines=['<!-- T26 : segmentation heuristique, non validée humainement. -->','']
    if result['status']=='partial':lines+=['> Source partielle : limites des sections non garanties.','']
    if result['candidates']:lines+=['> Titres ambigus : consulter les candidats dans sections.json.','']
    current_page=object()
    for unit in units:
        if unit['page']!=current_page:
            current_page=unit['page']
            if current_page is not None:lines += [f'<!-- Page physique {current_page} -->','']
        decoration=decorations.get(unit['start'])
        if decoration:
            lines += [f'<!-- {decoration["node_id"]} ; catégorie={decoration["category"] or "interne"} -->',
                      '#'*decoration['level']+' '+escape(decoration['text']).replace('\n',' '),'']
            continue
        for block in unit['blocks']:
            if masked_fragment(block):
                continue
            if block['type']=='table':
                cells=block.get('cells',[])
                if block.get('structure_preserved') and cells and cells[0]:
                    row=lambda r:'| '+' | '.join(escape(c).replace('\n','<br>') for c in r)+' |'
                    lines += [row(cells[0]),'| '+' | '.join('---' for _ in cells[0])+' |']+[row(r) for r in cells[1:]]+['']
                else:lines+=['> Tableau : structure non restituée ; données sources dans le JSON.','']
            elif block['raw_text'] is None:
                lines+=['> Bloc sans texte reconnu : voir hypothèses et provenance JSON.','']
            else:
                # Masked originals remain in JSON, including their provenance.
                lines += [escape(block['raw_text']).replace('\n','  \n'),'']
    return '\n'.join(lines).rstrip()+'\n'
