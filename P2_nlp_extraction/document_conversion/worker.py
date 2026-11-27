"""Un document par processus, exports progressifs et adaptateur OCR public."""
import argparse
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path
import re
from time import monotonic, perf_counter

from ..document_ingestion.detection import detect_file
from ..document_ingestion.models import Budget as IngestionBudget, IngestionLimits
from ..scripts.ocr_common import ROOT
from . import docx_native, ocr_adapter, pdf_native, scan_tables
from .layout import merge_native_ocr, order_blocks
from .manifest_validation import artifact_path, confined, load_json, relative, snapshot, validate_manifest
from .markdown import render
from .models import Budget, ConversionFailure, ConversionLimits, ConversionOptions, error, write_json, atomic_text


_LOCATOR = re.compile(
    r"(?P<date>(?<![\w/])(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.–-]\d{1,2}[/.–-]\d{4})(?![\w/]))"
    r"|(?P<reference>(?<!\w)(?:n\s*[°º]|numéro|réf(?:érence)?\.?|رقم)\s*:?\s*"
    r"(?=[\w./-]*\d)[\w]+(?:[./-][\w]+)*)",
    re.IGNORECASE,
)


def _text_locators(blocks):
    """Index source mentions without interpreting their contractual meaning."""
    for block in blocks:
        text = block['raw_text']
        if not text or block['type'] in ('table', 'unresolved') or block.get('native_usable') is False:
            continue
        for match in _LOCATOR.finditer(text):
            yield dict(kind=match.lastgroup, raw_text=match.group(), block_id=block['block_id'],
                       page=block['page'], span=list(match.span()), method=block['method'],
                       bbox=block['bbox'], needs_review=True)


def initial_document(item, manifest, manifest_path, digest, options):
    return {'schema_version': 'p2.conversion_document.v1', 'document_id': item['file_id'],
            'status': 'processing', 'human_validated': False,
            'source': {'ingestion_run_id': manifest['run_id'], 'file_id': item['file_id'],
                       'manifest_path': relative(manifest_path), 'manifest_sha256': digest,
                       'original_name': item['original_name'], 'relative_path': item['relative_path'],
                       'artifact_path': item['artifact_path'], 'sha256': item['sha256'],
                       'size_bytes': item['size_bytes'], 'detected_type': item['detected_type']},
            'coordinate_system': 'displayed_page_points_top_left_rotation_applied; DOCX=null',
            'pages': [], 'blocks': [], 'sections': [], 'warnings': [], 'errors': [],
            'coverage': {'source_page_count': None, 'requested_pages': None, 'processed_pages': []},
            'options': {**asdict(options), 'ocr_results': []},
            'versions': {name: version(name) for name in ('PyMuPDF', 'python-docx', 'lxml')},
            'outputs': {'markdown': 'document.md', 'json': 'document.json'}, 'execution_seconds': 0.0}


def export(folder, result, limits):
    from .ocr_structure import structure_page
    for index, block in enumerate(result['blocks'], 1):
        block['block_id'] = f"{result['document_id']}_b{index:06d}"
    if result['status'] != 'processing':
        result['text_locators'] = list(_text_locators(result['blocks']))
    for page in result['pages']:
        if any(b.get('method') == 'ocr' for b in page['blocks']):
            page['structure'] = structure_page(page, result['document_id'])
    md = render(result)
    atomic_text(folder / 'document.md', md, limits.max_output_bytes)
    write_json(folder / 'document.json', result, limits.max_output_bytes)
    write_json(folder / 'progress.json', {'document_id': result['document_id'], 'status': result['status'],
        'pages': [{'page': p['page'], 'status': p['status'], 'blocks': len(p['blocks'])} for p in result['pages']]},
        limits.max_output_bytes)


def flatten(result, limits):
    result['blocks'] = [b for p in result['pages'] for b in p['blocks']]
    if len(result['blocks']) > limits.max_blocks:
        raise ConversionFailure('block_limit', 'Trop de blocs dans le document.')


def convert_pdf(path, folder, result, options, limits, budget):
    import pymupdf
    with pymupdf.open(path) as pdf:
        count = len(pdf)
        numbers = sorted(options.pdf_pages or range(1, count + 1))
        result['coverage']['source_page_count'] = count
        result['coverage']['requested_pages'] = numbers
        if not numbers or numbers[-1] > count:
            raise ConversionFailure('page_range', 'Une page demandée est absente du PDF.')
        if len(numbers) > limits.max_pages:
            raise ConversionFailure('page_limit', 'Nombre de pages supérieur à la limite.')
        if len(numbers) != count:
            result['warnings'].append('only_requested_pages_converted')
        for number in numbers:
            budget.tick()
            start = perf_counter()
            page = pdf_native.extract_page(pdf[number - 1], options, limits, budget)
            page['timings'] = {'native_seconds': perf_counter() - start}
            if page['routing']['decision'] == 'blank':
                page['status'] = 'apparently_blank'
                page['warnings'].append('blank_page_heuristic_not_human_verified')
            elif page['routing']['decision'] in ('ocr', 'hybrid'):
                page['status'] = 'awaiting_ocr'
            else:
                page['status'] = 'completed'
            if len(result['blocks']) + len(page['blocks']) > limits.max_blocks:
                raise ConversionFailure('block_limit', 'Trop de blocs dans le document.')
            result['pages'].append(page)
            result['coverage']['processed_pages'].append(number)
            flatten(result, limits)
            export(folder, result, limits)
    needed = [p['page'] for p in result['pages'] if p['status'] == 'awaiting_ocr']
    geometries = {p['page']: p for p in result['pages']}
    cached = ocr_adapter.cached_pages(options.ocr_results, result['source']['sha256'], geometries, options, limits) if options.ocr_results else {}
    # Interrupted/empty results are evidence to retain, not successful cache hits.
    retry = {n for n, r in cached.items() if r['status'] in ('error', 'processing') or not r['blocks']} if options.ocr_mode == 'auto' else set()
    previous = {n: cached.pop(n) for n in retry}
    missing = [n for n in needed if n not in cached]
    if len(missing) > limits.max_ocr_pages and options.ocr_mode == 'auto':
        raise ConversionFailure('ocr_page_limit', 'Nombre de pages nécessitant un OCR supérieur à la limite.')
    applied = set()
    def apply_ocr(number):
        page, record = geometries[number], cached.get(number)
        if number in previous:
            # Keep the earlier diagnostics, but do not turn an old error into a new failure.
            page['warnings'].append('previous_failed_ocr_retried')
            if record is None:
                record = previous[number]
            else:
                record = {**record, 'provenance': {**record['provenance'],
                    'previous_ocr_attempt': previous[number]['provenance']}}
        if record is not None:
            # Provenance and diagnostics belong to every OCR result, including
            # empty/failed results. Never depend on a successful text merge.
            page['warnings'].extend(record['warnings'])
            page['errors'].extend(record['errors'])
            page['ocr_provenance'] = record['provenance']
            page['timings']['ocr_reported'] = record['timings']
        if record is None:
            page['status'] = 'needs_ocr'
            page['errors'].append(error('ocr_required_not_available', 'OCR nécessaire mais désactivé ou résultat absent.'))
        elif not record['blocks']:
            page['status'] = 'ocr_incomplete'
            page['errors'].append(error('ocr_incomplete', 'Résultat OCR vide ou en erreur malgré le contenu visuel.'))
        else:
            incomplete = record['status'] in ('error', 'processing')
            if incomplete:
                page['errors'].append(error('ocr_incomplete', 'Blocs partiels OCR conservés ; page interrompue.'))
                page['warnings'].append('ocr_partial_blocks_preserved_unvalidated')
            native = [b for b in page['blocks'] if b.get('native_usable', True)]
            rejected_native = [b for b in page['blocks'] if not b.get('native_usable', True)]
            merged = merge_native_ocr(native, record['blocks']) + rejected_native
            if options.extract_tables and not incomplete and page['routing']['decision'] == 'ocr':
                with pymupdf.open(path) as pdf:
                    merged, warnings = scan_tables.add_scan_tables(pdf[number - 1], merged, limits, budget)
                page['warnings'].extend(warnings)
            total = len(result['blocks']) - len(page['blocks']) + len(merged)
            if len(merged) > limits.max_blocks_per_page or total > limits.max_blocks:
                page['status'] = 'ocr_incomplete'
                page['errors'].append(error('block_limit', 'Fusion OCR trop volumineuse ; résultat brut disponible dans la référence OCR.'))
            else:
                page['blocks'] = merged
                page['status'] = 'ocr_incomplete' if incomplete else 'completed_with_review'
        applied.add(number)
        flatten(result, limits)
        export(folder, result, limits)
    for number in needed:
        if number in cached:
            apply_ocr(number)
    for offset in range(0, len(missing), options.ocr_batch_size):
        if options.ocr_mode != 'auto':
            break
        budget.tick()
        batch = missing[offset:offset + options.ocr_batch_size]
        for number in batch:
            geometries[number]['status'] = 'processing'
        export(folder, result, limits)
        start = perf_counter()
        try:
            # Keep raw runs linked to the conversion and document IDs without
            # nesting their page diagnostics under the conversion output tree.
            ocr_folder = ROOT / 'outputs/ocr/runs' / folder.parents[1].name / folder.name
            raw = ocr_adapter.recognize(path, batch, ocr_folder, options, limits, budget)
            if raw is not None:
                # Stockage privé ; aucune confiance dans exports/image/source_pdf.
                cache = folder / f'ocr_batch_{offset:04d}.json'
                write_json(cache, raw, limits.max_output_bytes)
                cached.update(ocr_adapter.cached_pages([str(cache)], result['source']['sha256'],
                                                      {n: geometries[n] for n in batch}, options, limits))
        except ConversionFailure as exc:
            for number in batch:
                geometries[number]['errors'].append(error(exc.code, str(exc)))
        for number in batch:
            geometries[number]['timings']['ocr_batch_seconds'] = perf_counter() - start
            apply_ocr(number)
    for number in needed:
        if number not in applied:
            apply_ocr(number)
    incomplete = any(p['status'] in ('needs_ocr', 'ocr_incomplete', 'awaiting_ocr') or p['errors'] for p in result['pages'])
    for page in result['pages']:
        for issue in page['errors']:
            result['errors'].append({'code': issue.get('code', 'ocr_page_error'),
                                     'message': issue.get('message', 'Erreur de page OCR.'), 'page': page['page']})
    review = any(b['needs_review'] for b in result['blocks']) or any(p['status'] == 'apparently_blank' for p in result['pages'])
    result['status'] = 'partial' if incomplete else 'completed_with_review' if review else 'completed'


def process_request(request):
    start = monotonic()
    options, limits = ConversionOptions(**request['options']), ConversionLimits(**request['limits'])
    options.validate(); limits.validate()
    budget = Budget(limits)
    folder = confined(request['document_directory'])
    result = request['initial_document']
    validated = False
    try:
        manifest_path, manifest, items, digest = validate_manifest(request['manifest_path'], limits, [result['document_id']])
        if digest != result['source']['manifest_sha256']:
            raise ConversionFailure('manifest_integrity_mismatch', 'Le manifeste T23 a changé pendant la conversion.')
        item = items[0]
        source = artifact_path(manifest_path.parent, item)
        private = folder / ('.source.' + item['detected_type'])
        snapshot(source, private, item, limits, budget)
        ilimits = replace(IngestionLimits(), max_source_bytes=limits.max_source_bytes,
                          max_file_bytes=limits.max_source_bytes,
                          max_total_bytes=max(limits.max_docx_expanded_bytes, limits.max_source_bytes),
                          timeout_seconds=max(.01, budget.remaining))
        detection = detect_file(private, item['original_name'], IngestionBudget(ilimits))
        if detection.get('status') != 'ready' or detection.get('detected_type') != item['detected_type']:
            raise ConversionFailure('source_type_mismatch', 'Le contenu réel ne correspond pas au document admis par T23.')
        validated = True
        if item['detected_type'] == 'pdf':
            convert_pdf(private, folder, result, options, limits, budget)
        else:
            if options.pdf_pages is not None:
                raise ConversionFailure('docx_pages_unavailable', 'pdf_pages ne peut pas sélectionner des pages DOCX.')
            blocks, sections, warnings = docx_native.extract_docx(private, options, limits, budget)
            result.update(blocks=blocks, sections=sections, warnings=warnings)
            omitted = any(w in warnings for w in ('revisions_content_controls_or_text_boxes_may_be_omitted', 'notes_or_comments_not_rendered'))
            omitted = omitted or any('embedded_image_not_ocr_processed' in b['warnings'] for b in blocks)
            result['status'] = 'partial' if omitted else 'completed_with_review' if warnings or any(b['needs_review'] for b in blocks) else 'completed'
    except Exception as exc:
        code = getattr(exc, 'code', 'conversion_failed' if validated else 'source_rejected')
        # Pas de chemins personnels/texte confidentiel dans les exceptions publiques.
        message = str(exc) if isinstance(exc, ConversionFailure) else 'Conversion interrompue : ' + type(exc).__name__
        result['errors'].append(error(code, message))
        result['status'] = 'partial' if result['blocks'] or result['pages'] else 'failed' if validated else 'rejected'
    result['execution_seconds'] = monotonic() - start
    export(folder, result, limits)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    request, _ = load_json(args.request, ConversionLimits().max_manifest_bytes)
    process_request(request)


if __name__ == '__main__':
    main()
