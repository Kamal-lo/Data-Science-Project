"""T28: evaluate saved outputs only, with explicit gates and provenance."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
from uuid import uuid4

from .cer import character_errors, word_errors
from .references import references, hypothesis, approved, scope_hash
from .segmentation import compare_sections, compare_hierarchy

ROOT=Path(__file__).resolve().parents[1]


class EvaluationInputError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationLimits:
    max_input_bytes:int=64*1024**2
    max_alignment_cells:int=8000000
    max_sections:int=1000
    max_output_bytes:int=64*1024**2


def _path(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise EvaluationInputError('Les chemins doivent rester dans P2.')
    return path


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise EvaluationInputError('Clé JSON dupliquée.')
        result[key]=value
    return result


def _read(path,limit):
    with _path(path).open('rb') as stream:data=stream.read(limit+1)
    if len(data)>limit:raise EvaluationInputError('Entrée trop volumineuse.')
    return data


def _load(path,limits):
    data=_read(path,limits.max_input_bytes)
    value=json.loads(data.decode('utf-8'),object_pairs_hook=_pairs,
                     parse_constant=lambda v: (_ for _ in ()).throw(ValueError('Nombre non fini.')))
    json.dumps(value,allow_nan=False)
    return value,dict(path=_path(path).relative_to(ROOT).as_posix(),sha256=hashlib.sha256(data).hexdigest())


def _validate(value,name):
    from jsonschema import Draft202012Validator
    schema=json.loads((ROOT/'config'/name).read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate(value)


def _ocr(document, manifest, origins, dataset_kind, normalization, limits):
    records=references(manifest,lambda p:_read(ROOT/p,limits.max_input_bytes),dataset_kind) if manifest else []
    if document:
        if document.get('schema_version')!='p2.automatic_ocr.v1':raise ValueError('Sortie ocr_pipeline enregistrée requise.')
        numbers=[p['page'] for p in document['pages']]
        if len(numbers)!=len(set(numbers)):raise ValueError('Pages OCR dupliquées.')
        for page in numbers:
            for language in ('fr','ar'):
                if not any(r['page']==page and r['language']==language for r in records):
                    records.append(dict(page=page,language=language,reference_text=None,reference_source=None,
                                        reference_sha256=None,approval={},scope_sha256=None,
                                        blockers=['reference_absent']))
    results=[]
    keys=[(r['page'],r['language']) for r in records]
    if len(keys)!=len(set(keys)):raise ValueError('Références page/langue dupliquées.')
    for record in records:
        if record['language'] not in ('fr','ar'):raise ValueError('Langue non prise en charge.')
        warnings=list(record['blockers']);text=None;blocks=[];metrics=None
        if document and record['reference_text'] is not None and not record['blockers']:
            text,blocks,problems=hypothesis(document,record);warnings.extend(problems)
        elif not document:warnings.append('ocr_output_absent')
        if not warnings:
            if not record['reference_text']:warnings.append('empty_reference_undefined_cer')
            else:
                try:metrics=character_errors(record['reference_text'],text,normalization=normalization,
                                              max_alignment_cells=limits.max_alignment_cells)
                except ValueError as exc:warnings.append(str(exc))
                if metrics is not None:
                    metrics['word_metrics'] = word_errors(record['reference_text'], text,
                        normalization=normalization, max_alignment_cells=limits.max_alignment_cells)
                    if metrics['word_metrics'] is None:
                        warnings.append('empty_reference_words_undefined_wer')
        validation=dict(human_validated=approved(record['approval']) and not record['blockers'],
                        synthetic_oracle=dataset_kind=='synthetic' and bool(manifest and manifest.get('dataset_kind')=='synthetic'),
                        approval=record['approval'])
        results.append(dict(document_id=document.get('pdf_sha256') if document else record.get('document_sha256'),
                            page=record['page'],language=record['language'],dataset_kind=dataset_kind,
                            status='evaluated' if metrics is not None else 'not_evaluated',metrics=metrics,
                            reference_source=record['reference_source'],reference_sha256=record['reference_sha256'],
                            reference_validation=validation,scope_sha256=record['scope_sha256'],
                            reference_text_original=record['reference_text'],hypothesis_text_original=text,
                            source_block_ids=blocks,warnings=list(dict.fromkeys(warnings))))
    aggregates={}
    for language in ('fr','ar'):
        items=[r for r in results if r['language']==language];valid=[r['metrics'] for r in items if r['metrics'] is not None]
        totals=None
        if valid:
            totals={key:sum(m[key] for m in valid) for key in ('substitutions','insertions','deletions','total_errors','reference_characters','hypothesis_characters')}
            totals.update(cer=totals['total_errors']/totals['reference_characters'],
                          cer_percent=100*totals['total_errors']/totals['reference_characters'])
            words = [m['word_metrics'] for m in valid if m['word_metrics'] is not None]
            totals['word_metrics'] = None
            if words:
                word_totals = {key: sum(m[key] for m in words) for key in (
                    'substitutions', 'insertions', 'deletions', 'total_errors',
                    'reference_words', 'hypothesis_words')}
                wer = word_totals['total_errors'] / word_totals['reference_words']
                totals['word_metrics'] = dict(word_totals, wer=wer, wer_percent=100 * wer)
        aggregates[language]=dict(status='not_evaluated' if not valid else 'partial' if len(valid)!=len(items) else 'evaluated',
                                  evaluated_pages=sum(r['metrics'] is not None for r in items),requested_pages=len(items),metrics=totals,
                                  warnings=['no_validated_comparable_reference'] if not valid else [])
    return dict(schema_version='p2.ocr_metrics.v1',dataset_kind=dataset_kind,normalization=normalization,
                character_unit='Unicode code point',block_join='literal LF in recorded block order',
                sources=origins,records=results,aggregates=aggregates,
                warnings=['synthetic_scores_do_not_measure_real_accuracy'] if dataset_kind=='synthetic' else [],
                limits=['No Arabic diacritic/tatweel/alef/ya folding; no whitespace, case or accent removal.',
                        'WER splits on Unicode whitespace and retains punctuation, case and diacritics.',
                        'CER and WER do not measure semantic accuracy.'])


def _sections(document,annotations,origins,dataset_kind,limits):
    result=dict(schema_version='p2.segmentation_metrics.v1',dataset_kind=dataset_kind,status='not_evaluated',
                sources=origins,document_id=None,language='mixed_or_unspecified',reference_validation=None,
                metrics=None,predicted_sections=[],reference_sections=[],scope=None,warnings=[],
                limits=['Exact intervals in T24 block identifiers; hierarchy scoring requires explicit annotations.',
                        'No fuzzy matching; incomplete inputs are scored only in an explicitly annotated scope.'])
    if not document:result['warnings'].append('segmentation_output_absent');return result
    _validate(document,'segmentation.schema.json')
    result['document_id']=document['source']['document_id']
    if document['status']=='partial':result['warnings'].append('partial_document_no_full_dce_claim')
    ids=[b['block_id'] for b in document['blocks']]
    if len(ids)!=len(set(ids)):raise ValueError('Identifiants T26 dupliqués.')
    if len(document['sections'])>limits.max_sections:raise ValueError('Trop de sections prédites.')
    predicted=[]
    occupied=set();section_ids=set()
    for section in document['sections']:
        selected=section['source_block_ids'];start=section['start_block_index'];end=section['end_block_index']
        if (not selected or start>end or end>=len(ids) or ids[start:end+1]!=selected
                or occupied.intersection(selected) or section['section_id'] in section_ids):
            raise ValueError('Étendue T26 incohérente ou sections racines dupliquées.')
        occupied.update(selected);section_ids.add(section['section_id'])
        predicted.append(dict(section_id=section['section_id'],category=section['category'],
                              start_block_id=selected[0],end_block_id=selected[-1],pages=section['pages']))
    result['predicted_sections']=predicted
    if annotations is None:result['warnings'].append('human_section_annotations_absent');return result
    _validate(annotations,'section_annotations.schema.json')
    validation=annotations['approval'];scope=annotations['scope'];refs=annotations['sections']
    result.update(reference_validation=validation,scope=scope,reference_sections=refs)
    synthetic=dataset_kind=='synthetic' and annotations['dataset_kind']=='synthetic'
    if annotations['dataset_kind']!=dataset_kind:result['warnings'].append('reference_dataset_kind_mismatch');return result
    if not synthetic and not approved(validation):result['warnings'].append('section_annotations_not_human_validated');return result
    if validation.get('scope_sha256')!=scope_hash(scope) or validation.get('reference_sha256')!=scope_hash(refs):
        result['warnings'].append('annotation_integrity_mismatch');return result
    if annotations['conversion_json_sha256']!=document['source']['conversion_json_sha256']:
        result['warnings'].append('annotation_document_mismatch');return result
    if len(refs)>limits.max_sections:raise ValueError('Trop de sections de référence.')
    selected=scope['block_ids']
    if not scope['exhaustive'] or not selected or not set(selected)<=set(ids):
        result['warnings'].append('annotation_scope_incomplete_or_unavailable');return result
    positions={bid:i for i,bid in enumerate(ids)}
    indices=[positions[b] for b in selected]
    if indices!=list(range(indices[0],indices[-1]+1)):
        result['warnings'].append('annotation_scope_not_contiguous');return result
    selected_set=set(selected)
    if any(selected_set.intersection(page['source_block_ids'])
           and page.get('status') in ('processing', 'awaiting_ocr', 'needs_ocr', 'ocr_incomplete', 'error', 'failed')
           for page in document.get('pages', [])):
        result['warnings'].append('annotation_scope_contains_nonfinal_page');return result
    for ref in refs:
        if ref['start_block_id'] not in selected_set or ref['end_block_id'] not in selected_set:
            result['warnings'].append('reference_outside_annotated_scope');return result
        if positions[ref['start_block_id']]>positions[ref['end_block_id']]:raise ValueError('Frontières de référence inversées.')
    ref_spans=[(r['start_block_id'],r['end_block_id']) for r in refs]
    if len(ref_spans)!=len(set(ref_spans)):raise ValueError('Annotations de sections dupliquées.')
    spans=sorted((positions[a],positions[b]) for a,b in ref_spans)
    if any(a2<=b1 for (a1,b1),(a2,b2) in zip(spans,spans[1:])):raise ValueError('Sections racines de référence chevauchantes.')
    included=[]
    for prediction,section in zip(predicted,document['sections']):
        source=set(section['source_block_ids'])
        if source&selected_set and not source<=selected_set:
            result['warnings'].append('predicted_section_crosses_annotation_scope');return result
        if source<=selected_set:included.append(prediction)
    result['metrics']=compare_sections(included,refs);result['status']='evaluated'
    if 'hierarchy' in scope:
        result['hierarchy_metrics'] = compare_hierarchy(document['sections'], scope['hierarchy'],
                                                        positions, selected_set, limits.max_sections)
    result['warnings'].append('evaluation_limited_to_explicit_annotated_scope')
    if synthetic:result['warnings'].append('synthetic_scores_do_not_measure_real_accuracy')
    return result


def evaluate_quality(ocr_json_path=None,reference_manifest_path=None,segmentation_json_path=None,
                     section_annotations_path=None,output_dir=None,*,dataset_kind='real',normalization='none',limits=None):
    """Evaluate cached OCR/T26 with verified reference artifacts; never run OCR.

    Return two report objects plus paths to fresh JSON/Markdown exports under P2.
    OCR references: existing French manifest or p2.ocr_references.v1. Synthetic
    oracles must explicitly declare dataset_kind=synthetic; they are never real scores.
    """
    from jsonschema import ValidationError
    limits=limits or EvaluationLimits()
    if not isinstance(limits,EvaluationLimits):raise TypeError('Utiliser EvaluationLimits.')
    if any(type(v) is not int or v<=0 for v in vars(limits).values()):raise EvaluationInputError('Limites invalides.')
    if dataset_kind not in ('real','synthetic') or normalization not in ('none','NFC'):raise EvaluationInputError('Options invalides.')
    destination=_path(output_dir if output_dir is not None else ROOT/'outputs/quality_evaluation')
    try:
        loaded=[];origins={}
        for key,path in zip(('ocr','references','segmentation','section_annotations'),
                            (ocr_json_path,reference_manifest_path,segmentation_json_path,section_annotations_path)):
            if path is None:loaded.append(None)
            else:
                data,origin=_load(path,limits);loaded.append(data);origins[key]=origin
        ocr,manifest,segmentation,annotations=loaded
        if manifest and manifest.get('dataset_kind','real')!=dataset_kind:raise ValueError('Type de corpus incohérent.')
        if manifest and manifest.get('schema_version')=='p2.ocr_references.v1':_validate(manifest,'ocr_references.schema.json')
        ocr_result=_ocr(ocr,manifest,origins,dataset_kind,normalization,limits)
        section_result=_sections(segmentation,annotations,origins,dataset_kind,limits)
        _validate(ocr_result,'ocr_metrics.schema.json');_validate(section_result,'segmentation_metrics.schema.json')
        payloads={name:json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n' for name,value in
                  (('ocr_metrics.json',ocr_result),('segmentation_metrics.json',section_result))}
        payloads['evaluation_report.md']=render(ocr_result,section_result)
        if sum(len(v.encode('utf-8')) for v in payloads.values())>limits.max_output_bytes:raise ValueError('Exports trop volumineux.')
    except (ValueError,KeyError,TypeError,RecursionError,ValidationError) as exc:raise EvaluationInputError(str(exc)) from exc
    folder=destination/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')+'_'+uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    for name,text in payloads.items():(folder/name).write_bytes(text.encode('utf-8'))
    return dict(ocr_metrics=ocr_result,segmentation_metrics=section_result,run_directory=str(folder),
                output_paths={name:str(folder/name) for name in payloads})


def render(ocr,sections):
    escape=lambda x:html.escape(str(x)).replace('|','\\|').replace('\n',' ')
    lines=['# T28 — Évaluation qualité','',f"Corpus : {ocr['dataset_kind']}. Normalisation : {ocr['normalization']}.",
           'Les textes et périmètres originaux sont conservés dans les JSON.','',
           '| Page | Langue | Statut | CER | WER | S / I / D (caractères) | Avertissements |',
           '|---|---|---|---:|---:|---|---|']
    for row in ocr['records']:
        metric=row['metrics']
        value=f"{metric['cer_percent']:.4f} %" if metric else 'Non évalué'
        words = metric.get('word_metrics') if metric else None
        wer = f"{words['wer_percent']:.4f} %" if words else 'Non évalué'
        counts=f"{metric['substitutions']} / {metric['insertions']} / {metric['deletions']}" if metric else '—'
        lines.append(f"| {row['page']} | {row['language']} | {row['status']} | {value} | {wer} | {counts} | {escape(', '.join(row['warnings']))} |")
    lines+=['','Globaux pondérés par les caractères (CER) et les mots (WER) de référence :','']
    for lang,item in ocr['aggregates'].items():
        metric=item['metrics']
        value=f"{metric['cer_percent']:.4f} % ({metric['total_errors']}/{metric['reference_characters']})" if metric else 'Non évalué'
        words = metric.get('word_metrics') if metric else None
        wer = f"{words['wer_percent']:.4f} % ({words['total_errors']}/{words['reference_words']})" if words else 'Non évalué'
        lines.append(f'- {lang} · CER {value} · WER {wer} · {item["evaluated_pages"]}/{item["requested_pages"]} pages évaluées.')
    lines+=['','## Découpage des sections','',f"Statut : {sections['status']}.",
            'Les métriques portent sur les sections racines et le périmètre annoté explicitement.']
    if sections['metrics']:
        for key,value in sections['metrics']['labeled_exact'].items():lines.append(f'- {key} : {value}.')
    else:lines.append('Précision, rappel, F1, catégories et frontières : **non évalués**.')
    lines+=['','Avertissements : '+escape(', '.join(sections['warnings'])),
            '', '## Sources et limites','']
    for key,value in ocr['sources'].items():lines.append(f'- {key} : {escape(value["path"])} ; SHA-256 `{value["sha256"]}`.')
    lines += ['']+['- '+escape(v) for v in ocr['limits']+sections['limits']]
    lines+=['','Les scores synthétiques ne mesurent pas la précision sur un DCE réel.',
             'Un enregistrement d’approbation vérifiable est une trace locale, pas une signature cryptographique du relecteur.','']
    return '\n'.join(lines)
