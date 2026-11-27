from importlib.util import find_spec
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
    @unittest.skipUnless(find_spec('numpy'), 'NumPy is part of the optional OCR environment')
    def test_short_rule_requires_raster_evidence_before_splitting(self):
        import numpy as np
        from P2_nlp_extraction.document_conversion.scan_tables import _short_vertical_rules

        gray = np.full((85, 100), 255, dtype=np.uint8)
        boxes = [(2, 2, 98, 24), (2, 27, 47, 51), (51, 27, 98, 51), (2, 54, 98, 81)]
        gray[2:24, 49] = 0
        gray[60:74, 49] = 0  # Short foreground mark inside a real merge.
        refined, evidence = _short_vertical_rules(gray, boxes, Budget(ConversionLimits()))
        self.assertEqual(evidence, [(49, 2, 49, 24)])
        self.assertIn((2, 2, 49, 24), refined)
        self.assertIn((49, 2, 98, 24), refined)
        self.assertIn(boxes[-1], refined)

    def test_borderless_bpu_preserves_rows_and_cell_geometry(self):
        import pymupdf
        from P2_nlp_extraction.document_conversion.pdf_native import extract_page

        matrix = [['Designation', 'Unite', 'Quantite', 'Montant'],
                  ['Beton', 'm3', '2', '200'], ['Acier', 'kg', '4', '400']]
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            for row, values in enumerate(matrix):
                for column, value in enumerate(values):
                    page.insert_text((50 + column * 130, 100 + row * 40), value)
            limits = ConversionLimits()
            result = extract_page(page, ConversionOptions(), limits, Budget(limits))
        table, = [block for block in result['blocks'] if block['type'] == 'table']
        self.assertEqual(table['cells'], matrix)
        self.assertIn('borderless_grid_inferred_from_text_alignment', table['warnings'])
        self.assertEqual(len(table['cell_metadata']), 12)
        self.assertEqual({cell['row'] for cell in table['cell_metadata']}, {0, 1, 2})

    def test_native_merged_cell_keeps_its_geometry_and_missing_cell(self):
        import pymupdf
        from P2_nlp_extraction.document_conversion.pdf_native import extract_page
        from P2_nlp_extraction.table_extraction.extraction import extract

        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.draw_rect(pymupdf.Rect(30, 30, 330, 150))
            page.draw_line((30, 70), (330, 70))
            page.draw_line((30, 110), (330, 110))
            page.draw_line((180, 70), (180, 150))
            for point, value in [((65, 55), 'Bordereau'), ((45, 95), 'Designation'),
                                 ((195, 95), 'Montant'), ((45, 135), 'Beton'), ((195, 135), '200')]:
                page.insert_text(point, value)
            limits = ConversionLimits()
            result = extract_page(page, ConversionOptions(), limits, Budget(limits))
        table, = [block for block in result['blocks'] if block['type'] == 'table']
        self.assertEqual(table['cells'][0], ['Bordereau', None])
        self.assertFalse(table['structure_preserved'])
        merged, = [cell for cell in table['cell_metadata'] if cell['row'] == 0]
        self.assertEqual(merged['bbox'], [30, 30, 330, 70])
        exported, = extract({'blocks': [dict(table, block_id='t24_1')]})
        self.assertEqual(exported['status'], 'partial')
        first, second = exported['rows'][0]['cells']
        self.assertEqual(first['source']['bbox'], merged['bbox'])
        self.assertIsNone(second['value'])
        self.assertEqual(exported['price_lines'], [])

    @unittest.skipUnless(find_spec('cv2'), 'OpenCV is part of the optional OCR environment')
    def test_scanned_grid_preserves_cell_geometry_and_unresolved_text(self):
        import pymupdf

        with pymupdf.open(stream=pdf_bytes(table=True)) as native, pymupdf.open() as scan:
            image = native[0].get_pixmap(dpi=144)
            page = scan.new_page(width=400, height=500)
            page.insert_image(page.rect, pixmap=image)
            self.ingestion(scan.tobytes())
        cache = self.mock_ocr()
        recorded = json.loads(cache.read_text(encoding='utf-8'))
        template = recorded['pages'][0]['blocks'][0]
        recorded['pages'][0]['blocks'] = [
            dict(template, block_id=f'ocr_{index}', raw_text=text, bbox_pdf_points=box)
            for index, (text, box) in enumerate((
                ('Article', [40, 194, 94, 210]), ('Prix', [160, 194, 205, 210]),
                ('Travaux', [40, 234, 102, 250]), (None, [160, 234, 205, 250]),
            ), 1)
        ]
        cache.write_text(json.dumps(recorded), encoding='utf-8')
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        table, = [block for block in result['blocks'] if block['type'] == 'table']
        self.assertEqual(table['cells'], [['Article', 'Prix'], ['Travaux', None]])
        self.assertEqual(table['cell_metadata'][0]['ocr_block_ids'], ['ocr_1'])
        self.assertEqual(len(table['cell_metadata'][0]['bbox']), 4)
        self.assertTrue(next(b for b in result['blocks'] if b['type'] == 'unresolved')['render'])
        markdown = Path(result['markdown_path']).read_text(encoding='utf-8')
        self.assertIn('| Article | Prix |', markdown)
        self.assertIn('Texte OCR indéterminé', markdown)

    def test_native_pdf_preserves_text_positions_and_structure(self):
        self.ingestion()
        result = self.convert()
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(all(b['method'] == 'native_pdf' for b in result['blocks']))
        self.assertTrue(any(b['type'] == 'heading' for b in result['blocks']))
        self.assertTrue(any(b['type'] == 'list_item' for b in result['blocks']))
        self.assertTrue(all(len(b['bbox']) == 4 and b['page'] == 1 for b in result['blocks']))
        self.assertIn('19/11/2026', Path(result['markdown_path']).read_text(encoding='utf-8'))
        locator = next(item for item in result['text_locators'] if item['kind'] == 'date')
        source = next(b for b in result['blocks'] if b['block_id'] == locator['block_id'])
        start, end = locator['span']
        self.assertEqual(source['raw_text'][start:end], '19/11/2026')
        self.assertEqual(locator['bbox'], source['bbox'])

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
        self.assertTrue(any(g['kind'] == 'raster' and len(g['bbox']) == 4
                            for g in result['pages'][0]['graphics']))

    def test_broken_arabic_font_mapping_requests_ocr_without_hiding_french(self):
        import pymupdf
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((60, 80), 'Texte natif valide et suffisamment long pour la conversion.')
            page.insert_htmlbox(pymupdf.Rect(60, 130, 500, 200),
                                '<div dir="rtl">الورقة الزرقاء</div>')
            self.ingestion(pdf.tobytes())
        result = self.convert(options=ConversionOptions(ocr_mode='never'))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pages'][0]['routing']['decision'], 'hybrid')
        self.assertTrue(any(not b['render'] and 'unusable_native_encoding' in b['warnings']
                            for b in result['blocks']))
        self.assertTrue(any(b['render'] and 'Texte natif valide' in b['raw_text']
                            for b in result['blocks']))

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


    def simulated_retry(self, status, *, fail=False):
        from dataclasses import asdict
        from P2_nlp_extraction.document_conversion.worker import initial_document, process_request
        from P2_nlp_extraction.scripts.ocr_common import sha256
        self.ingestion(pdf_bytes(('scan', 'scan')))
        cache = self.mock_ocr((1, 2))
        raw = json.loads(cache.read_text(encoding='utf-8'))
        raw['pages'][1].update(status=status, blocks=[])
        cache.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
        options = ConversionOptions(ocr_mode='auto', pdf_pages=(1,2), ocr_results=(str(cache),),
                                    ocr_batch_size=1, ocr_detector_max_side=1280)
        folder = self.folder / 'direct'; folder.mkdir()
        initial = initial_document(self.item, self.manifest_data, self.manifest, sha256(self.manifest), options)
        request = dict(manifest_path=str(self.manifest), document_directory=str(folder),
                       options=asdict(options), limits=asdict(ConversionLimits()), initial_document=initial)
        result = json.loads(json.dumps(raw))
        result['selected_pages'] = [2]; result['pages'] = [json.loads(json.dumps(raw['pages'][0]))]
        result['pages'][0]['page'] = 2
        from P2_nlp_extraction.document_conversion.models import ConversionFailure
        with patch('P2_nlp_extraction.document_conversion.ocr_adapter.recognize',
                   side_effect=ConversionFailure('ocr_failed','simulated failure') if fail else None,
                   return_value=result) as recognize_mock:
            process_request(request)
        self.assertEqual(recognize_mock.call_count, 1)
        self.assertEqual(recognize_mock.call_args.args[1], [2])
        output = json.loads((folder / 'document.json').read_text(encoding='utf-8'))
        from jsonschema import Draft202012Validator
        from P2_nlp_extraction.scripts.ocr_common import ROOT
        Draft202012Validator(json.loads((ROOT/'config/conversion.schema.json').read_text())).validate(output)
        self.assertEqual(output['pages'][0]['status'], 'completed_with_review')
        self.assertIn('previous_failed_ocr_retried', output['pages'][1]['warnings'])
        self.assertEqual(output['pages'][0]['blocks'][0]['bbox'], raw['pages'][0]['blocks'][0]['bbox_pdf_points'])
        return output

    def test_failed_cache_retried_without_repeating_completed_page(self):
        result = self.simulated_retry('error')
        self.assertEqual(result['pages'][1]['status'], 'completed_with_review')
        self.assertIn('previous_ocr_attempt', result['pages'][1]['ocr_provenance'])

    def test_processing_cache_retried(self):
        self.assertEqual(self.simulated_retry('processing')['pages'][1]['status'], 'completed_with_review')

    def test_retry_failure_preserves_previous_diagnostics(self):
        result = self.simulated_retry('error', fail=True)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pages'][1]['status'], 'ocr_incomplete')
        self.assertTrue(result['pages'][1]['ocr_provenance'])

    def test_small_detector_options_do_not_change_recognition_dpi_or_memory_limit(self):
        options = ConversionOptions(ocr_detector_max_side=1280, ocr_dpi=200, ocr_fallback_mode='off')
        limits = ConversionLimits(timeout_seconds=90)
        calls = []
        recognize('unused', [1], self.folder, options, limits, Budget(limits),
                  backend=lambda *a, **k: calls.append(k))
        self.assertEqual(calls[0]['detector_max_side'],1280)
        self.assertEqual(calls[0]['dpi'],200)
        self.assertEqual(calls[0]['pages'],[1])
        self.assertEqual(calls[0]['max_worker_memory_bytes'],1536*1024**2)
        self.assertLessEqual(calls[0]['timeout_seconds'],90)
        self.assertEqual(calls[0]['fallback_mode'],'off')


if __name__ == '__main__':
    unittest.main()
