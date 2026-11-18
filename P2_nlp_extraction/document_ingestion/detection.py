"""Identification structurelle bornée ; aucune conversion ou reconnaissance OCR."""
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.parsers import expat

from .models import IngestionFailure, InvalidDocument
from .safety import safe_relative
from .zip_extraction import checked_zip, read_member

CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
WORD_NS = ('http://schemas.openxmlformats.org/wordprocessingml/2006/main',
           'http://purl.oclc.org/ooxml/wordprocessingml/main')
OFFICE_REL = ('http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument',
              'http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument')
DOCX_MAIN = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
DOCM_MAIN = 'application/vnd.ms-word.document.macroEnabled.main+xml'


def _xml(data, budget, callback):
    """Pas d'arbre XML ; callbacks bornés et DTD/entités systématiquement refusées."""
    parser = expat.ParserCreate(namespace_separator='|')
    depth, count, root = 0, 0, None

    def forbidden(*args):
        raise IngestionFailure('unsafe_xml', 'DTD et entités XML interdites.')

    def start(name, attrs):
        nonlocal depth, count, root
        budget.tick()
        depth += 1; count += 1
        if root is None:
            root = name
        if depth > budget.limits.max_xml_depth or count > budget.limits.max_xml_nodes:
            raise IngestionFailure('xml_complexity_limit', 'XML trop profond ou trop complexe.')
        callback(name, attrs, depth)

    def end(name):
        nonlocal depth
        depth -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    try:
        for pos in range(0, len(data), 16*1024):
            budget.tick()
            parser.Parse(data[pos:pos+16*1024], False)
        parser.Parse(b'', True)
    except expat.ExpatError as exc:
        raise InvalidDocument('XML Open XML invalide.') from exc
    return root


def _part_name(name, limits, *, absolute=False):
    # Les cibles OPC sont des URI locales ; aucune relation externe n'est suivie.
    url = urlsplit(name)
    if url.scheme or url.netloc or url.query or url.fragment or '\\' in name:
        raise InvalidDocument('Relation Open XML non locale ou ambiguë.')
    decoded = unquote(url.path, encoding='utf-8', errors='strict')
    if absolute:
        if not decoded.startswith('/') or decoded.startswith('//'):
            raise InvalidDocument('Nom de partie Open XML invalide.')
        decoded = decoded[1:]
    elif decoded.startswith('/'):
        decoded = decoded[1:]
    return safe_relative(decoded, limits)


def _docx(archive, entries, budget):
    by_name = {e['relative_path']: e for e in entries if not e['is_directory']}
    required = ('[Content_Types].xml', '_rels/.rels')
    if any(name not in by_name for name in required):
        raise InvalidDocument('Paquet Office incomplet : types ou relations absents.')
    contents = {}
    for name, entry in by_name.items():
        if name in required:
            contents[name] = read_member(archive, entry['info'], budget, cap=budget.limits.max_xml_bytes)['data']
    types, targets, declared_types = {}, [], []

    def content_type(name, attrs, depth):
        if name in (CT_NS+'|Override', CT_NS+'|Default') and depth == 2:
            declared_types.append(attrs.get('ContentType', ''))
        if name == CT_NS+'|Override' and depth == 2:
            part = _part_name(attrs.get('PartName', ''), budget.limits, absolute=True)
            if part in types:
                raise InvalidDocument('Type de partie déclaré plusieurs fois.')
            types[part] = attrs.get('ContentType', '')

    if _xml(contents['[Content_Types].xml'], budget, content_type) != CT_NS+'|Types':
        raise InvalidDocument('Racine des types Open XML invalide.')

    def relationship(name, attrs, depth):
        if name == REL_NS+'|Relationship' and depth == 2 and attrs.get('Type') in OFFICE_REL:
            if attrs.get('TargetMode', 'Internal') != 'Internal':
                raise InvalidDocument('Document principal externe interdit.')
            targets.append(_part_name(attrs.get('Target', ''), budget.limits))

    if _xml(contents['_rels/.rels'], budget, relationship) != REL_NS+'|Relationships' or len(targets) != 1:
        raise InvalidDocument('Relation principale Word absente ou ambiguë.')
    main = targets[0]
    kind = types.get(main)
    if kind == DOCM_MAIN:
        return {'detected_type': 'docm', 'mime_type': 'application/vnd.ms-word.document.macroEnabled.12',
                'status': 'blocked', 'reason': 'macros_not_supported', 'warnings': []}
    if kind != DOCX_MAIN:
        return {'detected_type': 'ooxml', 'mime_type': 'application/zip', 'status': 'unsupported',
                'reason': 'office_type_not_supported', 'warnings': []}
    if main not in by_name:
        raise InvalidDocument('Partie principale Word absente.')
    if (any(PurePosixPath(name).name.casefold() == 'vbaproject.bin' for name in by_name)
            or any('vbaproject' in value.casefold() for value in declared_types)):
        raise IngestionFailure('macro_content_detected', 'Macros dans un conteneur déclaré DOCX.')
    bodies = []

    def document(name, attrs, depth):
        if name in tuple(ns+'|body' for ns in WORD_NS) and depth == 2:
            bodies.append(name)

    main_xml = read_member(archive, by_name[main]['info'], budget, cap=budget.limits.max_xml_bytes)['data']
    root = _xml(main_xml, budget, document)
    if root not in tuple(ns+'|document' for ns in WORD_NS) or bodies != [root.rsplit('|', 1)[0]+'|body']:
        raise InvalidDocument('Structure principale Word invalide.')
    # Vérifier CRC/tailles de toutes les autres parties, sans les exécuter ni suivre leurs relations.
    for name, entry in by_name.items():
        if name not in required and name != main:
            read_member(archive, entry['info'], budget)
    for entry in entries:
        if entry['is_directory']:
            read_member(archive, entry['info'], budget)
    return {'detected_type': 'docx', 'mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'status': 'ready', 'reason': None, 'warnings': [],
            'metadata': {'main_part': main, 'part_count': len(entries), 'validation_level': 'structure_and_crc'}}


def detect_file(path, original_name, budget):
    """Interne au worker. Un DOCX n'est jamais reconnu sur son seul suffixe."""
    budget.tick()
    with path.open('rb') as source:
        head = source.read(1024)
    import zipfile
    zip_signature = head.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'))
    if not zip_signature and zipfile.is_zipfile(path) and b'%PDF-' not in head:
        raise IngestionFailure('zip_layout_unsupported', 'ZIP préfixé ou auto-extractible non pris en charge.')
    result = {'detected_type': 'unknown', 'mime_type': 'application/octet-stream',
              'status': 'unsupported', 'reason': 'unknown_format', 'warnings': []}
    pdf_header = head.find(b'%PDF-')
    if 0 <= pdf_header < 1024:
        # Un ZIP ordinaire peut contenir un PDF stocké : ne pas l'interpréter comme un PDF autonome.
        if not head.startswith(b'PK'):
            if zipfile.is_zipfile(path):
                raise IngestionFailure('ambiguous_container', 'Fichier à la fois PDF et ZIP : refus conservateur.')
            import pymupdf
            try:
                with pymupdf.open(path, filetype='pdf') as pdf:
                    if not pdf.is_pdf or not pdf.page_count:
                        raise InvalidDocument('PDF sans structure exploitable.')
                    result = {'detected_type': 'pdf', 'mime_type': 'application/pdf',
                              'status': 'blocked' if pdf.needs_pass or pdf.is_repaired else 'ready',
                              'reason': 'password_required' if pdf.needs_pass else 'pdf_repair_required' if pdf.is_repaired else None,
                              'warnings': ['pdf_repaired'] if pdf.is_repaired else [],
                              'metadata': {'page_count': pdf.page_count, 'encrypted': bool(pdf.needs_pass),
                                           'validation_level': 'structure_only'}}
            except (RuntimeError, ValueError, InvalidDocument) as exc:
                result.update(detected_type='pdf', mime_type='application/pdf', status='invalid', reason='invalid_pdf')
    if zip_signature:
        with checked_zip(path, budget) as (archive, entries):
            budget.add_entries(len(entries))
            names = {e['relative_path'] for e in entries}
            office = '[Content_Types].xml' in names or '_rels/.rels' in names or 'word/document.xml' in names
            if office:
                try:
                    result = _docx(archive, entries, budget)
                except (InvalidDocument, UnicodeError, ValueError) as exc:
                    result = {'detected_type': 'ooxml', 'mime_type': 'application/zip', 'status': 'invalid',
                              'reason': 'invalid_ooxml', 'warnings': []}
            else:
                result = {'detected_type': 'zip', 'mime_type': 'application/zip', 'status': 'archive',
                          'reason': None, 'warnings': [], 'metadata': {'entry_count': len(entries)}}
    extension = PurePosixPath(original_name.replace('\\', '/')).suffix.casefold()
    expected = {'pdf': '.pdf', 'docx': '.docx', 'docm': '.docm', 'zip': '.zip'}
    if (result['detected_type'] in expected and extension != expected[result['detected_type']]
            or extension in expected.values() and expected.get(result['detected_type']) != extension):
        result['warnings'].append('extension_mismatch')
    return result
