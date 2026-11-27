"""Local P2 validation against the transferred DCE and recorded OCR."""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import psutil
import pymupdf
from jsonschema import Draft202012Validator

from P2_nlp_extraction.document_conversion import ConversionOptions
from P2_nlp_extraction.ocr_pipeline import extract_pdf
from P2_nlp_extraction.pipeline import load_delivery, load_job, run_pipeline
from P2_nlp_extraction.quality_evaluation import evaluate_quality
from P2_nlp_extraction.quality_evaluation.references import FINAL_OCR_PAGE_STATES, scope_hash
from P2_nlp_extraction.scripts.ocr_common import ROOT, sha256
from P2_nlp_extraction.storage import resolve_document, resolve_export
from P2_nlp_extraction.table_extraction import extract_tables

PDF = ROOT / 'data/pdf/test_dce.pdf'
REFERENCES = ROOT / 'data/ground_truth/pages_1_2/manifest.json'
RECORDED = ROOT / 'outputs/ocr/automatic_sample/20261118T221046_740048Z_de048b93/document.json'
OUTPUT = ROOT / 'outputs/audit'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def reference_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Le fichier de référence doit rester dans P2.')
    return path


def write_new_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def draft_references(folder, pages, language, ocr_path=None, sections_path=None):
    """Create editable inputs with blank reference text and no approval."""
    ocr = read_json(reference_path(ocr_path)) if ocr_path else None
    sections = read_json(reference_path(sections_path)) if sections_path else None
    if not (ocr or sections):
        raise ValueError('Fournir une sortie OCR ou T26.')
    records = []
    if ocr:
        selected = [p for p in ocr['pages'] if p['page'] in pages and
                    p['status'] in FINAL_OCR_PAGE_STATES and not p['errors']]
        if len(selected) != len(set(pages)):
            raise ValueError('Une page demandée est absente ou non finalisée dans ce lot OCR.')
        for page in selected:
            width, height = page['image_size']
            scope = dict(image_size=[width, height], dpi=page['dpi'],
                         regions=[dict(name='zone à relire', bbox=[0, 0, width, height])])
            text_name = f"page-{page['page']}-{language}.txt"
            records.append(dict(page=page['page'], language=language, scope=scope,
                                approval=dict(reference_file=text_name)))
    folder = reference_path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    if ocr:
        for record in records:
            name = record['approval']['reference_file']
            path = folder / name
            path.touch(exist_ok=False)
            record['approval']['reference_file'] = path.relative_to(ROOT).as_posix()
        write_new_json(folder / 'ocr-draft.json', dict(schema_version='p2.ocr_references.v1',
                       dataset_kind='real', document_sha256=ocr['pdf_sha256'], records=records))
    if sections:
        write_new_json(folder / 'sections-draft.json', dict(schema_version='p2.section_annotations.v1',
                       dataset_kind='real', conversion_json_sha256=sections['source']['conversion_json_sha256'],
                       scope=dict(block_ids=[b['block_id'] for b in sections['blocks']],
                                  exhaustive=False), sections=[]))
    return folder


def approve_reference(draft_path, reviewer):
    """Seal an explicitly reviewed draft. Evaluation still verifies its scope."""
    draft_path = reference_path(draft_path)
    draft = read_json(draft_path)
    reviewer = reviewer.strip()
    if not reviewer or draft.get('dataset_kind') != 'real':
        raise ValueError('Indiquer le nom du relecteur pour cette référence réelle.')
    approval = dict(human_reviewed=True, scope_confirmed=True, reviewer=reviewer,
                    approved_at=datetime.now(timezone.utc).isoformat())
    if draft.get('schema_version') == 'p2.ocr_references.v1' and draft['records']:
        schema = 'ocr_references'
        for record in draft['records']:
            transcript = reference_path(ROOT / record['approval']['reference_file'])
            if not transcript.read_text(encoding='utf-8').strip():
                raise ValueError(f'Transcription vide pour la page {record["page"]}.')
            record['approval'].update(approval, reference_sha256=sha256(transcript),
                                      scope_sha256=scope_hash(record['scope']))
    elif draft.get('schema_version') == 'p2.section_annotations.v1':
        schema = 'section_annotations'
        if not draft['scope']['exhaustive'] or not draft['scope']['block_ids'] or not draft['sections']:
            raise ValueError('Définir le périmètre exhaustif et renseigner les sections.')
        draft['approval'] = dict(approval, reference_sha256=scope_hash(draft['sections']),
                                 scope_sha256=scope_hash(draft['scope']))
    else:
        raise ValueError('Brouillon de référence inconnu ou vide.')
    Draft202012Validator(read_json(ROOT / 'config' / f'{schema}.schema.json')).validate(draft)
    approved_path = draft_path.with_name(draft_path.stem + '-approved.json')
    write_new_json(approved_path, draft)
    return approved_path


def validate_exports(job):
    assert load_job(job['job_path']) == job
    assert sha256(resolve_document(job['source'])) == sha256(PDF)
    schemas = {
        'document_json': 'conversion',
        'sections_json': 'segmentation',
        'tables_json': 'tables',
        'bpu_json': 'bpu',
        'ocr_metrics.json': 'ocr_metrics',
        'segmentation_metrics.json': 'segmentation_metrics',
    }
    validated = set()
    for document in job['documents']:
        for exports in [document['outputs'], *(record['outputs'] for record in document['quality'])]:
            for name, info in exports.items():
                path = ROOT / info['path']
                assert path.stat().st_size == info['size_bytes'] and sha256(path) == info['sha256'], name
                if name in schemas:
                    schema = read_json(ROOT / 'config' / (schemas[name] + '.schema.json'))
                    Draft202012Validator(schema).validate(read_json(path))
                    validated.add(name)
                elif path.suffix in {'.md', '.csv'}:
                    path.read_text(encoding='utf-8')
    return sorted(validated)


def check_pipeline(reuse, pages, cache_paths):
    options = ConversionOptions(
        ocr_mode='reuse_only' if reuse else 'never',
        pdf_pages=tuple(pages) if reuse else None,
        ocr_results=tuple(map(str, cache_paths)) if reuse else (),
    )
    job = run_pipeline(
        PDF, OUTPUT / ('recorded' if reuse else 'native'), options=options,
        reference_manifest_path=REFERENCES if reuse else None,
    )
    report = {
        'job': job['job_path'], 'status': job['status'], 'steps': job['steps'],
        'errors': job['errors'], 'schemas': validate_exports(job), 'documents': [],
    }
    for document in job['documents']:
        details = {'status': document['status'], 'outputs': document['outputs']}
        if details['outputs']:
            source = read_json(ROOT / details['outputs']['document_json']['path'])
            details['coverage'] = source.get('coverage')
            details['blocks'] = dict(Counter(block['type'] for block in source['blocks']))
            details['page_statuses'] = dict(Counter(p.get('status') for p in source['pages']))
        report['documents'].append(details)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def replay_complete(page_count):
    """Replay finalized page batches with the original PDF and checked provenance."""
    signature = sha256(PDF)
    sources = {}
    selected = {}
    for path in sorted((OUTPUT / 'ocr').glob('*/document.json')):
        raw = read_json(path)
        if raw['pdf_sha256'] != signature:
            continue
        sources[path] = raw
        for page in raw['pages']:
            if page['status'] in ('ok', 'needs_review', 'near_blank') and not page['errors']:
                selected[page['page']] = path
    pages = list(range(1, page_count + 1))
    missing = sorted(set(pages) - selected.keys())
    if missing:
        raise RuntimeError(f'Pages sans OCR finalisé : {missing}')

    cache_paths = []
    for source in sorted(set(selected.values())):
        raw = sources[source]
        records = [page for page in raw['pages'] if selected.get(page['page']) == source]
        if len(records) == len(raw['pages']):
            cache_paths.append(source)
            continue
        # Preserve the original and use only the pages retained from this attempt.
        subset = OUTPUT / f'ocr-replay-{raw["run_id"]}.json'
        subset.write_text(json.dumps({
            **raw, 'pages': records, 'selected_pages': [page['page'] for page in records],
            'status': 'completed_with_review', 'errors': [],
            'audit_subset_of': source.relative_to(ROOT).as_posix(),
            'audit_subset_source_sha256': sha256(source),
        }, ensure_ascii=False), encoding='utf-8')
        cache_paths.append(subset)
    check_pipeline(True, pages, cache_paths)


def check_ocr(pages, max_side, fallback, page_timeout):
    from P2_nlp_extraction.ocr_pipeline.models import preflight
    preflight()
    ram = psutil.virtual_memory()
    if ram.available < 2 * 1024**3:
        raise RuntimeError('Moins de 2 Gio de RAM disponible avant l’essai.')
    result = extract_pdf(
        PDF, OUTPUT / 'ocr', pages=pages, dpi=200, detector_max_side=max_side,
        fallback_mode=fallback, timeout_seconds=(page_timeout + 30) * len(pages) + 60,
        page_timeout_seconds=page_timeout,
        initialization_timeout_seconds=60,
    )
    evaluation = evaluate_quality(result['exports']['json'], REFERENCES, output_dir=OUTPUT / 'quality')
    print(json.dumps({
        'status': result['status'], 'pdf_pages': pages, 'run': result['run_directory'],
        'available_ram_mib_before': round(ram.available / 1024**2), 'detection_max_side': max_side,
        'fallback_mode': fallback, 'page_timeout_seconds': page_timeout,
        'seconds': result['execution_seconds'], 'errors': result['errors'],
        'pages': [{'page': p['page'], 'status': p['status'], 'errors': p['errors'],
                   'blocks': dict(Counter(b['language'] for b in p['blocks'])),
                   'timings': p['timings']} for p in result['pages']],
        'attempts': result['attempts'],
        'quality': [
            {k: r[k] for k in ('page', 'language', 'status', 'metrics', 'warnings')}
            for r in evaluation['ocr_metrics']['records']
        ],
    }, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('native', 'recorded', 'ocr', 'complete', 'tables',
                                         'reference-draft', 'reference-approve', 'reference-check'))
    parser.add_argument('--pages', nargs='+', type=int, default=[1])
    parser.add_argument('--max-side', type=int, default=1280)
    parser.add_argument('--fallback', choices=('off', 'preprocess'), default='off')
    parser.add_argument('--page-timeout', type=float, default=100)
    parser.add_argument('--ocr-result', type=Path, action='append')
    parser.add_argument('--sections', type=Path)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--draft-dir', type=Path)
    parser.add_argument('--reviewer')
    parser.add_argument('--language', choices=('fr', 'ar'), default='ar')
    parser.add_argument('--job', help='Chemin du suivi depuis P2 pour le mode tables.')
    arguments = parser.parse_args()
    if arguments.mode.startswith('reference-'):
        batches = arguments.ocr_result or []
        if len(batches) > 1:
            parser.error('Fournir un seul lot OCR pour cette opération.')
        ocr = batches[0] if batches else None
        if arguments.mode == 'reference-draft':
            if not arguments.draft_dir:
                parser.error('Indiquer --draft-dir.')
            print(draft_references(arguments.draft_dir, arguments.pages, arguments.language, ocr, arguments.sections))
        elif arguments.mode == 'reference-approve':
            if not arguments.reviewer or bool(arguments.reference) == bool(arguments.annotations):
                parser.error('Indiquer --reviewer et un seul fichier avec --reference ou --annotations.')
            print(approve_reference(arguments.reference or arguments.annotations, arguments.reviewer))
        else:
            result = evaluate_quality(ocr, arguments.reference, arguments.sections, arguments.annotations)
            print(result['output_paths']['evaluation_report.md'])
            for record in result['ocr_metrics']['records']:
                if record['reference_validation']['approval']:
                    print(record['page'], record['language'], record['status'], record['warnings'])
            metrics = result['segmentation_metrics']
            print('Segmentation :', metrics['status'], metrics['warnings'])
        return
    if arguments.mode == 'tables':
        if not arguments.job:
            parser.error('Indiquer --job.')
        job = load_delivery(arguments.job)
        for entry in job['documents']:
            exports = entry['outputs']
            if 'document_json' in exports:
                result = extract_tables(resolve_export(exports['document_json']),
                                        resolve_export(exports['sections_json']) if 'sections_json' in exports else None,
                                        OUTPUT / 'tables')
                print(result['status'], result['run_directory'])
        return
    with pymupdf.open(PDF) as pdf:
        page_count = len(pdf)
        print('DCE:', page_count, 'pages, sha256:', sha256(PDF), flush=True)
    if arguments.mode == 'ocr':
        check_ocr(arguments.pages, arguments.max_side, arguments.fallback, arguments.page_timeout)
    elif arguments.mode == 'complete':
        replay_complete(page_count)
    else:
        check_pipeline(arguments.mode == 'recorded', arguments.pages, arguments.ocr_result or [RECORDED])


if __name__ == '__main__':
    main()
