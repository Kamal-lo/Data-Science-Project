"""API publique sans import de Paddle dans le processus appelant."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep
import uuid

from ..scripts.ocr_common import ROOT, local_path, sha256, write_json
from .routing import RULES


class OCRPipelineError(RuntimeError):
    """Échec avec résultats partiels disponibles via l’attribut result."""
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def _read(path, fallback=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def _stop(process):
    import psutil
    try:
        children = psutil.Process(process.pid).children(recursive=True)
        for child in reversed(children):
            try:
                if child.name().lower() != 'conhost.exe':
                    child.kill()
            except psutil.NoSuchProcess:
                pass
        process.kill()
    except (psutil.NoSuchProcess, ProcessLookupError):
        pass
    process.wait(timeout=15)


def _failure(number, message, previous=None):
    record = previous or {'page': number, 'blocks': [], 'warnings': [], 'timings': {}}
    record['status'] = 'error'
    record.setdefault('errors', []).append({'stage': 'worker', 'type': 'WorkerFailure', 'message': message})
    return record


def _export(folder, result):
    raw_pages, suggestion_pages, hypotheses = [], [], []
    for page in result['pages']:
        raw, suggestions = [], []
        for block in page['blocks']:
            raw_line = block['raw_text'] if block['raw_text'] is not None else f'[{block["block_id"]}: indéterminé, hypothèses dans JSON]'
            proposal = block.get('arabic_spacing_proposal') or {}
            raw.append(raw_line)
            suggestions.append(proposal['proposed_text'] if proposal.get('accepted') else raw_line)
            hypotheses.append(f'[{block["block_id"]}]\n'+ '\n'.join(
                f'[{lang}] {value["text"]}' for lang, value in block['recognition_candidates'].items()))
        page['raw_text'] = '\n'.join(raw)
        page['text_with_spacing_proposals'] = '\n'.join(suggestions)
        heading = f'=== PAGE {page["page"]} — {page["status"]} ===\n'
        raw_pages.append(heading+page['raw_text'])
        suggestion_pages.append(heading+page['text_with_spacing_proposals'])
    result['exports'] = {key: str(folder/name) for key, name in
                         [('json', 'document.json'), ('raw_txt', 'document_raw.txt'),
                          ('spacing_txt', 'document_spacing_proposals.txt'), ('hypotheses_txt', 'recognition_candidates.txt')]}
    write_json(folder/'document.json', result)
    for name, value in [('document_raw.txt', '\n\n'.join(raw_pages)),
                        ('document_spacing_proposals.txt', '\n\n'.join(suggestion_pages)),
                        ('recognition_candidates.txt', '\n\n'.join(hypotheses))]:
        (folder/name).write_text(value, encoding='utf-8')


def extract_pdf(pdf_path, output_dir=None, *, pages=None, dpi=200, arabic_spacing='suggest',
                on_error='continue', cpu_threads=4, timeout_seconds=600,
                page_timeout_seconds=240, initialization_timeout_seconds=120, max_pixels=60_000_000):
    """Extraire un PDF sans zone manuelle. Numéros de pages à partir de 1.

    Chaque appel crée un dossier unique sous output_dir, qui doit rester dans P2.
    pages=None traite toutes les pages ; utiliser pages=[1, 2] pour un essai court.
    Les langues sont des hypothèses heuristiques, jamais des références validées.
    Les cas indéterminés n’ont pas de texte arbitrairement sélectionné.
    """
    start = monotonic()
    if dpi not in (200, 300) or arabic_spacing not in ('off', 'suggest') or on_error not in ('continue', 'raise'):
        raise ValueError('dpi=200/300 ; arabic_spacing=off/suggest ; on_error=continue/raise.')
    for value in (timeout_seconds, page_timeout_seconds, initialization_timeout_seconds):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('Les délais doivent être positifs et finis.')
    if not isinstance(cpu_threads, int) or not 1 <= cpu_threads <= 64 or not isinstance(max_pixels, int) or max_pixels < 1:
        raise ValueError('cpu_threads ou max_pixels invalide.')
    pdf = Path(pdf_path).resolve(strict=True)
    import pymupdf
    with pymupdf.open(pdf) as document:
        if not document.is_pdf:
            raise ValueError('Un PDF est requis.')
        if document.needs_pass:
            raise ValueError('PDF protégé par mot de passe ; aucune extraction lancée.')
        count = len(document)
    selected = list(range(1, count+1)) if pages is None else list(pages)
    if not selected or any(type(p) is not int or not 1 <= p <= count for p in selected) or len(selected) != len(set(selected)):
        raise ValueError('Sélection non vide de pages uniques, entre 1 et le nombre de pages.')
    selected.sort()
    base = local_path(output_dir if output_dir is not None else ROOT/'outputs/ocr/automatic')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')+'_'+uuid.uuid4().hex[:8]
    folder = base/run_id
    folder.mkdir(parents=True, exist_ok=False)
    digest = sha256(pdf)
    collected, remaining, attempts, infrastructure_errors = {}, selected[:], [], []
    while remaining:
        if monotonic()-start >= timeout_seconds:
            for number in remaining:
                collected[number] = _failure(number, 'Document timeout avant traitement de cette page.')
            break
        request = {'pdf_path': str(pdf), 'run_dir': str(folder), 'pages': remaining[:], 'dpi': dpi,
                   'arabic_spacing': arabic_spacing, 'on_error': on_error, 'cpu_threads': cpu_threads,
                   'max_pixels': max_pixels}
        attempt = len(attempts)+1
        request_path = folder/f'request_{attempt}.json'
        write_json(request_path, request)
        phase_start, previous_phase = monotonic(), None
        reason, progress = None, {}
        with (folder/f'worker_{attempt}.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, '-B', '-X', 'utf8', '-X', 'faulthandler',
                                        '-m', 'P2_nlp_extraction.ocr_pipeline.worker', '--request', str(request_path)],
                                       cwd=ROOT.parent, stdout=log, stderr=subprocess.STDOUT,
                                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            try:
                while process.poll() is None:
                    progress = _read(folder/'progress.json', {})
                    phase = (progress.get('phase'), progress.get('page'))
                    if phase != previous_phase:
                        phase_start, previous_phase = monotonic(), phase
                    elapsed = monotonic()-phase_start
                    if monotonic()-start > timeout_seconds:
                        reason = 'document_timeout'
                    elif phase[0] == 'initializing' and elapsed > initialization_timeout_seconds:
                        reason = 'initialization_timeout'
                    elif phase[0] == 'page' and elapsed > page_timeout_seconds:
                        reason = 'page_timeout'
                    if reason:
                        _stop(process)
                        break
                    sleep(.2)
            finally:
                # Une interruption de l’appelant ne doit pas laisser un worker OCR orphelin.
                if process.poll() is None:
                    _stop(process)
        attempts.append({'attempt': attempt, 'exit_code': process.returncode, 'interruption': reason})
        progress = _read(folder/'progress.json', progress)
        fatal = _read(folder/'fatal_error.json')
        for number in remaining:
            page = _read(folder/'pages'/f'page_{number:03d}.json')
            if page and page.get('status') != 'processing':
                collected[number] = page
        active = progress.get('page')
        if active in remaining and active not in collected:
            partial = _read(folder/'pages'/f'page_{active:03d}.json')
            collected[active] = _failure(active, reason or f'Arrêt natif, code {process.returncode}', partial)
            write_json(folder/'pages'/f'page_{active:03d}.json', collected[active])
        pending = [p for p in remaining if p not in collected]
        if fatal or reason in ('document_timeout', 'initialization_timeout') or progress.get('phase') == 'initializing':
            infrastructure_errors.append(fatal or {'stage': 'worker', 'message': reason or 'initialization_failed'})
            for number in pending:
                collected[number] = _failure(number, str(infrastructure_errors[-1]))
            break
        if on_error == 'raise' and any(p['errors'] for p in collected.values()):
            for number in pending:
                collected[number] = _failure(number, 'Non traitée après échec, on_error=raise.')
            break
        if pending == remaining:
            for number in pending:
                collected[number] = _failure(number, f'Worker sans résultat, code {process.returncode}.')
            break
        remaining = pending
    records = [collected[number] for number in selected]
    errors = sum(bool(p.get('errors')) for p in records)
    result = {'schema_version': 'p2.automatic_ocr.v1', 'run_id': run_id, 'source_pdf': str(pdf),
              'pdf_sha256': digest, 'source_page_count': count, 'selected_pages': selected,
              'status': 'failed' if all(p['status'] == 'error' for p in records) else 'partial' if errors else
                        'completed_with_review' if any(p['status'] != 'ok' for p in records) else 'completed',
              'pages': records, 'model_metadata': _read(folder/'models.json'),
              'routing_rules': RULES, 'routing_calibrated': False,
              'coordinate_system': 'rendered_image_pixels_top_left_origin; PDF points also provided',
              'attempts': attempts, 'errors': infrastructure_errors,
              'arabic_cer_wer': None, 'human_ground_truth_validated': False,
              'execution_seconds': monotonic()-start, 'run_directory': str(folder)}
    if sha256(pdf) != digest:
        result['status'] = 'failed'
        result['errors'].append({'stage': 'integrity', 'message': 'PDF modifié pendant extraction.'})
    _export(folder, result)
    if on_error == 'raise' and (errors or result['errors']):
        raise OCRPipelineError('Extraction en échec ; résultats partiels enregistrés.', result)
    return result
