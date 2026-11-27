import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from conversion_fixtures import ConversionCase, pdf_bytes, docx_bytes, zip_bytes
from P2_nlp_extraction.document_conversion import ConversionInputError, ConversionLimits, ConversionOptions
from P2_nlp_extraction.document_conversion.manifest_validation import confined, validate_manifest
from P2_nlp_extraction.document_conversion.models import Budget
from P2_nlp_extraction.document_conversion.worker import initial_document, process_request
from dataclasses import asdict


class SecurityAndAdapterTests(ConversionCase):
    def test_xml_part_with_bin_extension_is_also_checked(self):
        with zipfile.ZipFile(io.BytesIO(docx_bytes())) as archive:
            entries = []
            for name in archive.namelist():
                data = archive.read(name)
                if name in ('[Content_Types].xml', 'word/_rels/document.xml.rels'):
                    data = data.replace(b'header1.xml', b'header1.bin')
                if name == 'word/header1.xml':
                    name, data = 'word/header1.bin', b'<!DOCTYPE x [<!ENTITY hidden "unsafe">]><x/>'
                entries.append((name, data))
        self.ingestion(zip_bytes(entries), 'unsafe-extension.docx')
        result = self.convert()
        self.assertEqual(result['errors'][0]['code'], 'unsafe_xml')

    def test_docx_dtd_in_non_main_xml_rejected_before_python_docx(self):
        original = docx_bytes()
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            entries = [(name, b'<!DOCTYPE x [<!ENTITY hidden "unsafe">]><x/>' if name == 'word/header1.xml' else archive.read(name)) for name in archive.namelist()]
        self.ingestion(zip_bytes(entries), 'unsafe.docx')
        result = self.convert()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'][0]['code'], 'unsafe_xml')

    def test_junction_or_symlink_component_rejected(self):
        self.ingestion()
        target = self.manifest.parent / self.item['artifact_path']
        original = Path.is_symlink
        def is_link(path):
            return path == target.parent or original(path)
        with patch.object(Path, 'is_symlink', is_link):
            with self.assertRaises(ConversionInputError):
                confined(target)

    def test_manifest_changed_after_selection_rejected(self):
        self.ingestion()
        options, limits = ConversionOptions(ocr_mode='never'), ConversionLimits()
        path, manifest, items, digest = validate_manifest(self.manifest, limits)
        initial = initial_document(items[0], manifest, path, digest, options)
        self.change_manifest(lambda m: m.update(dce_id='changed'))
        folder = self.folder / 'worker'; folder.mkdir()
        result = process_request({'manifest_path': str(path), 'document_directory': str(folder),
                                  'options': asdict(options), 'limits': asdict(limits), 'initial_document': initial})
        self.assertEqual(result['errors'][0]['code'], 'manifest_integrity_mismatch')

    def test_auto_mode_calls_public_ocr_only_for_scanned_page(self):
        self.ingestion(pdf_bytes(('native', 'scan')))
        cache = self.mock_ocr((2,))
        simulated = json.loads(cache.read_text(encoding='utf-8'))
        options, limits = ConversionOptions(ocr_mode='auto'), ConversionLimits()
        path, manifest, items, digest = validate_manifest(self.manifest, limits)
        initial = initial_document(items[0], manifest, path, digest, options)
        folder = self.folder / 'worker'; folder.mkdir()
        with patch('P2_nlp_extraction.ocr_pipeline.extract_pdf', return_value=simulated) as mocked:
            result = process_request({'manifest_path': str(path), 'document_directory': str(folder),
                                      'options': asdict(options), 'limits': asdict(limits), 'initial_document': initial})
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs['pages'], [2])
        self.assertEqual(result['status'], 'completed_with_review', result['errors'])
        self.assertEqual({b['method'] for b in result['blocks']}, {'native_pdf', 'ocr'})

    def test_native_auto_does_not_call_public_ocr(self):
        self.ingestion()
        options, limits = ConversionOptions(), ConversionLimits()
        path, manifest, items, digest = validate_manifest(self.manifest, limits)
        folder = self.folder / 'worker'; folder.mkdir()
        with patch('P2_nlp_extraction.ocr_pipeline.extract_pdf', side_effect=AssertionError('OCR interdit')) as mocked:
            result = process_request({'manifest_path': str(path), 'document_directory': str(folder),
                                      'options': asdict(options), 'limits': asdict(limits),
                                      'initial_document': initial_document(items[0], manifest, path, digest, options)})
        mocked.assert_not_called()
        self.assertEqual(result['status'], 'completed')

    def test_second_ocr_batch_failure_keeps_first_batch_text(self):
        self.ingestion(pdf_bytes(('scan', 'scan')))
        simulated = json.loads(self.mock_ocr((1,)).read_text(encoding='utf-8'))
        options, limits = ConversionOptions(ocr_batch_size=1), ConversionLimits()
        path, manifest, items, digest = validate_manifest(self.manifest, limits)
        folder = self.folder / 'worker'; folder.mkdir()
        with patch('P2_nlp_extraction.ocr_pipeline.extract_pdf', side_effect=[simulated, RuntimeError('simulated')]) as mocked:
            result = process_request({'manifest_path': str(path), 'document_directory': str(folder),
                                      'options': asdict(options), 'limits': asdict(limits),
                                      'initial_document': initial_document(items[0], manifest, path, digest, options)})
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(any(b['raw_text'] == 'نص عربي' and b['page'] == 1 for b in result['blocks']))
        self.assertEqual(result['pages'][1]['status'], 'needs_ocr')

    def test_wrong_ocr_coordinates_rejected(self):
        self.ingestion(pdf_bytes(('scan',)))
        cache = self.mock_ocr()
        data = json.loads(cache.read_text(encoding='utf-8'))
        data['pages'][0]['blocks'][0]['bbox_pdf_points'] = [-100, 0, 100, 10]
        cache.write_text(json.dumps(data), encoding='utf-8')
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['errors'][0]['code'], 'ocr_coordinates_invalid')

    def test_duplicate_ocr_results_do_not_choose_arbitrarily(self):
        self.ingestion(pdf_bytes(('scan',)))
        cache = self.mock_ocr()
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache), str(cache))))
        self.assertEqual(result['errors'][0]['code'], 'ocr_duplicate_page')

    def test_ocr_spacing_proposal_is_separate_and_unvalidated(self):
        self.ingestion(pdf_bytes(('scan',)))
        cache = self.mock_ocr(raw_text='نصعربي')
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        block = result['blocks'][0]
        self.assertEqual(block['raw_text'], 'نصعربي')
        self.assertEqual(block['arabic_spacing_proposal']['proposed_text'], 'نص عربي')
        self.assertFalse(block['arabic_spacing_proposal']['human_validated'])
        markdown = Path(result['markdown_path']).read_text(encoding='utf-8')
        self.assertIn('نصعربي', markdown)
        self.assertNotIn('نص عربي', markdown)


if __name__ == '__main__':
    unittest.main()
