"""Petites fixtures T23, créées uniquement dans un répertoire temporaire P2."""
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from P2_nlp_extraction.document_ingestion import IngestionLimits
from P2_nlp_extraction.document_ingestion.worker import process_request
from P2_nlp_extraction.scripts.ocr_common import ROOT


def pdf_bytes(encrypted=False):
    import pymupdf
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        page.insert_text((20, 30), 'Synthetic T23 document')
        kwargs = {'encryption': pymupdf.PDF_ENCRYPT_AES_256, 'owner_pw': 'owner', 'user_pw': 'test'} if encrypted else {}
        return pdf.tobytes(**kwargs)


def zip_bytes(entries, compression=zipfile.ZIP_STORED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def docx_bytes(*, main=None, main_type=None, extra=(), relationships=None):
    main_type = main_type or 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
    main = main if main is not None else '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Français عربي</w:t></w:r></w:p></w:body></w:document>'
    types = f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="{main_type}"/></Types>'
    rels = relationships or '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    return zip_bytes([('[Content_Types].xml', types), ('_rels/.rels', rels), ('word/document.xml', main), *extra])


class IngestionCase(unittest.TestCase):
    def setUp(self):
        parent = ROOT/'.cache/t23_tests'; parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.counter = 0

    def source(self, data, name='source.zip'):
        target = self.folder/name
        target.write_bytes(data)
        return target

    def direct(self, data, name='source.zip', **limits):
        source = self.source(data, name)
        self.counter += 1
        run = self.folder/f'run_{self.counter}'; run.mkdir()
        self.last_run = run
        return process_request({'source_path': str(source), 'source_name': name,
                                'run_directory': str(run), 'dce_id': None,
                                'limits': asdict(IngestionLimits(**limits))})

    def assert_rejected(self, result, code=None):
        self.assertIn(result['status'], ('failed', 'rejected'))
        self.assertFalse(result['eligible_for_t24'])
        self.assertTrue(result['errors'])
        self.assertTrue(all(not f['eligible_for_t24'] and f['artifact_path'] is None for f in result['files']))
        if code:
            self.assertEqual(result['errors'][0]['code'], code)
