"""Public API. Reads explicit local T24 files; never follows paths in their JSON."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .engine import segment, render

ROOT=Path(__file__).resolve().parents[1]


class SegmentationInputError(ValueError):
    pass


@dataclass(frozen=True)
class SegmentationLimits:
    max_input_bytes:int=64*1024**2
    max_blocks:int=50000
    max_output_bytes:int=64*1024**2

    def validate(self):
        if any(type(v) is not int or v<=0 for v in vars(self).values()):
            raise ValueError('Les limites doivent être des entiers strictement positifs.')


def _path(path):
    result=Path(path).resolve()
    if not result.is_relative_to(ROOT):
        raise SegmentationInputError('Les chemins doivent rester dans P2_nlp_extraction.')
    return result


def _read(path, limit):
    with path.open('rb') as stream: data=stream.read(limit+1)
    if len(data)>limit: raise SegmentationInputError('Fichier trop volumineux.')
    return data


def _pairs(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise SegmentationInputError('Clé JSON dupliquée.')
        value[key]=item
    return value


def segment_document(document_json, output_dir=None, *, markdown_path=None, limits=None):
    """Segment a T24 document JSON, optionally checking its explicit Markdown.

    Returns sections plus runtime absolute export paths. All output is local to
    P2, in a fresh folder. No PDF is read, no model loaded, no section invented
    for unassigned blocks. Scores are heuristic, never accuracy probabilities.
    """
    from jsonschema import Draft202012Validator, ValidationError
    limits=limits or SegmentationLimits()
    if not isinstance(limits,SegmentationLimits):raise TypeError('Utiliser SegmentationLimits.')
    limits.validate()
    path=_path(document_json);data=_read(path,limits.max_input_bytes)
    try:
        document=json.loads(data.decode('utf-8'),object_pairs_hook=_pairs,
                            parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))
        schema=json.loads((ROOT/'config/conversion.schema.json').read_text(encoding='utf-8'))
        Draft202012Validator(schema).validate(document)
        if document['schema_version']!='p2.conversion_document.v1':raise ValueError('Un document T24 est requis, pas un manifeste.')
        if document['status'] in ('processing','rejected'):raise ValueError('Conversion non finalisée ou rejetée.')
        blocks=document['blocks'];ids=[b['block_id'] for b in blocks]
        if len(blocks)>limits.max_blocks:raise ValueError('Limite de blocs dépassée.')
        if len(set(ids))!=len(ids):raise ValueError('Identifiants de blocs dupliqués.')
        if document['source']['detected_type']=='pdf' and blocks and not document['pages']:
            raise ValueError('Blocs PDF sans pages sources.')
        if document['pages']:
            page_numbers=[p['page'] for p in document['pages']]
            if len(set(page_numbers))!=len(page_numbers):raise ValueError('Pages dupliquées.')
            flattened=[b for p in document['pages'] for b in p['blocks']]
            if flattened!=blocks:raise ValueError('Blocs canoniques et pages divergents.')
            if any(b['page']!=p['page'] for p in document['pages'] for b in p['blocks']):raise ValueError('Page de bloc incohérente.')
        md_path=_path(markdown_path if markdown_path is not None else path.with_name('document.md'))
        md_bytes=_read(md_path,limits.max_input_bytes) if md_path.exists() else None
        if markdown_path is not None and md_bytes is None:raise ValueError('Markdown explicite absent.')
        result,decorations,units=segment(document,md_bytes.decode('utf-8').splitlines() if md_bytes is not None else None)
    except (ValueError,KeyError,TypeError,RecursionError,ValidationError) as exc:
        raise SegmentationInputError(str(exc)) from exc
    result['source']={'document_id':document['document_id'],'conversion_json':path.relative_to(ROOT).as_posix(),
                      'conversion_json_sha256':hashlib.sha256(data).hexdigest(),
                      'markdown':md_path.relative_to(ROOT).as_posix() if md_bytes is not None else None,
                      'markdown_sha256':hashlib.sha256(md_bytes).hexdigest() if md_bytes is not None else None,
                      'conversion_source':document['source'],'coordinate_system':document['coordinate_system']}
    if md_bytes is None: result['warnings'].append('markdown_not_available_json_used')
    result['outputs']={'json':'sections.json','markdown':'sections.md'}
    output_schema=json.loads((ROOT/'config/segmentation.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(output_schema).validate(result)
    encoded=(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    markdown=render(result,decorations,units).encode('utf-8')
    if max(len(encoded),len(markdown))>limits.max_output_bytes:raise SegmentationInputError('Export trop volumineux.')
    base=_path(output_dir if output_dir is not None else ROOT/'outputs/segmentation')
    folder=base/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')+'_'+uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'sections.json').write_bytes(encoded);(folder/'sections.md').write_bytes(markdown)
    return {**result,'run_directory':str(folder),'sections_json_path':str(folder/'sections.json'),
            'markdown_path':str(folder/'sections.md')}
