"""Conventions communes : chemins P2, sorties UTF-8 et mesures traçables."""
from __future__ import annotations

import hashlib
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = ROOT / 'data/pdf/test_dce.pdf'
DEFAULT_OUTPUT = ROOT / 'outputs/ocr'


def local_path(path: str | Path) -> Path:
    """Interdire toute écriture hors P2, y compris via un lien symbolique."""
    result = Path(path).resolve()
    if not result.is_relative_to(ROOT):
        raise ValueError(f'La destination doit rester dans {ROOT}: {result}')
    return result


def write_json(path: Path, value: object) -> None:
    path = local_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def configure_cache() -> None:
    """Les téléchargements des modèles restent dans P2, sans changer HOME."""
    cache = ROOT / '.cache'
    for key, folder in {
        'PADDLE_PDX_CACHE_HOME': 'paddlex',
        'PADDLE_HOME': 'paddle',
        'HF_HOME': 'huggingface',
        'MODELSCOPE_CACHE': 'modelscope',
    }.items():
        target = cache / folder
        target.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(target)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')


def error_details(exc: Exception) -> dict:
    return {'type': type(exc).__name__, 'message': str(exc),
            'traceback': traceback.format_exc()}


def reading_order(blocks: list[dict], right_to_left: bool = False) -> list[dict]:
    """Ordre géométrique par lignes puis abscisse ; pas de reconstruction de tableau.

    Les coordonnées et l'ordre natif sont conservés dans les résultats. Une page
    multicolonne complexe nécessite une vérification humaine.
    """
    pending = sorted(blocks, key=lambda b: (b['bbox'][1], b['bbox'][0]))
    rows: list[list[dict]] = []
    for block in pending:
        y = (block['bbox'][1] + block['bbox'][3]) / 2
        height = max(1, block['bbox'][3] - block['bbox'][1])
        if rows:
            anchor = rows[-1][0]['bbox']
            center = (anchor[1] + anchor[3]) / 2
            if abs(y - center) <= 0.5 * min(height, max(1, anchor[3] - anchor[1])):
                rows[-1].append(block)
                continue
        rows.append([block])
    return [block for row in rows for block in
            sorted(row, key=lambda b: b['bbox'][0], reverse=right_to_left)]


def save_page(folder: Path, page: int, result: dict) -> None:
    folder = local_path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f'page_{page:03d}'
    (folder / f'{stem}.txt').write_text(result['text'], encoding='utf-8')
    write_json(folder / f'{stem}.json', result)
