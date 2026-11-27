"""Frontière T23/T24 : validation du contrat, confinement et empreintes."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from ..scripts.ocr_common import ROOT
from ..document_ingestion.safety import safe_relative
from ..document_ingestion.models import IngestionLimits
from .models import ConversionInputError, ConversionFailure


def confined(path, *, must_exist=True):
    """Tous les chemins T24 restent dans P2 ; refuse liens ET jonctions Windows."""
    path = Path(path).absolute()
    if not path.is_relative_to(ROOT):
        raise ConversionInputError('Chemin hors du module P2.')
    cursor = ROOT
    for part in path.relative_to(ROOT).parts:
        if part in ('.', '..'):
            raise ConversionInputError('Chemin non canonique.')
        cursor = cursor / part
        if cursor.is_symlink() or (hasattr(cursor, 'is_junction') and cursor.is_junction()):
            raise ConversionInputError('Lien symbolique ou jonction interdit.')
    resolved = path.resolve(strict=must_exist)
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ConversionInputError('Chemin résolu hors de P2.')
    return resolved


def relative(path):
    return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()


def load_json(path, limit):
    path = confined(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ConversionInputError('JSON absent ou trop volumineux.')
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ConversionInputError('JSON trop volumineux.')
    def unique_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Clé JSON dupliquée.')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nombre JSON non fini.')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ConversionInputError('JSON mal formé ou ambigu.') from exc
    return value, hashlib.sha256(raw).hexdigest()


def artifact_path(run, item):
    value = item.get('artifact_path')
    rel = item.get('relative_path')
    if not isinstance(value, str) or not isinstance(rel, str) or '\\' in value or '\\' in rel:
        raise ConversionInputError('Chemin de fichier non canonique.')
    try:
        clean = safe_relative(rel, IngestionLimits())
    except Exception as exc:
        raise ConversionInputError('Chemin relatif dangereux.') from exc
    if str(clean) != rel or value != 'files/' + rel or PurePosixPath(value).is_absolute():
        raise ConversionInputError('Chemin T23 incohérent ou dangereux.')
    candidate = confined(run / value)
    if not candidate.is_relative_to((run / 'files').resolve()) or not candidate.is_file():
        raise ConversionInputError('Artefact hors du dossier files ou absent.')
    return candidate


def admissible(item):
    return (item.get('status') == 'ready' and item.get('eligible_for_t24') is True
            and item.get('detected_type') in ('pdf', 'docx'))


def validate_manifest(path, limits, file_ids=None):
    from jsonschema import Draft202012Validator
    path = confined(path)
    if path.name != 'manifest.json':
        raise ConversionInputError('Le manifeste doit être le manifest.json d’une ingestion T23.')
    manifest, digest = load_json(path, limits.max_manifest_bytes)
    schema = json.loads((ROOT / 'config/ingestion_manifest.schema.json').read_text(encoding='utf-8'))
    issue = next(Draft202012Validator(schema).iter_errors(manifest), None)
    if issue:
        raise ConversionInputError('Manifeste non conforme au schéma T23 : ' + issue.validator)
    if manifest['status'] not in ('completed', 'completed_with_issues') or not manifest['eligible_for_t24']:
        raise ConversionInputError('Ingestion non terminée ou sans fichier admissible.')
    if manifest['run_id'] != path.parent.name:
        raise ConversionInputError('Identifiant et répertoire d’ingestion incohérents.')
    items = {f['file_id']: f for f in manifest['files']}
    if len(items) != len(manifest['files']):
        raise ConversionInputError('Identifiants de fichiers dupliqués.')
    if file_ids is not None:
        if isinstance(file_ids, (str, bytes)) or not file_ids or len(set(file_ids)) != len(file_ids):
            raise ConversionInputError('file_ids doit être une séquence non vide et sans doublons.')
        if any(i not in items or not admissible(items[i]) for i in file_ids):
            raise ConversionInputError('Un identifiant demandé est absent ou non admissible.')
        selected = [items[i] for i in file_ids]
    else:
        selected = [f for f in manifest['files'] if admissible(f)]
    if not selected or len(selected) > limits.max_documents:
        raise ConversionInputError('Aucun fichier admissible ou trop de documents.')
    paths = set()
    for item in selected:
        if not re.fullmatch(r'f[0-9]{6,}', item['file_id']):
            raise ConversionInputError('Identifiant de fichier invalide.')
        candidate = artifact_path(path.parent, item)
        key = str(candidate).casefold()
        if key in paths:
            raise ConversionInputError('Plusieurs identifiants désignent le même artefact.')
        paths.add(key)
    return path, manifest, selected, digest


def snapshot(source, target, item, limits, budget):
    """Copie privée vérifiée avant parsing ; ne convertit jamais directement l'original."""
    if item['size_bytes'] > limits.max_source_bytes:
        raise ConversionFailure('source_size_limit', 'Source trop volumineuse.')
    source = confined(source)
    before = source.stat()
    digest, count = hashlib.sha256(), 0
    with source.open('rb') as reader, target.open('xb') as writer:
        while data := reader.read(1024 * 1024):
            budget.tick()
            count += len(data)
            if count > limits.max_source_bytes or count > item['size_bytes']:
                raise ConversionFailure('source_size_mismatch', 'Taille réelle incompatible avec le manifeste.')
            digest.update(data)
            writer.write(data)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or count != item['size_bytes'] or digest.hexdigest() != item['sha256']:
        raise ConversionFailure('source_integrity_mismatch', 'Taille ou SHA-256 modifié depuis T23.')
