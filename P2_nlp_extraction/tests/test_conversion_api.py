import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from conversion_fixtures import ConversionCase, pdf_bytes, docx_bytes, zip_bytes
from P2_nlp_extraction.document_conversion import convert_ingestion, ConversionInputError, ConversionLimits, ConversionOptions
from P2_nlp_extraction.document_conversion.models import atomic_text, error
from P2_nlp_extraction.scripts.ocr_common import ROOT


class IntegrationTests(ConversionCase):
    def test_atomic_export_in_deep_folder(self):
        folder = self.folder / ('nested_' + 'x' * max(1, 227 - len(str(self.folder))))
        folder.mkdir()
        target = folder / 'document.md'
        atomic_text(target, 'First', 64)
        atomic_text(target, 'Second', 64)
        self.assertEqual(target.read_text(encoding='utf-8'), 'Second')
        self.assertEqual(list(folder.iterdir()), [target])

    def test_atomic_export_retries_windows_reader_lock(self):
        target = self.folder / 'progress.json'
        target.write_text('old', encoding='utf-8')
        locked = PermissionError('A polling reader has the file open')
        locked.winerror = 5
        original_replace = Path.replace
        attempts = []

        def replace(source, destination):
            attempts.append(destination)
            if len(attempts) == 1:
                raise locked
            return original_replace(source, destination)

        with patch.object(Path, 'replace', replace):
            atomic_text(target, 'new', 64)
        self.assertEqual(attempts, [target, target])
        self.assertEqual(target.read_text(encoding='utf-8'), 'new')

    def test_multi_document_t23_zip_to_markdown_json(self):
        self.ingestion(zip_bytes([('Français/cahier.pdf', pdf_bytes()), ('عربي/عقد.docx', docx_bytes()), ('notes.txt', b'unsupported')]), 'dce.zip')
        source_bytes = self.manifest.read_bytes()
        artifacts = {f['artifact_path']: (self.manifest.parent / f['artifact_path']).read_bytes() for f in self.manifest_data['files'] if f['artifact_path']}
        result = convert_ingestion(self.manifest, self.folder / 'conversion', options=ConversionOptions(ocr_mode='never'))
        self.assertEqual(len(result['documents']), 2)
        self.assertEqual(result['status'], 'completed_with_review')
        self.assertEqual(self.manifest.read_bytes(), source_bytes)
        self.assertTrue(all((self.manifest.parent / p).read_bytes() == data for p, data in artifacts.items()))
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / 'config/conversion.schema.json').read_text(encoding='utf-8'))
        validator = Draft202012Validator(schema)
        persisted = json.loads(Path(result['manifest_path']).read_text(encoding='utf-8'))
        validator.validate(persisted)
        for item in result['documents']:
            folder = Path(result['run_directory'])
            document = json.loads((folder / item['json']).read_text(encoding='utf-8'))
            validator.validate(document)
            self.assertFalse(document['human_validated'])
            ids = [b['block_id'] for b in document['blocks']]
            self.assertEqual(len(ids), len(set(ids)))
            text = (folder / item['markdown']).read_text(encoding='utf-8')
            lines = text.splitlines()
            for block in document['blocks']:
                if block['markdown_lines']:
                    start, end = block['markdown_lines']
                    self.assertTrue(1 <= start <= end <= len(lines))
            self.assertNotIn(str(ROOT), json.dumps(document, ensure_ascii=False))

    def test_one_document_by_id(self):
        self.ingestion(zip_bytes([('a.pdf', pdf_bytes()), ('b.docx', docx_bytes())]), 'package.zip')
        selected = next(f['file_id'] for f in self.manifest_data['files'] if f['detected_type'] == 'docx')
        result = self.convert(file_id=selected)
        self.assertEqual(result['document_id'], selected)
        self.assertEqual(result['source']['detected_type'], 'docx')

    def test_cli_accepts_manifest(self):
        self.ingestion()
        done = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'P2_nlp_extraction.document_conversion',
                               str(self.manifest), '--output-dir', str(self.folder / 'cli'), '--ocr-mode', 'never'],
                              cwd=ROOT.parent, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['status'], 'completed')

    def test_source_size_limit(self):
        self.ingestion()
        result = self.convert(limits=ConversionLimits(max_source_bytes=10))
        self.assertEqual(result['errors'][0]['code'], 'source_size_limit')

    def test_worker_timeout_no_fake_success(self):
        self.ingestion()
        result = self.convert(limits=ConversionLimits(timeout_seconds=.001))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'][0]['code'], 'timeout')

    def test_worker_memory_limit_no_fake_success(self):
        self.ingestion()
        result = self.convert(limits=ConversionLimits(max_worker_memory_bytes=1))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'][0]['code'], 'memory_limit')

    def test_failure_of_one_document_does_not_skip_next(self):
        self.ingestion(zip_bytes([('a.pdf', pdf_bytes()), ('b.pdf', pdf_bytes())]), 'pair.zip')
        calls = []
        from P2_nlp_extraction.document_conversion.api import _run
        def run(*args):
            calls.append(1)
            return (error('worker_failed', 'Simulated worker failure.'), 0.0) if len(calls) == 1 else _run(*args)
        with patch('P2_nlp_extraction.document_conversion.api._run', side_effect=run):
            result = convert_ingestion(self.manifest, self.folder / 'batch', options=ConversionOptions(ocr_mode='never'))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([d['status'] for d in result['documents']], ['failed', 'completed'])

    def test_no_conversion_written_into_ingestion(self):
        self.ingestion()
        with self.assertRaises(ValueError):
            convert_ingestion(self.manifest, self.manifest.parent, options=ConversionOptions(ocr_mode='never'))


if __name__ == '__main__':
    unittest.main()
