"""ZIP conservateur : métadonnées bornées, structure cohérente, lecture comptabilisée."""
from contextlib import contextmanager
import hashlib
import struct
import zipfile
import zlib

from .models import IngestionFailure
from .safety import validate_entries

EOCD = struct.Struct('<4s4H2IH')
CENTRAL = struct.Struct('<4s6H3I5H2I')
LOCAL = struct.Struct('<4s5H3I2H')


def _reject(code, message):
    raise IngestionFailure(code, message)


def _extra(data):
    pos = 0
    while pos < len(data):
        if pos + 4 > len(data):
            _reject('corrupt_zip', 'Champ extra ZIP tronqué.')
        kind, size = struct.unpack_from('<HH', data, pos)
        pos += 4
        if kind == 1:
            _reject('zip64_unsupported', 'ZIP64 non pris en charge.')
        if pos + size > len(data):
            _reject('corrupt_zip', 'Taille de champ extra ZIP incohérente.')
        pos += size


def _preflight(path, budget):
    """Lire un répertoire central borné AVANT ZipFile, qui l'allouerait en mémoire."""
    limits = budget.limits
    size = path.stat().st_size
    if size > limits.max_file_bytes:
        _reject('file_size_limit', 'Conteneur ZIP trop volumineux.')
    with path.open('rb') as source:
        source.seek(max(0, size - 65557))
        tail = source.read(65557)
        pos = len(tail)
        while True:
            pos = tail.rfind(b'PK\x05\x06', 0, pos)
            if pos < 0:
                _reject('corrupt_zip', 'Fin du répertoire ZIP absente ou tronquée.')
            if pos + EOCD.size <= len(tail):
                end = EOCD.unpack_from(tail, pos)
                if pos + EOCD.size + end[-1] == len(tail):
                    break
        disk, cd_disk, disk_count, count, cd_size, cd_offset = end[1:7]
        end_offset = size - len(tail) + pos
        if pos >= 20 and tail[pos-20:pos-16] == b'PK\x06\x07':
            _reject('zip64_unsupported', 'Localisateur ZIP64 non pris en charge.')
        if count == 65535 or disk_count == 65535 or cd_size == 0xffffffff or cd_offset == 0xffffffff:
            _reject('zip64_unsupported', 'ZIP64 non pris en charge.')
        if disk or cd_disk or disk_count != count:
            _reject('multidisk_unsupported', 'Archives multidisques non prises en charge.')
        if count > limits.max_entries:
            _reject('entry_count_limit', 'Trop d’entrées ZIP.')
        if cd_size > limits.max_metadata_bytes:
            _reject('metadata_limit', 'Répertoire central trop volumineux.')
        if cd_offset + cd_size != end_offset:
            _reject('zip_layout_unsupported', 'Préfixe, données annexes ou structure ZIP non prise en charge.')
        source.seek(cd_offset)
        central = source.read(cd_size)
        if len(central) != cd_size:
            _reject('corrupt_zip', 'Répertoire central tronqué.')
        offset, records, declared_total = 0, [], 0
        while offset < len(central):
            budget.tick()
            if offset + CENTRAL.size > len(central):
                _reject('corrupt_zip', 'Entrée centrale tronquée.')
            item = CENTRAL.unpack_from(central, offset)
            if item[0] != b'PK\x01\x02':
                _reject('corrupt_zip', 'Signature centrale invalide.')
            _, made, needed, flags, method, _, _, crc, compressed, expanded, nlen, xlen, clen, entry_disk, _, _, local_offset = item
            if any(v == 0xffffffff for v in (compressed, expanded, local_offset)):
                _reject('zip64_unsupported', 'Entrée ZIP64 non prise en charge.')
            if entry_disk:
                _reject('multidisk_unsupported', 'Entrée sur un autre disque.')
            if flags & 1:
                _reject('encrypted_zip_unsupported', 'ZIP chiffré non pris en charge.')
            if method not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                _reject('compression_unsupported', f'Méthode ZIP non prise en charge : {method}.')
            if needed >= 45:
                _reject('zip64_unsupported', 'Version ZIP64 non prise en charge.')
            if flags & ~0x080e or needed > 20:
                _reject('zip_features_unsupported', 'Fonctions ZIP non prises en charge.')
            if expanded > limits.max_file_bytes:
                _reject('file_size_limit', 'Fichier décompressé trop volumineux.')
            if expanded / max(1, compressed) > limits.max_compression_ratio:
                _reject('compression_ratio_limit', 'Ratio de compression excessif.')
            declared_total += expanded
            if declared_total > limits.max_total_bytes:
                _reject('total_size_limit', 'Taille totale déclarée excessive.')
            stop = offset + CENTRAL.size + nlen + xlen + clen
            if stop > len(central) or not nlen or nlen > 4096:
                _reject('corrupt_zip', 'Longueur de métadonnée incohérente.')
            name = central[offset+CENTRAL.size:offset+CENTRAL.size+nlen]
            _extra(central[offset+CENTRAL.size+nlen:offset+CENTRAL.size+nlen+xlen])
            records.append((local_offset, flags, method, crc, compressed, expanded, name))
            if len(records) > limits.max_entries:
                _reject('entry_count_limit', 'Nombre réel d’entrées excessif.')
            offset = stop
        if len(records) != count:
            _reject('corrupt_zip', 'Nombre d’entrées centrales incohérent.')
        ranges, metadata_bytes = [], cd_size
        for local_offset, flags, method, crc, compressed, expanded, name in records:
            budget.tick()
            source.seek(local_offset)
            header = source.read(LOCAL.size)
            if len(header) != LOCAL.size:
                _reject('corrupt_zip', 'En-tête local tronqué.')
            sig, needed, local_flags, local_method, _, _, lcrc, lcsize, lusize, nlen, xlen = LOCAL.unpack(header)
            if sig != b'PK\x03\x04' or (local_flags, local_method) != (flags, method):
                _reject('corrupt_zip', 'En-têtes local et central incohérents.')
            if needed > 20 or lcsize == 0xffffffff or lusize == 0xffffffff:
                _reject('zip64_unsupported', 'Fonction locale ZIP64/non prise en charge.')
            metadata_bytes += LOCAL.size + nlen + xlen
            if metadata_bytes > limits.max_metadata_bytes:
                _reject('metadata_limit', 'Métadonnées locales cumulées excessives.')
            if nlen != len(name) or source.read(nlen) != name:
                _reject('corrupt_zip', 'Noms local et central différents.')
            _extra(source.read(xlen))
            end_data = local_offset + LOCAL.size + nlen + xlen + compressed
            if flags & 8:
                source.seek(end_data)
                descriptor = source.read(16)
                signed = descriptor.startswith(b'PK\x07\x08')
                start = 4 if signed else 0
                if len(descriptor) < start+12 or struct.unpack_from('<3I', descriptor, start) != (crc, compressed, expanded):
                    _reject('corrupt_zip', 'Descripteur de données incohérent.')
                end_data += start + 12
            elif (lcrc, lcsize, lusize) != (crc, compressed, expanded):
                _reject('corrupt_zip', 'Tailles/CRC local et central différents.')
            if end_data > cd_offset:
                _reject('overlapping_zip', 'Données ZIP chevauchantes.')
            ranges.append((local_offset, end_data))
        previous = 0
        for start, stop in sorted(ranges):
            if start != previous:
                _reject('zip_layout_unsupported', 'Entrées chevauchantes, préfixe ou zones annexes.')
            previous = stop
        if previous != cd_offset:
            _reject('zip_layout_unsupported', 'Disposition ZIP non prise en charge.')


@contextmanager
def checked_zip(path, budget):
    _preflight(path, budget)
    try:
        with zipfile.ZipFile(path) as archive:
            entries = validate_entries(archive.infolist(), budget.limits)
            yield archive, entries
    except (zipfile.BadZipFile, EOFError, zlib.error, UnicodeError, NotImplementedError) as exc:
        raise IngestionFailure('corrupt_zip', 'Conteneur ZIP illisible ou corrompu.', status='failed') from exc


def read_member(archive, info, budget, *, destination=None, cap=None):
    """Décompression bornée, y compris si file_size ment ; contrôle de fin et CRC."""
    limit = min(budget.limits.max_file_bytes, cap if cap is not None else budget.limits.max_file_bytes)
    if info.file_size > limit:
        _reject('xml_size_limit' if cap is not None else 'file_size_limit', 'Taille du membre excessive.')
    count, digest, chunks, crc = 0, hashlib.sha256(), [], 0

    def accept(chunk):
        nonlocal count, crc
        count += len(chunk)
        budget.consume(len(chunk))
        if count > limit:
            _reject('file_size_limit', 'Taille réellement lue excessive.')
        if count > info.file_size:
            _reject('corrupt_zip', 'La taille réelle dépasse la taille déclarée.')
        if count / max(1, info.compress_size) > budget.limits.max_compression_ratio:
            _reject('compression_ratio_limit', 'Ratio réel excessif.')
        digest.update(chunk); crc = zlib.crc32(chunk, crc)
        if destination is not None:
            destination.write(chunk)
        elif cap is not None:
            chunks.append(chunk)

    # ZipExtFile tronque au file_size déclaré. Ici on contrôle aussi le flux réel.
    with open(archive.filename, 'rb') as source:
        source.seek(info.header_offset)
        header = LOCAL.unpack(source.read(LOCAL.size))
        source.seek(header[-2] + header[-1], 1)
        remaining = info.compress_size
        decoder = zlib.decompressobj(-15) if info.compress_type == zipfile.ZIP_DEFLATED else None
        while remaining:
            budget.tick()
            raw = source.read(min(64*1024, remaining))
            if not raw:
                _reject('corrupt_zip', 'Données compressées tronquées.')
            remaining -= len(raw)
            if decoder is None:
                accept(raw)
                continue
            while raw:
                budget.tick()
                chunk = decoder.decompress(raw, min(64*1024, limit-count+1, info.file_size-count+1))
                accept(chunk)
                if decoder.unused_data or (decoder.eof and remaining):
                    _reject('corrupt_zip', 'Données annexes dans le flux compressé.')
                raw = decoder.unconsumed_tail
        if decoder is not None and not decoder.eof:
            _reject('corrupt_zip', 'Flux deflate incomplet.')
    if count != info.file_size or crc != info.CRC:
        _reject('corrupt_zip', 'Taille décompressée incohérente.')
    return {'size_bytes': count, 'sha256': digest.hexdigest(), 'data': b''.join(chunks) if cap is not None else None}
