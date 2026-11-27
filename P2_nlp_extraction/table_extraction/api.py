"""Public T27 entry point. No PDF opening, OCR imports or embedded path traversal."""
from dataclasses import dataclass
from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .extraction import extract, tables_csv, bpu_csv

ROOT=Path(__file__).resolve().parents[1]


class TableExtractionInputError(ValueError):
    """Invalid, inconsistent or out-of-scope input; no exports created."""


@dataclass(frozen=True)
class TableExtractionLimits:
    max_input_bytes:int=64*1024**2
    max_blocks:int=50000
    max_tables:int=1000
    max_cells:int=200000
    max_output_bytes:int=128*1024**2

    def validate(self):
        if any(type(v) is not int or v<=0 for v in vars(self).values()):
            raise TableExtractionInputError('Les limites doivent être des entiers strictement positifs.')


def _path(path):
    result=Path(path).resolve()
    if not result.is_relative_to(ROOT):
        raise TableExtractionInputError('Les chemins doivent rester dans P2_nlp_extraction.')
    return result


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise TableExtractionInputError('Clé JSON dupliquée.')
        result[key]=value
    return result


def _load(path, limit, schema_name):
    from jsonschema import Draft202012Validator
    with path.open('rb') as stream:data=stream.read(limit+1)
    if len(data)>limit:raise TableExtractionInputError('Fichier JSON trop volumineux.')
    value=json.loads(data.decode('utf-8'),object_pairs_hook=_pairs,
                     parse_constant=lambda v: (_ for _ in ()).throw(ValueError('Nombre JSON non fini.')))
    # Also reject overflowing JSON floats (e.g. 1e999).
    json.dumps(value,allow_nan=False)
    schema=json.loads((ROOT/'config'/schema_name).read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate(value)
    return value,hashlib.sha256(data).hexdigest()


def _check_conversion(document, limits):
    if document['schema_version']!='p2.conversion_document.v1':raise ValueError('Un document T24 est requis.')
    if document['status'] in ('processing','rejected'):raise ValueError('Conversion non finalisée ou rejetée.')
    blocks=document['blocks'];ids=[b['block_id'] for b in blocks]
    if len(blocks)>limits.max_blocks:raise ValueError('Limite de blocs dépassée.')
    if len(ids)!=len(set(ids)):raise ValueError('Identifiants de blocs dupliqués.')
    pages=document['pages']
    if document['source']['detected_type']=='pdf':
        if [b for p in pages for b in p['blocks']]!=blocks:raise ValueError('Blocs PDF et pages divergents.')
        if len({p['page'] for p in pages})!=len(pages):raise ValueError('Pages dupliquées.')
        if any(b['page']!=p['page'] for p in pages for b in p['blocks']):raise ValueError('Page de bloc incohérente.')
    tables=[b for b in blocks if b['type']=='table']
    if len(tables)>limits.max_tables:raise ValueError('Limite de tableaux dépassée.')
    count=0
    for table in tables:
        matrix=table.get('cells')
        if isinstance(matrix,list):count+=sum(len(row) for row in matrix if isinstance(row,list))
    if count>limits.max_cells:raise ValueError('Limite de cellules dépassée.')


def _check_segmentation(segmentation, document, digest):
    source=segmentation['source']
    if (source['conversion_json_sha256']!=digest or source['document_id']!=document['document_id']
            or source['conversion_source']!=document['source'] or segmentation['blocks']!=document['blocks']):
        raise ValueError('La segmentation ne correspond pas exactement au document T24 fourni.')
    ids=[b['block_id'] for b in document['blocks']]
    claimed=[]
    def check(node, parent_ids):
        start,end=node['start_block_index'],node['end_block_index']
        selected=node['source_block_ids']
        if (start>end or end>=len(ids) or ids[start:end+1]!=selected
                or not set(selected)<=set(parent_ids) or not set(node['title_block_ids'])<=set(selected)):
            raise ValueError('Références ou étendue de section incohérentes.')
        expected=list(dict.fromkeys(document['blocks'][i]['page'] for i in range(start,end+1)
                                    if document['blocks'][i]['page'] is not None))
        if node['pages']!=expected:raise ValueError('Pages de section incohérentes.')
        for child in node['children']:check(child,selected)
    for section in segmentation['sections']:
        check(section,ids);claimed.extend(section['source_block_ids'])
    claimed+=segmentation['unassigned_block_ids']
    if len(set(claimed))!=len(claimed) or set(claimed)!=set(ids):raise ValueError('Couverture T26 incohérente.')


def _incomplete(document):
    if document['status'] in ('failed','partial') or document['errors']:return True
    if any(p['status'] in ('failed','partial') or p['errors'] for p in document['pages']):return True
    if document['source']['detected_type']=='pdf':
        pages=document['coverage'].get('processed_pages',[])
        total=document['coverage'].get('source_page_count')
        return not (type(total) is int and total>0 and len(pages)==total
                    and all(type(p) is int for p in pages)
                    and sorted(pages)==list(range(1,len(pages)+1))
                    and sorted(p['page'] for p in document['pages'])==sorted(pages))
    return False


def extract_tables(conversion_json_path, segmentation_json_path=None, output_dir=None, *, limits=None):
    """Extract T24 tables, optionally associate verified T26 boundaries, export four files.

    Only local P2 paths are accepted. Results are unvalidated hypotheses. Every
    call creates a fresh run directory; input files and other packages are untouched.
    """
    from jsonschema import Draft202012Validator, ValidationError
    limits=limits or TableExtractionLimits()
    if not isinstance(limits,TableExtractionLimits):raise TypeError('Utiliser TableExtractionLimits.')
    limits.validate()
    path=_path(conversion_json_path)
    destination=_path(output_dir if output_dir is not None else ROOT/'outputs/table_extraction')
    try:
        document,digest=_load(path,limits.max_input_bytes,'conversion.schema.json')
        _check_conversion(document,limits)
        segmentation=None;segpath=None;segdigest=None
        if segmentation_json_path is not None:
            segpath=_path(segmentation_json_path)
            segmentation,segdigest=_load(segpath,limits.max_input_bytes,'segmentation.schema.json')
            _check_segmentation(segmentation,document,digest)
        tables=extract(document,segmentation,max_cells=limits.max_cells)
        incomplete=_incomplete(document) or bool(segmentation and segmentation['status']=='partial')
        warnings=['table_and_bpu_interpretations_require_human_review']
        if segmentation is None:warnings.append('no_t26_section_context')
        if incomplete:warnings.append('source_conversion_incomplete')
        if not tables:warnings.append('no_structured_table_blocks_available_not_proof_of_absence')
        source=dict(document_id=document['document_id'],conversion_json=path.relative_to(ROOT).as_posix(),
                    conversion_json_sha256=digest,segmentation_json=segpath.relative_to(ROOT).as_posix() if segpath else None,
                    segmentation_json_sha256=segdigest,conversion_source=copy.deepcopy(document['source']),
                    coordinate_system=document['coordinate_system'],conversion_status=document['status'])
        common=dict(status='partial' if incomplete or any(t['status']=='partial' for t in tables) else 'completed_with_review',
                    human_validated=False,source=source,coverage=copy.deepcopy(document['coverage']),warnings=warnings,
                    source_warnings=copy.deepcopy(document['warnings']),source_errors=copy.deepcopy(document['errors']),
                    source_pages=[{k:copy.deepcopy(v) for k,v in p.items() if k!='blocks'} for p in document['pages']],
                    segmentation_warnings=copy.deepcopy(segmentation['warnings']) if segmentation else [],
                    outputs={'tables_json':'tables.json','tables_csv':'tables.csv','bpu_json':'bpu.json','bpu_csv':'bpu.csv'})
        result=dict(schema_version='p2.tables.v1',**common,tables=tables)
        bpu=dict(schema_version='p2.bpu.v1',**copy.deepcopy(common),
                 tables=[copy.deepcopy(t) for t in tables if t['classification'] in ('bpu','bpu_candidate')])
        payloads={}
        for name,data in (('tables',result),('bpu',bpu)):
            schema=json.loads((ROOT/f'config/{name}.schema.json').read_text(encoding='utf-8'))
            Draft202012Validator(schema).validate(data)
            payloads[name+'.json']=(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
        payloads['tables.csv']=tables_csv(tables);payloads['bpu.csv']=bpu_csv(bpu['tables'])
        if sum(map(len,payloads.values()))>limits.max_output_bytes:raise ValueError('Limite totale des exports dépassée.')
    except (ValueError,TypeError,KeyError,RecursionError,ValidationError) as exc:
        raise TableExtractionInputError(str(exc)) from exc
    folder=destination/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')+'_'+uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    for name,data in payloads.items():(folder/name).write_bytes(data)
    return dict(result,run_directory=str(folder),
                output_paths={key:str(folder/name) for key,name in common['outputs'].items()})
