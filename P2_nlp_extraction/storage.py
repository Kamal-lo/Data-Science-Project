"""T09 : stockage local immuable ; métadonnées portables pour un futur backend P6."""
import hashlib
import os
from pathlib import Path
import stat
import tempfile

from .scripts.ocr_common import ROOT, sha256
from .document_ingestion.models import IngestionLimits
from .document_ingestion.safety import safe_relative


def output_path(path):
    """Les nouvelles sorties sont limitées à P2/outputs, jamais au code source."""
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT / 'outputs'):
        raise ValueError('La destination doit rester dans P2_nlp_extraction/outputs.')
    return path


def resolve_export(entry, *, max_bytes=None):
    """Resolve a job export inside P2/outputs and verify its size and SHA-256."""
    path = output_path(ROOT / entry['path'])
    size = path.stat().st_size
    if max_bytes is not None and size > max_bytes:
        raise ValueError('Export trop volumineux pour cette lecture.')
    if not path.is_file() or size != entry.get('size_bytes') or sha256(path) != entry['sha256']:
        raise ValueError('Export modifié depuis le traitement.')
    return path


def store_document(source_path, *, directory=None, max_bytes=50 * 1024**2):
    """Copier en flux, identifier par SHA-256 et refuser de remplacer un objet.

    Le retour constitue le contrat T09 : backend, document_id, sha256,
    size_bytes, original_name et artifact_path relatif à P2. Ce stockage local
    ne constitue pas une connexion à la base de données ou au serveur de P6.
    """
    source = Path(source_path)
    if safe_relative(source.name, IngestionLimits()) != source.name:
        raise ValueError('Nom de fichier non portable.')
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('max_bytes doit être un entier positif.')
    if source.is_symlink() or source.is_junction() or not stat.S_ISREG(source.stat().st_mode):
        raise ValueError('La source doit être un fichier régulier, sans lien.')
    base = output_path(directory or ROOT / 'outputs/library')
    base.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        digest = hashlib.sha256()
        size = 0
        with source.open('rb') as incoming, tempfile.NamedTemporaryFile(dir=base, delete=False) as stream:
            temporary = Path(stream.name)
            while chunk := incoming.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError('Fichier trop volumineux pour le stockage local.')
                digest.update(chunk)
                stream.write(chunk)
        checksum = digest.hexdigest()
        folder = output_path(base / checksum)
        folder.mkdir(exist_ok=True)
        target = output_path(folder / source.name)
        try:
            # Création sans écrasement, y compris si deux dépôts sont simultanés.
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or sha256(target) != checksum:
                raise ValueError('Objet existant corrompu : aucun remplacement effectué.')
        return dict(schema_version='p2.storage.v1', backend='local',
                    document_id='sha256:' + checksum, sha256=checksum,
                    size_bytes=size, original_name=source.name,
                    artifact_path=target.relative_to(ROOT).as_posix())
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)  # Seulement le temporaire créé par cet appel.


def resolve_document(record):
    """Vérifier un échange T09 avant lecture ; ne pas faire confiance à son chemin."""
    if record.get('schema_version') != 'p2.storage.v1' or record.get('backend') != 'local':
        raise ValueError('Contrat de stockage local inconnu.')
    path = output_path(ROOT / record['artifact_path'])
    if (path.is_symlink() or not path.is_file() or path.name != record.get('original_name')
            or record.get('document_id') != 'sha256:' + record.get('sha256', '')
            or path.parent.name != record.get('sha256')
            or path.stat().st_size != record.get('size_bytes')
            or sha256(path) != record.get('sha256')):
        raise ValueError('Identité ou intégrité du document non conforme.')
    return path
