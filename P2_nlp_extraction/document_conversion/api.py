"""API T24 : validation T23 puis conversion séquentielle dans des processus bornés."""
from dataclasses import asdict
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep
from uuid import uuid4

from ..scripts.ocr_common import ROOT
from .manifest_validation import confined, load_json, relative, validate_manifest
from .models import ConversionLimits, ConversionOptions, error, write_json


def _stop(process):
    import psutil
    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    for child in reversed(descendants):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def _run(request_path, document_folder, limits):
    import psutil
    start, failure = monotonic(), None
    with (document_folder / 'worker.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-B', '-X', 'utf8', '-m',
                                    'P2_nlp_extraction.document_conversion.worker', '--request', str(request_path)],
                                   cwd=ROOT.parent, stdout=log, stderr=subprocess.STDOUT,
                                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        try:
            while process.poll() is None:
                if monotonic() - start > limits.timeout_seconds:
                    failure = error('timeout', 'Délai dépassé ; processus de conversion arrêté.')
                try:
                    parent = psutil.Process(process.pid)
                    rss = parent.memory_info().rss
                    for child in parent.children(recursive=True):
                        try:
                            rss += child.memory_info().rss
                        except psutil.NoSuchProcess:
                            pass
                    if rss > limits.max_worker_memory_bytes:
                        failure = error('memory_limit', 'Budget mémoire surveillé dépassé ; processus arrêté.')
                except psutil.NoSuchProcess:
                    pass
                if failure:
                    _stop(process)
                    break
                sleep(.02)
        finally:
            if process.poll() is None:
                _stop(process)
        if process.returncode and failure is None:
            failure = error('worker_failed', 'Le processus de conversion s’est terminé anormalement.')
    return failure, monotonic() - start


def convert_ingestion(manifest_path, output_dir=None, *, file_ids=None, options=None, limits=None):
    """Convertir les PDF/DOCX ready + eligible d'une ingestion terminée.

    Retourne le manifeste de conversion + run_directory/manifest_path absolus
    (ces deux derniers ne sont pas persistés). Chaque document a son MD et JSON.
    Entrées non conformes : ConversionInputError/ValueError, sans lancement OCR.
    Erreurs documentaires : statuts explicites et sorties partielles conservées.
    Voir README.md pour les limites et la politique OCR automatique par défaut.
    """
    from .worker import initial_document, export
    started = monotonic()
    options = ConversionOptions() if options is None else options
    limits = ConversionLimits() if limits is None else limits
    if not isinstance(options, ConversionOptions) or not isinstance(limits, ConversionLimits):
        raise TypeError('Utiliser ConversionOptions et ConversionLimits.')
    options.validate(); limits.validate()
    path, manifest, items, digest = validate_manifest(manifest_path, limits, file_ids)
    # Valider les chemins de réutilisation AVANT de créer les sorties.
    for cached in options.ocr_results:
        confined(cached)
    base = confined(output_dir if output_dir is not None else ROOT / 'outputs/conversion', must_exist=False)
    # Ne jamais écrire dans les artefacts T23 ni dans les packages sources.
    if base == path.parent or base.is_relative_to(path.parent):
        raise ValueError('La conversion doit être séparée de son ingestion source.')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ') + '_' + uuid4().hex[:8]
    folder = base / run_id
    folder.mkdir(parents=True, exist_ok=False)
    result = {'schema_version': 'p2.conversion.v1', 'run_id': run_id, 'status': 'processing',
              'human_validated': False, 'source_manifest': relative(path), 'source_manifest_sha256': digest,
              'ingestion_run_id': manifest['run_id'], 'documents': [], 'errors': [],
              'execution_seconds': 0.0}
    write_json(folder / 'manifest.json', result, limits.max_output_bytes)
    for item in items:
        destination = folder / 'documents' / item['file_id']
        destination.mkdir(parents=True)
        initial = initial_document(item, manifest, path, digest, options)
        export(destination, initial, limits)
        request = {'manifest_path': str(path), 'document_directory': str(destination),
                   'options': asdict(options), 'limits': asdict(limits), 'initial_document': initial}
        request_path = destination / 'request.json'
        write_json(request_path, request, limits.max_manifest_bytes)
        failure, seconds = _run(request_path, destination, limits)
        try:
            document, _ = load_json(destination / 'document.json', limits.max_output_bytes)
        except (OSError, ValueError):
            document = initial
            failure = failure or error('result_incomplete', 'Sortie JSON absente ou illisible.')
        if failure or document['status'] == 'processing':
            document['errors'].append(failure or error('worker_incomplete', 'Conversion sans statut final.'))
            document['status'] = 'partial' if document['blocks'] else 'failed'
            document['execution_seconds'] = seconds
            export(destination, document, limits)
        result['documents'].append({'document_id': item['file_id'], 'status': document['status'],
                                    'source_file_id': item['file_id'], 'execution_seconds': seconds,
                                    'markdown': f"documents/{item['file_id']}/document.md",
                                    'json': f"documents/{item['file_id']}/document.json",
                                    'errors': document['errors'], 'warnings': document['warnings']})
        write_json(folder / 'manifest.json', result, limits.max_output_bytes)
    statuses = {d['status'] for d in result['documents']}
    result['status'] = ('failed' if statuses <= {'failed', 'rejected'} else 'partial'
                        if statuses & {'failed', 'rejected', 'partial'} else 'completed_with_review'
                        if 'completed_with_review' in statuses else 'completed')
    result['execution_seconds'] = monotonic() - started
    write_json(folder / 'manifest.json', result, limits.max_output_bytes)
    return {**result, 'run_directory': str(folder), 'manifest_path': str(folder / 'manifest.json')}


def convert_document(manifest_path, file_id, output_dir=None, *, options=None, limits=None):
    """Même contrat de contrôle ; retourne le document choisi + chemins runtime."""
    result = convert_ingestion(manifest_path, output_dir, file_ids=[file_id], options=options, limits=limits)
    folder = Path(result['run_directory'])
    item = result['documents'][0]
    document, _ = load_json(folder / item['json'], (limits or ConversionLimits()).max_output_bytes)
    return {**document, 'run_directory': str(folder), 'manifest_path': result['manifest_path'],
            'document_json_path': str(folder / item['json']), 'markdown_path': str(folder / item['markdown'])}
