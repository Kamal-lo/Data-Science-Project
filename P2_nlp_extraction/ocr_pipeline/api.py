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
from .quality import QUALITY_POLICY
from .resources import LinuxContainerGuard, WindowsJob, ResourceProtectionError


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


def _native_diagnostics(exit_code, log_tail, *, supervisor_terminated=False, observed_exit_code=None):
    """Report independent evidence; a memory alert does not prove crash causality."""
    code = observed_exit_code if observed_exit_code is not None else (None if supervisor_terminated else exit_code)
    evidence = []
    if isinstance(code, int) and code & 0xffffffff == 0xc0000005:
        evidence.append('windows_exception_exit_code')
    if 'Windows fatal exception: access violation' in log_tail:
        evidence.append('faulthandler_log')
    return {'access_violation_reported': bool(evidence), 'evidence': evidence,
            'exit_code_before_supervisor_termination': observed_exit_code,
            'final_exit_code': exit_code, 'supervisor_terminated': supervisor_terminated,
            'memory_crash_causality': 'not_established'}


def _log_tail(path):
    with path.open('rb') as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - 65536))
        return stream.read().decode('utf-8', errors='replace')


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
    record['status'] = ('needs_review' if record.get('blocks') and record.get('fallback_interruption') else 'error')
    record.setdefault('errors', []).append({'stage': 'worker', 'type': 'WorkerFailure', 'message': message})
    return record


def _interrupted_page(record, reason):
    """Enrich a durable checkpoint; never replace saved primary hypotheses."""
    pending = record.pop('fallback_in_progress', None)
    if pending:
        now = monotonic()
        elapsed = max(0, pending['remaining_seconds'] + now - pending['deadline_monotonic'])
        diagnostic = dict(pending, interruption=reason, outcome='interrupted_no_result',
                          elapsed_seconds=elapsed,
                          deadline_overrun_seconds=max(0, now-pending['deadline_monotonic']))
        record['fallback_interruption'] = diagnostic
        record.setdefault('fallback', {})['interrupted_attempt_seconds'] = elapsed
        record.setdefault('warnings', []).append({'code': reason, 'partial_page': True})
        for block in record['blocks']:
            if block['block_id'] == pending.get('block_id'):
                block['fallback_attempted'] = True
                block['fallback_skipped_reason'] = reason
                block['needs_review'] = True
                block.setdefault('warnings', []).append(reason)
                block['recognition_attempts'].append({'variant': 'contrast_grayscale', 'result': None,
                    'errors': [{'stage': 'fallback', 'type': reason, 'message': 'Worker interrupted by supervisor.'}]})
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
                page_timeout_seconds=240, initialization_timeout_seconds=120, max_pixels=60_000_000,
                fallback_mode='preprocess', max_fallback_blocks=8, fallback_timeout_seconds=20,
                max_worker_memory_bytes=1536 * 1024**2, detector_max_side=None):
    """Extraire un PDF sans zone manuelle. Numéros de pages à partir de 1.

    Chaque appel crée un dossier unique sous output_dir, qui doit rester dans P2.
    pages=None traite toutes les pages ; utiliser pages=[1, 2] pour un essai court.
    Les langues sont des hypothèses heuristiques, jamais des références validées.
    Les cas indéterminés n’ont pas de texte arbitrairement sélectionné.
    """
    start = monotonic()
    if detector_max_side is not None and (type(detector_max_side) is not int or not 32 <= detector_max_side <= 4000):
        raise ValueError("detector_max_side: entier entre 32 et 4000, ou None.")
    if dpi not in (200, 300) or arabic_spacing not in ('off', 'suggest') or on_error not in ('continue', 'raise'):
        raise ValueError('dpi=200/300 ; arabic_spacing=off/suggest ; on_error=continue/raise.')
    if fallback_mode not in ('off', 'preprocess'):
        raise ValueError('fallback_mode doit être off ou preprocess.')
    if type(max_fallback_blocks) is not int or not 0 <= max_fallback_blocks <= 64:
        raise ValueError('max_fallback_blocks doit être compris entre 0 et 64.')
    if isinstance(fallback_timeout_seconds, bool) or not isinstance(fallback_timeout_seconds, (int, float)) or not math.isfinite(fallback_timeout_seconds) or fallback_timeout_seconds <= 0:
        raise ValueError('fallback_timeout_seconds doit être positif et fini.')
    for value in (timeout_seconds, page_timeout_seconds, initialization_timeout_seconds):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('Les délais doivent être positifs et finis.')
    if not isinstance(cpu_threads, int) or not 1 <= cpu_threads <= 64 or not isinstance(max_pixels, int) or max_pixels < 1:
        raise ValueError('cpu_threads ou max_pixels invalide.')
    if type(max_worker_memory_bytes) is not int or max_worker_memory_bytes < 1:
        raise ValueError('max_worker_memory_bytes doit être un entier positif.')
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
    worker_env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    if os.name == 'nt':
        # Paddle 3.2.2 initialise son cache de datasets via expanduser("~"),
        # même pour les prédicteurs locaux. Isoler le profil du seul worker.
        worker_env['USERPROFILE'] = str(local_path(ROOT / '.cache'))
    collected, remaining, attempts, infrastructure_errors = {}, selected[:], [], []
    while remaining:
        if monotonic()-start >= timeout_seconds:
            for number in remaining:
                collected[number] = _failure(number, 'Document timeout avant traitement de cette page.')
            break
        request = {'pdf_path': str(pdf), 'run_dir': str(folder), 'pages': remaining[:], 'dpi': dpi,
                   'arabic_spacing': arabic_spacing, 'on_error': on_error, 'cpu_threads': cpu_threads,
                   'max_pixels': max_pixels, 'fallback_mode': fallback_mode,
                   'max_fallback_blocks': max_fallback_blocks,
                   'fallback_timeout_seconds': min(fallback_timeout_seconds, page_timeout_seconds),
                   'resource_job_name': 'Local\\p2_ocr_' + uuid.uuid4().hex,
                   'max_worker_memory_bytes': max_worker_memory_bytes}
        if detector_max_side is not None:
            request['detector_max_side'] = detector_max_side
        attempt = len(attempts)+1
        request_path = folder/f'request_{attempt}.json'
        write_json(request_path, request)
        # A restarted worker must not inherit the preceding page's expired deadline.
        write_json(folder/'progress.json', {'phase': 'starting', 'page': None})
        phase_start, previous_phase = monotonic(), None
        page_started, active_page = None, None
        reason, progress = None, {}
        supervisor_terminated, observed_exit_code = False, None
        try:
            guard = (LinuxContainerGuard(max_worker_memory_bytes) if sys.platform == 'linux'
                     else WindowsJob(request['resource_job_name'], max_worker_memory_bytes))
        except ResourceProtectionError as exc:
            diagnostic = {'stage': 'resource_guard', 'type': type(exc).__name__, 'message': str(exc)}
            infrastructure_errors.append(diagnostic)
            write_json(folder/'resource_guard_failure.json', diagnostic)
            for number in remaining:
                collected[number] = _failure(number, str(exc))
            break
        with guard as job, \
                (folder/f'worker_{attempt}.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, '-B', '-X', 'utf8', '-X', 'faulthandler',
                                        '-m', 'P2_nlp_extraction.ocr_pipeline.worker', '--request', str(request_path)],
                                       cwd=ROOT.parent, stdout=log, stderr=subprocess.STDOUT,
                                       env=worker_env, start_new_session=sys.platform == 'linux')
            if sys.platform == 'linux':
                job.process = process
            try:
                while process.poll() is None:
                    progress = _read(folder/'progress.json', progress)
                    phase = (progress.get('phase'), progress.get('page'))
                    if phase[1] != active_page:
                        active_page, page_started = phase[1], monotonic()
                    if phase != previous_phase:
                        phase_start, previous_phase = monotonic(), phase
                    elapsed = monotonic()-phase_start
                    resources = job.snapshot()
                    if resources['memory_limit_hit']:
                        reason = 'memory_limit'
                    elif monotonic()-start > timeout_seconds:
                        reason = 'document_timeout'
                    elif phase[0] in (None, 'starting', 'initializing') and elapsed > initialization_timeout_seconds:
                        reason = 'initialization_timeout'
                    elif phase[0] == 'fallback' and monotonic() >= progress['fallback_deadline']:
                        reason = 'fallback_timeout'
                    elif phase[0] in ('page', 'fallback') and page_started is not None and monotonic()-page_started > page_timeout_seconds:
                        reason = 'page_timeout'
                    if reason:
                        observed_exit_code = process.poll()
                        if observed_exit_code is None:
                            supervisor_terminated = True
                            job.terminate()
                            _stop(process)
                        break
                    sleep(.02)
            finally:
                # Une interruption de l’appelant ne doit pas laisser un worker OCR orphelin.
                if process.poll() is None:
                    supervisor_terminated = True
                    job.terminate()
                    _stop(process)
            resources = job.snapshot()
            if resources['memory_limit_hit']:
                reason = 'memory_limit'
            elif resources.get('container_oom_kills') and process.returncode == -9:
                reason = 'container_oom'
        native = _native_diagnostics(process.returncode, _log_tail(folder/f'worker_{attempt}.log'),
                                     supervisor_terminated=supervisor_terminated,
                                     observed_exit_code=observed_exit_code)
        attempts.append({'attempt': attempt, 'exit_code': process.returncode, 'interruption': reason,
                         'resources': resources, 'native_diagnostics': native})
        if reason:
            infrastructure_errors.append({'stage': 'supervisor', 'type': reason,
                                          'message': 'OCR worker tree interrupted; saved checkpoints retained.'})
        if native['access_violation_reported']:
            infrastructure_errors.append({'stage': 'native', 'type': 'NativeAccessViolation',
                'message': 'Access violation reported independently of resource notifications; see worker log.',
                'diagnostics': native})
        progress = _read(folder/'progress.json', progress)
        fatal = _read(folder/'fatal_error.json')
        for number in remaining:
            page = _read(folder/'pages'/f'page_{number:03d}.json')
            if page and page.get('status') != 'processing':
                collected[number] = page
        active = progress.get('page')
        if active in remaining and active not in collected:
            partial = _read(folder/'pages'/f'page_{active:03d}.json')
            if partial:
                partial = _interrupted_page(partial, reason or 'worker_failed')
            collected[active] = _failure(active, reason or f'Arrêt natif, code {process.returncode}', partial)
            if native['access_violation_reported']:
                collected[active]['errors'].append({'stage': 'native', 'type': 'NativeAccessViolation',
                                                    'message': 'See native_diagnostics and worker log.'})
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
              'status': 'failed' if all(p['status'] == 'error' for p in records) else 'partial' if errors or infrastructure_errors else
                        'completed_with_review' if any(p['status'] != 'ok' for p in records) else 'completed',
              'pages': records, 'model_metadata': _read(folder/'models.json'),
              'routing_rules': RULES, 'routing_calibrated': False,
              'quality_policy': QUALITY_POLICY,
              'fallback_policy': {'mode': fallback_mode, 'max_blocks_per_page': max_fallback_blocks,
                                  'timeout_seconds_per_page': min(fallback_timeout_seconds, page_timeout_seconds),
                                  'max_detection_retries': 1, 'new_models': False,
                                  'deadline_enforcement': 'supervisor_terminates_worker_tree',
                                  'timeout_result': 'partial_page_primary_checkpoint_preserved'},
              'resource_policy': {'memory_limit_bytes': max_worker_memory_bytes,
                                  'mechanism': 'linux_cgroup_v2_and_process_group' if sys.platform == 'linux' else 'windows_job_object',
                                  'memory_metric': 'sampled_tree_pss_bytes' if sys.platform == 'linux' else 'job_private_commit_bytes',
                                  'supervisor_poll_seconds': .02},
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
