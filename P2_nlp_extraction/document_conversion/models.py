"""Contrats publics et budgets de conversion ; aucun chargement de modèle à l'import."""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from time import monotonic
from uuid import uuid4


@dataclass(frozen=True)
class ConversionOptions:
    ocr_mode: str = 'auto'  # auto, never, reuse_only
    pdf_pages: tuple[int, ...] | None = None  # indices physiques, à partir de 1
    ocr_results: tuple[str, ...] = ()  # JSON existants ; jamais leurs chemins internes
    ocr_dpi: int = 200
    ocr_batch_size: int = 4
    extract_tables: bool = True

    def validate(self):
        if self.ocr_mode not in ('auto', 'never', 'reuse_only'):
            raise ValueError('ocr_mode doit être auto, never ou reuse_only.')
        if self.ocr_dpi not in (200, 300) or type(self.ocr_dpi) is not int:
            raise ValueError('ocr_dpi doit être 200 ou 300.')
        if type(self.ocr_batch_size) is not int or not 1 <= self.ocr_batch_size <= 16:
            raise ValueError('ocr_batch_size doit être compris entre 1 et 16.')
        if type(self.extract_tables) is not bool:
            raise ValueError('extract_tables doit être booléen.')
        if self.pdf_pages is not None:
            if not isinstance(self.pdf_pages, (tuple, list)) or not self.pdf_pages or any(type(p) is not int or p < 1 for p in self.pdf_pages) or len(set(self.pdf_pages)) != len(self.pdf_pages):
                raise ValueError('pdf_pages : indices positifs, uniques, liste non vide.')
        if not isinstance(self.ocr_results, (tuple, list)) or any(not isinstance(p, str) for p in self.ocr_results):
            raise ValueError('ocr_results doit contenir des chemins de JSON.')


@dataclass(frozen=True)
class ConversionLimits:
    max_manifest_bytes: int = 8 * 1024**2
    max_documents: int = 20
    max_source_bytes: int = 100 * 1024**2
    max_pages: int = 200
    max_ocr_pages: int = 30
    max_blocks_per_page: int = 2000
    max_blocks: int = 50_000
    max_characters_per_page: int = 200_000
    max_docx_expanded_bytes: int = 128 * 1024**2
    max_xml_part_bytes: int = 4 * 1024**2
    max_xml_total_bytes: int = 32 * 1024**2
    max_table_cells: int = 10_000
    max_output_bytes: int = 64 * 1024**2
    max_pixels: int = 12_000_000
    timeout_seconds: float = 600
    max_worker_memory_bytes: int = 1536 * 1024**2

    def validate(self):
        for name, value in asdict(self).items():
            if name == 'timeout_seconds':
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError('timeout_seconds doit être positif et fini.')
            elif type(value) is not int or value <= 0:
                raise ValueError(f'{name} doit être un entier positif.')


class ConversionInputError(ValueError):
    """Requête/manifeste refusé avant traitement des documents."""


class ConversionFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Budget:
    def __init__(self, limits):
        self.limits = limits
        self.started = monotonic()

    @property
    def remaining(self):
        return max(0.0, self.limits.timeout_seconds - (monotonic() - self.started))

    def tick(self):
        if self.remaining <= 0:
            raise ConversionFailure('timeout', 'Délai de conversion dépassé.')


def error(code, message):
    return {'code': code, 'message': message}


def atomic_text(path, text, limit):
    data = text.encode('utf-8')
    if len(data) > limit:
        raise ConversionFailure('output_size_limit', 'Sortie trop volumineuse.')
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_bytes(data)
    temporary.replace(path)


def write_json(path, value, limit):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', limit)


def new_block(kind, text, method, *, page=None, bbox=None, **extra):
    return dict(type=kind, raw_text=text, text=text, method=method, page=page,
                bbox=bbox, language='und', human_validated=False,
                needs_review=False, warnings=[], render=True, **extra)
