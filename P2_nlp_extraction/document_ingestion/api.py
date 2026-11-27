"""API publique T23 : processus borné et résultat JSON, sans chargement de Paddle."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import stat
import subprocess
import sys
from time import monotonic, sleep
import uuid

from ..scripts.ocr_common import ROOT, local_path, write_json
from .models import IngestionLimits


def _stop(process):
    import psutil
    try:
        tree = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        tree = []
    for child in reversed(tree):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def ingest_path(source_path, output_dir=None, *, dce_id=None, limits=None):
    """Préparer un fichier local ou ZIP pour T24, sans conversion ni OCR.

    Les sorties restent dans P2. Les refus documentaires sont retournés dans le
    manifeste ; les entrées/options invalides lèvent une exception. Aucun poids
    Paddle ni accès réseau n'est nécessaire. Voir document_ingestion/README.md.
    """
    from .worker import initial_result, revoke
    start = monotonic()
    limits = IngestionLimits() if limits is None else limits
    if not isinstance(limits, IngestionLimits):
        raise TypeError('limits doit être une IngestionLimits.')
    limits.validate()
    if dce_id is not None and (not isinstance(dce_id, str) or not dce_id.strip() or len(dce_id) > 200):
        raise ValueError('dce_id doit être une chaîne non vide de 200 caractères maximum.')
    source = Path(source_path).absolute()
    mode = source.lstat().st_mode
    if not stat.S_ISREG(mode) or source.is_symlink() or source.is_junction():
        raise ValueError('La source doit être un fichier régulier, sans lien.')
    source = source.resolve(strict=True)
    base = local_path(output_dir if output_dir is not None else ROOT/'outputs/ingestion')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')+'_'+uuid.uuid4().hex[:8]
    folder = base/run_id
    folder.mkdir(parents=True, exist_ok=False)
    request = {'source_path': str(source), 'source_name': source.name, 'run_directory': str(folder),
               'limits': asdict(limits), 'dce_id': dce_id}
    request_path = folder/'request.json'
    write_json(request_path, request)
    result = initial_result(run_id, source.name, dce_id, limits)
    write_json(folder/'manifest.json', result)
    reason = None
    if source.stat().st_size > limits.max_source_bytes:
        reason = ('source_size_limit', 'Source trop volumineuse.', 'rejected')
    else:
        import psutil
        with (folder/'worker.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, '-B', '-X', 'utf8', '-m',
                                        'P2_nlp_extraction.document_ingestion.worker', '--request', str(request_path)],
                                       cwd=ROOT.parent, stdout=log, stderr=subprocess.STDOUT,
                                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            try:
                while process.poll() is None:
                    if monotonic()-start > limits.timeout_seconds:
                        reason = ('timeout', 'Délai maximal dépassé, worker arrêté.', 'rejected')
                    else:
                        try:
                            parent = psutil.Process(process.pid)
                            rss = parent.memory_info().rss
                            for child in parent.children(recursive=True):
                                try:
                                    rss += child.memory_info().rss
                                except psutil.NoSuchProcess:
                                    pass
                            if rss > limits.max_worker_memory_bytes:
                                reason = ('memory_limit', 'Budget mémoire surveillé dépassé.', 'rejected')
                        except psutil.NoSuchProcess:
                            pass
                    if reason:
                        _stop(process)
                        break
                    sleep(.02)
            finally:
                if process.poll() is None:
                    _stop(process)
            if process.returncode and reason is None:
                reason = ('worker_failed', 'Worker terminé anormalement.', 'failed')
    try:
        result = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        reason = reason or ('manifest_incomplete', 'Manifeste incomplet.', 'failed')
    if reason or result.get('status') == 'processing':
        code, message, status = reason or ('worker_incomplete', 'Worker sans résultat final.', 'failed')
        revoke(result, code, message, status)
    result['execution_seconds'] = monotonic()-start
    write_json(folder/'manifest.json', result)
    # Chemins absolus utiles au programme appelant, absents du manifeste portable.
    return {**result, 'run_directory': str(folder), 'manifest_path': str(folder/'manifest.json')}
