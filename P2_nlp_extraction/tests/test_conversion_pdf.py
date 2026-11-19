import json
from pathlib import Path
import unittest
from unittest.mock import patch

from conversion_fixtures import ConversionCase, pdf_bytes
from P2_nlp_extraction.document_conversion import ConversionLimits, ConversionOptions
from P2_nlp_extraction.document_conversion.layout import merge_native_ocr, order_blocks
from P2_nlp_extraction.document_conversion.models import Budget, new_block
from P2_nlp_extraction.document_conversion.ocr_adapter import recognize
from P2_nlp_extraction.document_conversion.routing import choose_route


class PDFTests(ConversionCase):
    def test_native_pdf_preserves_text_positions_and_structure(self):
        self.ingestion()
        result = self.convert()
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(all(b['method'] == 'native_pdf' for b in result['blocks']))
        self.assertTrue(any(b['type'] == 'heading' for b in result['blocks']))
        self.assertTrue(any(b['type'] == 'list_item' for b in result['blocks']))
        self.assertTrue(all(len(b['bbox']) == 4 and b['page'] == 1 for b in result['blocks']))
        self.assertIn('19/11/2026', Path(result['markdown_path']).read_text(encoding='utf-8'))

    def test_scan_with_simulated_arabic_ocr(self):
        self.ingestion(pdf_bytes(('scan',)))
        cache = self.mock_ocr()
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        self.assertEqual(result['status'], 'completed_with_review')
        block = result['blocks'][0]
        self.assertEqual(block['raw_text'], 'نص عربي')
        self.assertEqual(block['method'], 'ocr')
        self.assertEqual(block['direction'], 'rtl')
        self.assertFalse(block['human_validated'])
        self.assertIn('recognition_candidates', block)
        self.assertEqual(result['pages'][0]['routing']['decision'], 'ocr')

    def test_mixed_pdf_routes_pages_individually(self):
        self.ingestion(pdf_bytes(('native', 'scan')))
        cache = self.mock_ocr((2,))
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        self.assertEqual([p['routing']['decision'] for p in result['pages']], ['native', 'ocr'])
        self.assertEqual({b['method'] for b in result['blocks']}, {'native_pdf', 'ocr'})
        self.assertEqual({b['page'] for b in result['blocks']}, {1, 2})

    def test_native_footer_does_not_hide_scanned_region(self):
        self.ingestion(pdf_bytes(('hybrid',)))
        cache = self.mock_ocr()
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        self.assertEqual(result['pages'][0]['routing']['decision'], 'hybrid')
        self.assertEqual({b['method'] for b in result['blocks']}, {'native_pdf', 'ocr'})

    def test_missing_ocr_is_partial_not_success(self):
        self.ingestion(pdf_bytes(('native', 'scan')))
        result = self.convert()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pages'][1]['status'], 'needs_ocr')
        self.assertIn('Conversion incomplète', Path(result['markdown_path']).read_text(encoding='utf-8'))

    def test_ambiguous_ocr_preserves_hypotheses_not_guess(self):
        self.ingestion(pdf_bytes(('scan',)))
        cache = self.mock_ocr(ambiguous=True)
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        self.assertIsNone(result['blocks'][0]['raw_text'])
        self.assertIn('Texte OCR indéterminé', Path(result['markdown_path']).read_text(encoding='utf-8'))

    def test_blank_page_no_ocr(self):
        self.ingestion(pdf_bytes(('blank',)))
        result = self.convert()
        self.assertEqual(result['pages'][0]['status'], 'apparently_blank')
        self.assertFalse(result['blocks'])

    def test_vector_content_needs_ocr(self):
        self.ingestion(pdf_bytes(('vector',)))
        result = self.convert()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pages'][0]['routing']['decision'], 'ocr')

    def test_rotated_coordinates(self):
        self.ingestion(pdf_bytes(rotation=90))
        result = self.convert()
        self.assertEqual(result['pages'][0]['width'], 500)
        for b in result['blocks']:
            self.assertGreaterEqual(b['bbox'][0], 0)
            self.assertLessEqual(b['bbox'][2], 500)
            self.assertLessEqual(b['bbox'][3], 400)

    def test_simple_table(self):
        self.ingestion(pdf_bytes(table=True))
        result = self.convert()
        tables = [b for b in result['blocks'] if b['type'] == 'table']
        self.assertTrue(tables)
        self.assertTrue(tables[0]['structure_preserved'])
        text = Path(result['markdown_path']).read_text(encoding='utf-8')
        self.assertIn('| Article | Prix |', text)
        self.assertEqual(text.count('Travaux'), 1)

    def test_paragraph_crossing_table_boundary_is_not_suppressed(self):
        import pymupdf
        with pymupdf.open(stream=pdf_bytes(table=True), filetype='pdf') as pdf:
            wide = 'HORS_TABLE ' + 'texte ' * 15
            pdf[0].insert_text((20, 170), '\n'.join([wide] + ['texte ' * 17] * 9), fontsize=9)
            # Un gros bloc englobe la grille ET du texte hors tableau : sa partie
            # extérieure ne doit pas disparaître au profit d'un tableau supposé.
            data = pdf.tobytes()
        self.ingestion(data)
        result = self.convert()
        self.assertIn('HORS\\_TABLE', Path(result['markdown_path']).read_text(encoding='utf-8'))

    def test_page_limit(self):
        self.ingestion(pdf_bytes(('native', 'native')))
        result = self.convert(limits=ConversionLimits(max_pages=1))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'][0]['code'], 'page_limit')

    def test_selected_pages_explicit_coverage(self):
        self.ingestion(pdf_bytes(('native', 'scan')))
        result = self.convert(options=ConversionOptions(ocr_mode='never', pdf_pages=(1,)))
        self.assertEqual(result['coverage']['source_page_count'], 2)
        self.assertEqual(result['coverage']['processed_pages'], [1])
        self.assertIn('only_requested_pages_converted', result['warnings'])

    def test_character_limit(self):
        self.ingestion()
        result = self.convert(limits=ConversionLimits(max_characters_per_page=3))
        self.assertEqual(result['errors'][0]['code'], 'character_limit')

    def test_existing_ocr_api_adapter_selected_pages_only(self):
        calls = []
        def fake(path, **kwargs):
            calls.append(kwargs)
            return {'pages': []}
        recognize('unused.pdf', [2], self.folder, ConversionOptions(), ConversionLimits(), Budget(ConversionLimits()), backend=fake)
        self.assertEqual(calls[0]['pages'], [2])
        self.assertEqual(calls[0]['cpu_threads'], 2)
        self.assertEqual(calls[0]['arabic_spacing'], 'suggest')
        self.assertIsNone(recognize('unused', [1], self.folder, ConversionOptions(ocr_mode='never'), ConversionLimits(), Budget(ConversionLimits()), backend=lambda *a, **k: self.fail('OCR interdit')))

    def test_dedup_requires_coordinates_and_exact_normalized_text(self):
        native = new_block('paragraph', 'Texte identique', 'native_pdf', bbox=[0, 0, 100, 20])
        duplicate = new_block('paragraph', 'Texte identique', 'ocr', bbox=[0, 0, 100, 20])
        elsewhere = new_block('paragraph', 'Texte identique', 'ocr', bbox=[0, 100, 100, 120])
        merged = merge_native_ocr([native], [duplicate, elsewhere])
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(native['alternative_recognitions']), 1)

    def test_conflicting_ocr_is_flagged_and_retained_as_hypothesis(self):
        native = new_block('paragraph', '12000 MAD', 'native_pdf', bbox=[0, 0, 100, 20])
        ocr = new_block('paragraph', '1200 MAD', 'ocr', bbox=[0, 0, 100, 20])
        merged = merge_native_ocr([native], [ocr])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['raw_text'], '12000 MAD')
        self.assertEqual(merged[0]['alternative_recognitions'][0]['raw_text'], '1200 MAD')
        self.assertTrue(merged[0]['needs_review'])

    def test_a_few_native_characters_are_not_enough(self):
        block = new_block('paragraph', '1', 'native_pdf', bbox=[0, 0, 20, 20])
        self.assertEqual(choose_route([block], [], [0, 0, 400, 500])['decision'], 'hybrid')

    def test_empty_ocr_on_a_scanned_page_stays_partial(self):
        self.ingestion(pdf_bytes(('scan',)))
        cache = self.mock_ocr()
        data = json.loads(cache.read_text(encoding='utf-8'))
        data['pages'][0].update(status='no_text_detected', blocks=[])
        cache.write_text(json.dumps(data), encoding='utf-8')
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pages'][0]['status'], 'ocr_incomplete')

    def test_rtl_blocks_ordered_right_to_left(self):
        left = new_block('paragraph', 'عربي', 'ocr', bbox=[10, 10, 50, 30]); left['language'] = 'ar'
        right = new_block('paragraph', 'نص', 'ocr', bbox=[100, 10, 140, 30]); right['language'] = 'ar'
        self.assertEqual(order_blocks([left, right])[0]['raw_text'], 'نص')
        self.assertTrue(left['needs_review'])

    def test_cache_source_hash_must_match(self):
        self.ingestion(pdf_bytes(('scan',)))
        cache = self.mock_ocr()
        data = json.loads(cache.read_text(encoding='utf-8')); data['pdf_sha256'] = '0' * 64
        cache.write_text(json.dumps(data), encoding='utf-8')
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['errors'][0]['code'], 'ocr_source_mismatch')


if __name__ == '__main__':
    unittest.main()
