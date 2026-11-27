"""Worker T23 isolé. Ses entrées proviennent uniquement de l'API locale."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
from time import sleep

from ..scripts.ocr_common import local_path, write_json
from .detection import detect_file
from .models import Budget, IngestionFailure, IngestionLimits
from .safety import confined_destination, safe_relative
from .zip_extraction import checked_zip, read_member


def initial_result(run_id, name, dce_id, limits):
    return {'schema_version': 'p2.ingestion.v1', 'run_id': run_id, 'dce_id': dce_id,
            'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'processing',
            'eligible_for_t24': False, 'source': {'name': name, 'detected_type': None,
            'sha256': None, 'size_bytes': None}, 'files': [], 'errors': [],
            'limits': asdict(limits), 'execution_seconds': 0, 'bytes_processed': 0}


def revoke(result, code, message, status='failed'):
    result['status'] = status
    result['eligible_for_t24'] = False
    result['errors'].append({'code': code, 'message': message})
    for item in result['files']:
        item['eligible_for_t24'] = False
        item['artifact_path'] = None
        if item['status'] == 'ready':
            item['status'] = 'not_published'
            item['reason'] = 'ingestion_not_completed'
    return result


def _copy_snapshot(source, target, budget):
    size, digest = 0, hashlib.sha256()
    if source.is_symlink() or source.is_junction():
        raise IngestionFailure('source_link', 'Les liens sources ne sont pas acceptés.')
    with source.open('rb') as stream, target.open('xb') as output:
        before = os.fstat(stream.fileno())
        while True:
            budget.tick()
            chunk = stream.read(min(64*1024, budget.limits.max_source_bytes-size+1))
            if not chunk:
                break
            size += len(chunk)
            if size > budget.limits.max_source_bytes:
                raise IngestionFailure('source_size_limit', 'Source trop volumineuse.')
            budget.consume(len(chunk)); digest.update(chunk); output.write(chunk)
        after = os.fstat(stream.fileno())
    if size != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise IngestionFailure('source_changed', 'Source modifiée pendant la lecture.', status='failed')
    return {'size_bytes': size, 'sha256': digest.hexdigest()}


def _record(relative, original, detection, digest, size, index, info=None):
    result = {'file_id': f'f{index:06d}', 'original_name': original, 'relative_path': relative,
              'artifact_path': None, 'declared_extension': Path(relative).suffix.casefold(),
              'size_bytes': size, 'sha256': digest, 'eligible_for_t24': False,
              'errors': [], **detection}
    if info is not None:
        result['zip_metadata'] = {'compressed_bytes': info.compress_size,
                                  'declared_bytes': info.file_size, 'compression_method': info.compress_type,
                                  'crc32': f'{info.CRC:08x}', 'flags': info.flag_bits,
                                  'modified_local': '%04d-%02d-%02dT%02d:%02d:%02d' % info.date_time,
                                  'timezone_known': False}
        if original.replace('\\', '/') != original:
            result['warnings'].append('path_separator_normalized')
    return result


def process_request(request):
    folder = local_path(request['run_directory'])
    limits = IngestionLimits(**request['limits']); limits.validate()
    budget = Budget(limits)
    source = Path(request['source_path'])
    result = initial_result(folder.name, request['source_name'], request['dce_id'], limits)
    staging = folder/'.staging'
    staging.mkdir(exist_ok=False)
    staged_files = staging/'files'; staged_files.mkdir()
    write_json(folder/'manifest.json', result)
    try:
        snapshot = staging/'source'
        result['source'].update(_copy_snapshot(source, snapshot, budget))
        if snapshot.stat().st_size > limits.max_file_bytes:
            raise IngestionFailure('file_size_limit', 'Fichier source supérieur à la limite par fichier.')
        detection = detect_file(snapshot, request['source_name'], budget)
        result['source']['detected_type'] = detection['detected_type']
        if detection['detected_type'] == 'zip':
            with checked_zip(snapshot, budget) as (archive, entries):
                for index, entry in enumerate(entries, 1):
                    budget.tick()
                    info, relative = entry['info'], entry['relative_path']
                    target = confined_destination(staged_files, relative)
                    if entry['is_directory']:
                        read_member(archive, info, budget)
                        target.mkdir(parents=True, exist_ok=True)
                        record = _record(relative, entry['original_name'],
                                         {'detected_type': 'directory', 'mime_type': None, 'status': 'directory',
                                          'reason': None, 'warnings': []}, None, 0, index, info)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open('xb') as output:
                            saved = read_member(archive, info, budget, destination=output)
                        found = detect_file(target, entry['original_name'], budget)
                        if found['detected_type'] == 'zip':
                            found.update(status='blocked', reason='nested_archive_not_allowed')
                            found['warnings'].append('nested_archive_not_extracted')
                        record = _record(relative, entry['original_name'], found, saved['sha256'], saved['size_bytes'], index, info)
                    result['files'].append(record)
                    write_json(folder/'manifest.json', result)
        else:
            relative = safe_relative(request['source_name'], limits)
            target = confined_destination(staged_files, relative)
            snapshot.rename(target)
            result['files'].append(_record(relative, request['source_name'], detection,
                                           result['source']['sha256'], result['source']['size_bytes'], 1))
        budget.tick()
        # Publication uniquement après le succès du traitement complet du conteneur.
        for attempt in range(11):
            try:
                staged_files.rename(folder/'files')
                break
            except PermissionError as exc:
                # Windows scanners can briefly hold a handle to the staged tree.
                if getattr(exc, 'winerror', None) not in (5, 32) or attempt == 10:
                    raise
                budget.tick()
                sleep(.02)
        for item in result['files']:
            item['artifact_path'] = 'files/'+item['relative_path']
            item['eligible_for_t24'] = item['status'] == 'ready' and item['detected_type'] in ('pdf', 'docx')
        issues = any(item['status'] not in ('ready', 'directory') for item in result['files'])
        result['status'] = 'completed_with_issues' if issues else 'completed'
        result['eligible_for_t24'] = any(item['eligible_for_t24'] for item in result['files'])
    except IngestionFailure as exc:
        revoke(result, exc.code, str(exc), exc.status)
    except OSError:
        revoke(result, 'io_error', 'Erreur de lecture ou écriture ; aucune publication autorisée.')
    except Exception as exc:
        # Ne pas exposer de chemin personnel ou de contenu documentaire dans une trace JSON.
        revoke(result, 'worker_error', f'Échec du worker ({type(exc).__name__}).')
    result['execution_seconds'] = budget.clock()-budget.started
    result['bytes_processed'] = budget.bytes_read
    write_json(folder/'manifest.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    request = json.loads(local_path(args.request).read_text(encoding='utf-8'))
    process_request(request)


if __name__ == '__main__':
    main()
