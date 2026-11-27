"""Chemins portables et collisions conservatrices pour des archives non fiables."""
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata

from .models import IngestionFailure

RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', re.I)


def safe_relative(name, limits):
    if not isinstance(name, str) or not name or '\x00' in name:
        raise IngestionFailure('unsafe_path', 'Nom vide ou contenant un caractère NUL.')
    normal = name.replace('\\', '/')
    if normal.startswith('/') or ':' in normal:
        raise IngestionFailure('unsafe_path', 'Chemin absolu, lecteur ou flux Windows interdit.')
    trimmed = normal[:-1] if normal.endswith('/') else normal
    parts = trimmed.split('/')
    if len(trimmed) > limits.max_path_chars or len(parts) > limits.max_depth:
        raise IngestionFailure('path_limit', 'Chemin trop long ou trop profond.')
    for part in parts:
        if (part in ('', '.', '..') or part.endswith((' ', '.')) or RESERVED.match(part)
                or any(ord(c) < 32 or ord(c) == 127 or c in '<>"|?*' for c in part)):
            raise IngestionFailure('unsafe_path', 'Segment de chemin non portable ou dangereux.')
    return PurePosixPath(*parts).as_posix()


def collision_key(name):
    return '/'.join(unicodedata.normalize('NFC', part).casefold() for part in name.split('/'))


def validate_entries(infos, limits):
    entries, seen, implied = [], {}, set()
    for info in infos:
        original = info.orig_filename
        relative = safe_relative(original, limits)
        mode = stat.S_IFMT(info.external_attr >> 16)
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or info.external_attr & 0x400:
            raise IngestionFailure('special_entry', 'Lien ou entrée spéciale interdit.')
        is_dir = original.replace('\\', '/').endswith('/')
        if (mode == stat.S_IFDIR and not is_dir) or (mode == stat.S_IFREG and is_dir):
            raise IngestionFailure('entry_type_mismatch', 'Type et nom de l’entrée incohérents.')
        if is_dir and info.file_size:
            raise IngestionFailure('directory_payload', 'Un dossier contient des données.')
        key = collision_key(relative)
        parts = key.split('/')
        parents = ['/'.join(parts[:i]) for i in range(1, len(parts))]
        if key in seen or (not is_dir and key in implied) or any(seen.get(p) is False for p in parents):
            raise IngestionFailure('path_collision', 'Collision de noms ou conflit fichier/dossier.')
        # Les parents implicites gardent aussi leur graphie : A/x et a/y sont ambigus sous Windows.
        for i, parent in enumerate(parents, 1):
            actual = '/'.join(relative.split('/')[:i])
            previous = next((e['relative_path'] for e in entries if collision_key(e['relative_path']) == parent), actual)
            if previous != actual:
                raise IngestionFailure('path_collision', 'Graphies de dossiers incompatibles.')
        seen[key] = is_dir
        implied.update(parents)
        entries.append({'info': info, 'original_name': original, 'relative_path': relative,
                        'is_directory': is_dir})
    # Vérifier aussi les graphies des dossiers uniquement implicites.
    spellings = {}
    for entry in entries:
        parts = entry['relative_path'].split('/')
        for i in range(1, len(parts) + (1 if entry['is_directory'] else 0)):
            name = '/'.join(parts[:i]); key = collision_key(name)
            if key in spellings and spellings[key] != name:
                raise IngestionFailure('path_collision', 'Collision Unicode ou de casse dans les dossiers.')
            spellings[key] = name
    return entries


def confined_destination(folder, relative):
    root = Path(folder).resolve(strict=True)
    destination = root.joinpath(*PurePosixPath(relative).parts)
    if destination == root or not destination.resolve().is_relative_to(root):
        raise IngestionFailure('unsafe_destination', 'Destination hors du dossier de travail.')
    # Le dossier de travail est neuf ; refuser néanmoins toute jonction ajoutée entre-temps.
    for parent in [destination, *destination.parents]:
        if parent == root:
            break
        if parent.exists() and (parent.is_symlink() or parent.is_junction()):
            raise IngestionFailure('unsafe_destination', 'Lien ou jonction dans la destination.')
    return destination
