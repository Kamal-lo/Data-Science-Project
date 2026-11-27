"""Contrat et limites explicites de l'ingestion."""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class IngestionLimits:
    max_source_bytes: int = 100 * 1024**2
    max_entries: int = 1000
    max_file_bytes: int = 100 * 1024**2
    max_total_bytes: int = 500 * 1024**2
    max_compression_ratio: float = 100
    max_depth: int = 16
    max_path_chars: int = 180
    max_metadata_bytes: int = 8 * 1024**2
    max_xml_bytes: int = 4 * 1024**2
    max_xml_nodes: int = 50_000
    max_xml_depth: int = 64
    timeout_seconds: float = 60
    max_worker_memory_bytes: int = 512 * 1024**2

    def validate(self):
        for name, value in asdict(self).items():
            if name in ('timeout_seconds', 'max_compression_ratio'):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError(f'{name} doit être positif et fini.')
            elif type(value) is not int or value <= 0:
                raise ValueError(f'{name} doit être un entier strictement positif.')


class IngestionFailure(Exception):
    def __init__(self, code, message, *, status='rejected'):
        super().__init__(message)
        self.code, self.status = code, status


class InvalidDocument(Exception):
    """Format documentaire endommagé ; ce n'est pas une validation réussie."""


class Budget:
    def __init__(self, limits, clock=None):
        from time import monotonic
        self.limits = limits
        self.clock = clock or monotonic
        self.started = self.clock()
        self.bytes_read = 0
        self.entries = 0

    def tick(self):
        if self.clock() - self.started > self.limits.timeout_seconds:
            raise IngestionFailure('timeout', 'Délai maximal dépassé.')

    def consume(self, size):
        self.tick()
        self.bytes_read += size
        if self.bytes_read > self.limits.max_total_bytes:
            raise IngestionFailure('total_size_limit', 'Budget global de lecture/décompression dépassé.')

    def add_entries(self, count):
        self.entries += count
        self.tick()
        if self.entries > self.limits.max_entries:
            raise IngestionFailure('entry_count_limit', 'Trop d’entrées, parties DOCX comprises.')
