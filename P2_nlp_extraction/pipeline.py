"""Une entrée P2 : stockage, ingestion, conversion, sections, tableaux et qualité."""
import argparse
import copy
import hashlib
from dataclasses import asdict, replace
import json
from pathlib import Path
import re
from threading import Lock
from time import perf_counter
from uuid import uuid4

from .document_ingestion import ingest_path, IngestionLimits
from .document_conversion import convert_ingestion, ConversionOptions, ConversionLimits
from .document_conversion.models import AUTO_LIMITS, DELIVERY_OCR_MAX_SIDE, atomic_text
from .document_conversion.manifest_validation import artifact_path, confined
from .document_segmentation import segment_document
from .table_extraction import extract_tables
from .table_extraction.extraction import bpu_csv, tables_csv
from .quality_evaluation import evaluate_quality
from .scripts.ocr_common import ROOT, sha256
from .storage import output_path, store_document, resolve_document, resolve_export

_RUN_LOCK = Lock()


def load_job(job_path):
    """Relire un suivi après fermeture de l'interface, sans relancer de traitement."""
    from jsonschema import Draft202012Validator
    path = Path(job_path)
    path = output_path(path if path.is_absolute() else ROOT / path)
    if path.name != 'job.json' or path.stat().st_size > 2 * 1024**2:
        raise ValueError('Fichier de suivi invalide ou trop volumineux.')
    value = json.loads(path.read_text(encoding='utf-8'))
    schema = json.loads((ROOT / 'config/pipeline.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate(value)
    return value


def _checkpoint(job, folder, progress):
    def persist():
        atomic_text(folder / 'job.json', json.dumps(job, ensure_ascii=False, indent=2, allow_nan=False), 2 * 1024**2)
    persist()
    if progress:
        try:
            progress(copy.deepcopy(job))
        except Exception:
            if 'progress_callback_failed' not in job['warnings']:
                job['warnings'].append('progress_callback_failed')
                persist()


def _step(job, folder, progress, name, action):
    """Une étape conserve son erreur et laisse les résultats précédents accessibles."""
    step = dict(name=name, status='processing', seconds=0, errors=[], warnings=[])
    job['steps'].append(step)
    _checkpoint(job, folder, progress)
    start = perf_counter()
    try:
        result = action()
        step['status'] = result.get('status', 'completed')
        if 'ocr_metrics' in result and 'segmentation_metrics' in result:
            ocr_states = {v['status'] for v in result['ocr_metrics']['aggregates'].values()}
            if 'partial' in ocr_states:
                step['status'] = 'partial'
            elif 'evaluated' not in ocr_states and result['segmentation_metrics']['status'] == 'not_evaluated':
                step['status'] = 'not_evaluated'
        step['errors'] = result.get('errors', [])
        step['warnings'] = result.get('warnings', [])
        return result
    except Exception as exc:
        step['status'] = 'failed'
        step['errors'].append(dict(code=type(exc).__name__, message=str(exc)))
        return None
    finally:
        step['seconds'] = perf_counter() - start
        import psutil
        step['supervisor_rss_after_bytes'] = psutil.Process().memory_info().rss
        _checkpoint(job, folder, progress)


def _exports(paths):
    """Indexer les exports avec leurs empreintes, sans recopier leurs contenus."""
    return {name: dict(path=output_path(path).relative_to(ROOT).as_posix(),
                       sha256=sha256(output_path(path)), size_bytes=output_path(path).stat().st_size)
            for name, path in paths.items()}


def _quality_inputs(document, document_folder, cache_paths):
    # T24 écrit des copies privées ocr_batch_*.json. Les réutilisations doivent
    # avoir été explicitement fournies par l'appelant, pas par un chemin JSON.
    paths = set()
    allowed = set()
    for path in map(Path, cache_paths):
        base = ROOT.parent if path.parts[:1] == (ROOT.name,) else ROOT
        allowed.add(base / path)
    for page in document['pages']:
        provenance = page.get('ocr_provenance', {})
        if 'ocr_json' not in provenance:
            continue
        path = confined(ROOT / provenance['ocr_json'])
        if not (path.is_relative_to(document_folder) or path in allowed):
            raise ValueError('Source OCR hors des résultats autorisés.')
        if sha256(path) != provenance.get('ocr_json_sha256'):
            raise ValueError('Le résultat OCR a changé depuis la conversion.')
        paths.add(path)
    return sorted(paths)


def _process_document(item, conversion_folder, job, folder, progress, references, annotations):
    first_step = len(job['steps'])
    document_id = item['document_id']
    if not re.fullmatch(r'f[0-9]{6,}', document_id):
        raise ValueError('Identifiant T24 invalide.')
    document_folder = output_path(conversion_folder / 'documents' / document_id)
    source = document_folder / 'document.json'
    document = json.loads(source.read_text(encoding='utf-8'))
    result = dict(document_id=document_id, source=document['source'],
                  status=document['status'], outputs=_exports({
                      'document_json': source, 'document_md': source.with_suffix('.md')}), quality=[])
    job['documents'].append(result)
    destination = folder / 'documents' / document_id
    segmentation = _step(job, folder, progress, document_id + ':sections',
                         lambda: segment_document(source, destination / 'sections'))
    if segmentation:
        result['outputs'].update(_exports({'sections_json': segmentation['sections_json_path'],
                                          'sections_md': segmentation['markdown_path']}))
    tables = _step(job, folder, progress, document_id + ':tables',
                   lambda: extract_tables(source, segmentation['sections_json_path'] if segmentation else None,
                                          destination / 'tables'))
    if tables:
        result['outputs'].update(_exports(tables['output_paths']))
    ocr_inputs = _quality_inputs(document, document_folder, job['options']['ocr_results']) or [None]
    for index, ocr in enumerate(ocr_inputs):
        quality = _step(job, folder, progress, f'{document_id}:quality:{index}',
                        lambda: evaluate_quality(ocr, references,
                            segmentation['sections_json_path'] if segmentation else None, annotations,
                            destination / 'quality'))
        if quality:
            result['quality'].append(dict(
                ocr_status={lang: value['status'] for lang, value in quality['ocr_metrics']['aggregates'].items()},
                segmentation_status=quality['segmentation_metrics']['status'],
                outputs=_exports(quality['output_paths'])))
    if result['status'] not in ('failed', 'rejected') and any(
            value and value['status'] == 'partial' for value in (segmentation, tables)):
        result['status'] = 'partial'
    if not segmentation or not tables or not result['quality']:
        result['status'] = 'partial' if result['status'] != 'failed' else 'failed'
    if result['status'] not in ('failed', 'rejected') and any(
            step['status'] in ('partial', 'failed', 'rejected') or step['errors']
            for step in job['steps'][first_step:]):
        result['status'] = 'partial'
    result['finished'] = True


def _member_id(item):
    payload = json.dumps([item['relative_path'], item['sha256']], ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def load_delivery(job_path):
    """Return a portable team handoff with verified local export descriptors."""
    job = load_job(job_path)
    if job['source']:
        resolve_document(job['source'])
    members = None
    if job.get('ingestion_manifest'):
        manifest = json.loads(resolve_export(job['ingestion_manifest']).read_bytes())
        if not job['source'] or manifest['source']['sha256'] != job['source']['sha256']:
            raise ValueError('Le manifeste ne correspond pas à la source du traitement.')
        members = {(item['relative_path'], item['sha256']) for item in manifest['files']
                   if item['eligible_for_t24']}
    seen = set()
    for entry in job['documents']:
        source = entry['source']
        if source.get('relative_path') and source.get('sha256'):
            identity = _member_id(source)
            if (entry.setdefault('member_id', identity) != identity or identity in seen or
                    (members is not None and (source['relative_path'], source['sha256']) not in members)):
                raise ValueError('Identité du membre incohérente dans la livraison.')
            seen.add(identity)
        outputs = entry['outputs']
        conversion = outputs.get('document_json')
        for name, export in outputs.items():
            path = resolve_export(export)
            if name == 'document_json' and json.loads(path.read_bytes())['source'] != source:
                raise ValueError('La conversion livrée ne correspond pas au membre.')
            if conversion and name in ('sections_json', 'tables_json', 'bpu_json'):
                derived = json.loads(path.read_bytes())
                if derived['source']['conversion_json_sha256'] != conversion['sha256']:
                    raise ValueError('Un export dérivé ne correspond pas à la conversion du membre.')
                csv_export = outputs.get(name.removesuffix('_json') + '_csv')
                if csv_export and name in ('tables_json', 'bpu_json'):
                    serialize = tables_csv if name == 'tables_json' else bpu_csv
                    expected = hashlib.sha256(serialize(derived['tables'])).hexdigest()
                    if csv_export['sha256'] != expected:
                        raise ValueError('Un export CSV ne correspond pas à son JSON.')
        for export in [value for evaluation in entry['quality'] for value in evaluation['outputs'].values()]:
            resolve_export(export)
    return job


def resolve_member_source(job_path, member_id):
    """Resolve an original PDF or DOCX by the stable member ID of a delivery."""
    job = load_delivery(job_path)
    entry = next((item for item in job['documents'] if item.get('member_id') == member_id), None)
    if entry is None or 'ingestion_manifest' not in job:
        raise ValueError('Membre ou manifeste indisponible dans cette livraison.')
    manifest_path = resolve_export(job['ingestion_manifest'])
    manifest = json.loads(manifest_path.read_bytes())
    source = entry['source']
    item = next(item for item in manifest['files'] if item['eligible_for_t24']
                and (item['relative_path'], item['sha256']) == (source['relative_path'], source['sha256']))
    path = artifact_path(manifest_path.parent, item)
    if path.stat().st_size != source['size_bytes'] or sha256(path) != source['sha256']:
        raise ValueError('Original du membre modifié depuis le traitement.')
    return path


def run_pipeline(source_path, output_dir=None, *, options=None, ingestion_limits=None,
                 conversion_limits=None, reference_manifest_path=None,
                 section_annotations_path=None, progress=None, _previous=None):
    """Traiter un PDF, DOCX ou ZIP séquentiellement. Aucun OCR par défaut.

    Retour : job versionné avec identifiants, étapes, erreurs et liens relatifs
    des exports. progress(job) reçoit un instantané à chaque début/fin d'étape.
    Les API T23 à T28 restent disponibles. Aucun backend P6/P5 n'est simulé.
    """
    options = options or ConversionOptions(ocr_mode='never')
    ingestion_limits = ingestion_limits or IngestionLimits()
    conversion_limits = conversion_limits or ConversionLimits()
    options.validate(); ingestion_limits.validate(); conversion_limits.validate()
    if progress is not None and not callable(progress):
        raise TypeError('progress doit être une fonction.')
    persisted_options = json.loads(json.dumps(asdict(options)))
    if options.ocr_results:
        # Accept the existing caller-relative paths and P2-relative descriptors.
        paths = []
        for value in map(Path, options.ocr_results):
            if not value.is_absolute():
                candidate = value.absolute()
                if not candidate.is_relative_to(ROOT) or not candidate.exists():
                    base = ROOT.parent if value.parts[:1] == (ROOT.name,) else ROOT
                    value = base / value
            paths.append(confined(value, must_exist=False))
        options = replace(options, ocr_results=tuple(map(str, paths)))
        persisted_options['ocr_results'] = [path.relative_to(ROOT).as_posix() for path in paths]
    base = output_path(output_dir or ROOT / 'outputs/runs')
    if not _RUN_LOCK.acquire(blocking=False):
        raise RuntimeError('Un traitement P2 est déjà en cours dans ce processus.')
    started = perf_counter()
    try:
        folder = base / uuid4().hex[:16]
        folder.mkdir(parents=True, exist_ok=False)
        job = dict(schema_version='p2.pipeline.v1', job_id=folder.name, status='processing',
                   source=None, options=persisted_options, steps=[], documents=[], warnings=[], errors=[],
                   integrations=dict(storage='local_only', team_backend='not_connected',
                                     final_response_dossier='outside_p2'), execution_seconds=0,
                   job_path=(folder / 'job.json').relative_to(ROOT).as_posix())
        job['settings'] = {'ingestion': asdict(ingestion_limits), 'conversion': asdict(conversion_limits),
                           'has_references': bool(reference_manifest_path or section_annotations_path)}
        if _previous:
            job['resume'] = {'from': _previous['job_path'], 'changes': {}, 'reused': []}
        def page_progress(value):
            job.setdefault('page_progress', {})[value['document_id']] = value
            _checkpoint(job, folder, progress)
        _checkpoint(job, folder, progress)
        stored = _step(job, folder, progress, 'storage', lambda: store_document(
            source_path, directory=base.parent / 'library', max_bytes=ingestion_limits.max_source_bytes))
        if stored:
            job['source'] = stored
            ingestion = _step(job, folder, progress, 'ingestion', lambda: ingest_path(
                resolve_document(stored), folder / 'ingestion', dce_id=stored['document_id'], limits=ingestion_limits))
            if ingestion and ingestion['status'] == 'completed_with_issues':
                job['warnings'].extend(
                    f"Fichier non converti ({item['status']}) : {item['relative_path']}"
                    for item in ingestion['files']
                    if not item['eligible_for_t24'] and item['status'] != 'directory'
                )
            if ingestion:
                job['ingestion_manifest'] = _exports({'manifest': ingestion['manifest_path']})['manifest']
            archive = bool(ingestion and ingestion['source']['detected_type'] == 'zip')
            if _previous and archive and ingestion['status'] in ('completed','completed_with_issues'):
                old_manifest = json.loads(resolve_export(_previous['ingestion_manifest']).read_bytes())
                old = {x['relative_path']: x['sha256'] for x in old_manifest['files'] if x['sha256']}
                new = {x['relative_path']: x['sha256'] for x in ingestion['files'] if x['sha256']}
                job['resume']['changes'] = {
                    'added': sorted(new.keys() - old.keys()), 'removed': sorted(old.keys() - new.keys()),
                    'modified': sorted(k for k in old.keys() & new.keys() if old[k] != new[k]),
                }
            if _previous and ingestion and not archive:
                job['errors'].append({'code': 'resume_source_not_zip', 'message': 'La source de révision doit être un ZIP.'})
                ingestion = None
            if ingestion and ingestion['eligible_for_t24']:
                eligible = [item for item in ingestion['files'] if item['eligible_for_t24']]
                reusable = {}
                if _previous and archive:
                    previous_options = {k: v for k,v in _previous['options'].items() if k != 'ocr_results'}
                    current_options = {k: v for k,v in persisted_options.items() if k != 'ocr_results'}
                    if (_previous.get('settings') == job['settings'] and not job['settings']['has_references']
                            and previous_options == current_options):
                        for entry in _previous['documents']:
                            if (entry['status'] not in ('completed','completed_with_review')
                                    or not entry.get('finished')
                                    or new.get(entry['source']['relative_path']) != entry['source']['sha256']):
                                continue
                            for export in list(entry['outputs'].values()) + [
                                    e for q in entry['quality'] for e in q['outputs'].values()]:
                                resolve_export(export)
                            reusable[_member_id(entry['source'])] = entry
                groups = [[item] for item in eligible] if archive and len(eligible) <= conversion_limits.max_documents else [eligible]
                remaining_seconds = conversion_limits.timeout_seconds
                for group in groups:
                    member = group[0]
                    stable = _member_id(member)
                    prior = reusable.get(stable) if len(group) == 1 else None
                    if prior:
                        reused = copy.deepcopy(prior)
                        # The T24 source ID belongs to its original manifest; keep it in source.
                        reused.update(document_id=member['file_id'], member_id=stable)
                        job['documents'].append(reused)
                        job['resume']['reused'].append(stable)
                        _checkpoint(job, folder, progress)
                        continue
                    if remaining_seconds <= 0:
                        job['errors'].append({'code': 'conversion_timeout',
                                              'message': 'Budget de conversion du ZIP épuisé.',
                                              'document_id': member['file_id']})
                        continue
                    conversion_started = perf_counter()
                    conversion = _step(job, folder, progress, 'conversion', lambda: convert_ingestion(
                        ingestion['manifest_path'], folder / 'conversion', options=options,
                        limits=replace(conversion_limits, timeout_seconds=remaining_seconds),
                        progress=page_progress, **({'file_ids': [item['file_id'] for item in group]} if archive and len(groups) > 1 else {})))
                    remaining_seconds -= perf_counter() - conversion_started
                    if conversion:
                        for item in conversion['documents']:
                            try:
                                _process_document(item, Path(conversion['run_directory']), job, folder, progress,
                                                  reference_manifest_path, section_annotations_path)
                                job['documents'][-1]['member_id'] = _member_id(job['documents'][-1]['source'])
                            except Exception as exc:
                                job['errors'].append(dict(code=type(exc).__name__, message=str(exc),
                                                          document_id=item.get('document_id')))
                            _checkpoint(job, folder, progress)
            elif ingestion:
                job['warnings'].append('ingestion_no_eligible_document')
        bad = {'partial', 'failed', 'rejected', 'completed_with_issues'}
        incomplete = (bool(job['errors']) or any(s['status'] in bad or s['errors'] for s in job['steps'])
                      or any(d['status'] in bad for d in job['documents']))
        usable = any(d['status'] not in ('failed', 'rejected') for d in job['documents'])
        job['status'] = ('partial' if incomplete else 'completed_with_review') if usable else 'failed'
        job['warnings'].append('human_review_required_results_are_not_validated_references')
        job['execution_seconds'] = perf_counter() - started
        _checkpoint(job, folder, progress)
        return job
    finally:
        _RUN_LOCK.release()


def resume_job(job_path, *, options=None, conversion_limits=None, progress=None, source_path=None):
    """Resume a stored source in a new linked run, keeping the old evidence.

    Current OCR results are reused after hash checks; failed pages are retried.
    Explicit OCR inputs replace automatic cache recovery.
    ZIP caches are routed to each member by its PDF SHA-256.
    """
    previous = load_job(job_path)
    if previous['source'] is None:
        raise ValueError('Aucune source persistée pour reprendre ce suivi.')
    source = resolve_document(previous['source']) if source_path is None else source_path
    manifest_entry = previous.get('ingestion_manifest')
    archive = bool(manifest_entry and json.loads(resolve_export(manifest_entry).read_bytes())['source']['detected_type'] == 'zip')
    if source_path is not None and not archive:
        raise ValueError('Le remplacement de source est réservé aux suivis ZIP avec manifeste.')
    settings = previous.get('settings') or {}
    if conversion_limits is None and settings.get('conversion'):
        conversion_limits = ConversionLimits(**settings['conversion'])
    selected = options if options is not None else replace(
        ConversionOptions(**previous['options']), ocr_results=())
    selected.validate()
    caches = set(selected.ocr_results)
    recover_caches = not caches and source_path is None
    folder = output_path(ROOT / previous['job_path']).parent
    cache_folder = None
    recovered_digests = set()
    for entry in previous['documents']:
        artifact = entry['outputs']['document_json']
        path = output_path(ROOT / artifact['path'])
        if sha256(path) != artifact['sha256']:
            raise ValueError('Conversion précédente modifiée : reprise refusée.')
        if not recover_caches:
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        digest = data.get('source', {}).get('sha256')
        if digest in recovered_digests:
            continue
        # Explicit option changes invalidate the automatically recovered OCR cache.
        if any(data['options'].get(k) != getattr(selected, k) for k in
               ('ocr_dpi', 'ocr_detector_max_side', 'ocr_fallback_mode',
                'ocr_max_fallback_blocks', 'ocr_fallback_timeout_seconds')):
            continue
        document_caches = _quality_inputs(data, path.parent, previous['options']['ocr_results'])
        if document_caches and digest:
            recovered_digests.add(digest)
        for cache in document_caches:
            # An earlier batch may own page 1 while a retry now owns page 2.
            # Keep only the pages still selected by the conversion's provenance,
            # so the original failed page cannot conflict with its replacement.
            numbers = {page['page'] for page in data['pages']
                       if page.get('ocr_provenance', {}).get('ocr_json')
                       == cache.relative_to(ROOT).as_posix()}
            raw = json.loads(cache.read_text(encoding='utf-8'))
            pages = [page for page in raw['pages'] if page['page'] in numbers]
            if len(pages) != len(raw['pages']):
                if cache_folder is None:
                    cache_folder = output_path(folder.parent / 'resume_cache' / uuid4().hex[:16])
                    cache_folder.mkdir(parents=True, exist_ok=False)
                raw = {**raw, 'pages': pages,
                       'selected_pages': [number for number in raw['selected_pages'] if number in numbers]}
                cache = cache_folder / f'ocr_{len(caches):04d}.json'
                atomic_text(cache, json.dumps(raw, ensure_ascii=False, allow_nan=False),
                            (conversion_limits or ConversionLimits()).max_output_bytes)
            caches.add(str(cache))
    selected = replace(selected, ocr_results=tuple(sorted(caches)))
    result = run_pipeline(source, folder.parent, options=selected,
                          conversion_limits=conversion_limits, progress=progress,
                          ingestion_limits=IngestionLimits(**settings.get('ingestion', {})),
                          **({'_previous': previous if options is None or not options.ocr_results else
                              {**previous, 'settings': None}}
                             if archive else {}))
    result['warnings'].append('resumed_from:' + previous['job_path'])
    _checkpoint(result, output_path(ROOT / result['job_path']).parent, progress)
    return result


def main():
    parser = argparse.ArgumentParser(description='Pipeline P2 local, sans OCR par défaut.')
    parser.add_argument('source')
    parser.add_argument('--pages', type=int, nargs='+', help='Pages physiques PDF, à partir de 1.')
    parser.add_argument('--ocr', choices=('never', 'reuse_only', 'auto'), default='never')
    parser.add_argument('--ocr-result', action='append', default=[])
    args = parser.parse_args()
    result = run_pipeline(args.source, options=ConversionOptions(
        ocr_mode=args.ocr, pdf_pages=args.pages, ocr_results=tuple(args.ocr_result),
        ocr_detector_max_side=DELIVERY_OCR_MAX_SIDE if args.ocr == 'auto' else None),
        conversion_limits=AUTO_LIMITS if args.ocr == 'auto' else None)
    print(json.dumps(dict(status=result['status'],job_path=result['job_path']),ensure_ascii=False))
    return {'failed': 1, 'partial': 2}.get(result['status'], 0)


if __name__ == '__main__':
    raise SystemExit(main())
