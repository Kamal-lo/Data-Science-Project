"""T25 : prétraitement et repli avec modèles simulés exclusivement."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from conversion_fixtures import ConversionCase, pdf_bytes
from P2_nlp_extraction.document_conversion import ConversionOptions
from P2_nlp_extraction.ocr_pipeline import extract_pdf
from P2_nlp_extraction.ocr_pipeline.preprocessing import enhance_scan
from P2_nlp_extraction.ocr_pipeline.quality import assess
from P2_nlp_extraction.ocr_pipeline.recovery import FallbackBudget, detect_page, recognize_block
from P2_nlp_extraction.ocr_pipeline.routing import route
from P2_nlp_extraction.ocr_pipeline.worker import process_document
from P2_nlp_extraction.scripts.ocr_common import ROOT


def candidates(fr='texte français fiable', fs=.95, ar='', ars=.1):
    return {'fr': {'text': fr, 'confidence': fs}, 'ar': {'text': ar, 'confidence': ars}}


class SequenceRecognizer:
    def __init__(self, results):
        self.results, self.calls = results, []

    def recognize(self, image, language):
        index = min(len(self.calls) // 2, len(self.results) - 1)
        self.calls.append(language)
        value = self.results[index][language]
        if isinstance(value, Exception): raise value
        return copy.deepcopy(value)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.image = np.full((40, 200, 3), 230, dtype=np.uint8)
        self.image[10:30, 20:180] = 180

    def run_block(self, outputs, budget=None, **kwargs):
        self.backend = SequenceRecognizer(outputs)
        return recognize_block(self.backend, self.image, budget or FallbackBudget('preprocess'), 100_000, **kwargs)

    def test_preprocessing_preserves_geometry_and_original_pixels(self):
        original = self.image.copy()
        result, metadata = enhance_scan(self.image, 100_000)
        self.assertEqual(result.shape, original.shape)
        self.assertTrue((self.image == original).all())
        self.assertFalse(metadata['geometry_changed'])
        self.assertEqual(metadata['coordinate_transform'], 'identity')
        self.assertFalse((result == original).all())

    def test_preprocessing_limits_and_bad_images(self):
        import numpy as np
        with self.assertRaises(ValueError): enhance_scan(self.image, 10)
        for bad in (None, np.zeros((0, 4, 3), dtype=np.uint8), np.zeros((4, 4), dtype=np.uint8)):
            with self.assertRaises(ValueError): enhance_scan(bad, 100)

    def test_nonempty_text_alone_is_not_quality(self):
        result = assess(route(candidates('llllllllllll', .99)))
        self.assertFalse(result['usable'])
        self.assertIn('repeated_character_noise', result['reasons'])
        self.assertFalse(result['human_validated'])

    def test_valid_primary_does_not_retry(self):
        result, errors, _ = self.run_block([candidates()])
        self.assertEqual(len(self.backend.calls), 2)
        self.assertFalse(result['fallback_attempted'])
        self.assertEqual(result['raw_text'], 'texte français fiable')
        self.assertFalse(errors)

    def test_low_confidence_recovered_and_all_attempts_preserved(self):
        result, errors, _ = self.run_block([candidates('texte initial faible', .3), candidates()])
        self.assertTrue(result['fallback_used'])
        self.assertEqual(result['selected_attempt'], 1)
        self.assertIsNone(result['primary_raw_text'])
        self.assertEqual(result['recognition_attempts'][0]['result']['recognition_candidates']['fr']['text'], 'texte initial faible')
        self.assertEqual(result['raw_text'], 'texte français fiable')
        self.assertTrue(result['needs_review'])
        self.assertFalse(errors)

    def test_arabic_recovery_preserves_raw_spaces(self):
        result, _, _ = self.run_block([candidates('', .1, 'النصالعربي', .3), candidates('', .1, 'النصالعربي', .98)])
        self.assertEqual(result['language'], 'ar')
        self.assertEqual(result['raw_text'], 'النصالعربي')
        self.assertTrue(result['fallback_used'])

    def test_repeated_garbage_can_be_recovered(self):
        result, _, _ = self.run_block([candidates('llllllllllll', .99), candidates()])
        self.assertEqual(result['primary_raw_text'], 'llllllllllll')
        self.assertTrue(result['fallback_used'])

    def test_failed_recovery_abstains(self):
        result, _, _ = self.run_block([candidates('faible', .2), candidates('toujours faible', .3)])
        self.assertIsNone(result['raw_text'])
        self.assertEqual(result['selected_attempt'], 0)
        self.assertTrue(result['fallback_attempted'])
        self.assertFalse(result['quality']['usable'])

    def test_script_conflict_does_not_force_language(self):
        result, _, _ = self.run_block([candidates('texte fiable', .99, 'النص العربي', .99)])
        self.assertIsNone(result['raw_text'])
        self.assertEqual(len(self.backend.calls), 2)
        self.assertEqual(result['fallback_skipped_reason'], 'ambiguous_or_unsupported_region_requires_review')

    def test_tifinagh_like_unresolved_hypotheses_are_not_promoted(self):
        result, _, _ = self.run_block([candidates('. .', .7, 'OEI oloHMM', .9)])
        self.assertIsNone(result['raw_text'])
        self.assertEqual(result['language'], 'und')
        self.assertEqual(len(self.backend.calls), 2)

    def test_numeric_consensus_needs_confidence_and_punctuation_is_not_text(self):
        self.assertTrue(assess(route(candidates('123,45', .99, '123,45', .99)))['usable'])
        self.assertFalse(assess(route(candidates('123,45', .1, '123,45', .1)))['usable'])
        self.assertFalse(assess(route(candidates('...', .99, '...', .99)))['usable'])

    def test_recognizer_exception_can_recover_without_losing_history(self):
        bad = candidates(); bad['ar'] = RuntimeError('synthetic recognition error')
        result, errors, _ = self.run_block([bad, candidates()])
        self.assertTrue(result['fallback_used'])
        self.assertFalse(errors)
        self.assertTrue(result['recognition_attempts'][0]['errors'])
        self.assertEqual(result['raw_text'], result['primary_raw_text'])

    def test_alternative_conflict_keeps_valid_primary(self):
        bad = candidates(); bad['ar'] = RuntimeError('synthetic')
        result, _, _ = self.run_block([bad, candidates('autre texte crédible')])
        self.assertFalse(result['fallback_used'])
        self.assertEqual(result['raw_text'], 'texte français fiable')
        self.assertIn('fallback_conflicts_with_primary_primary_preserved', result['warnings'])

    def test_block_budget_and_time_budget(self):
        budget = FallbackBudget('preprocess', max_blocks=1)
        self.run_block([candidates('faible', .2), candidates()], budget)
        result, _, _ = self.run_block([candidates('faible', .2)], budget)
        self.assertEqual(result['fallback_skipped_reason'], 'fallback_block_budget')
        self.assertEqual(len(self.backend.calls), 2)
        budget = FallbackBudget('preprocess', timeout_seconds=1); budget.spent_seconds = 1
        result, _, _ = self.run_block([candidates('faible', .2)], budget)
        self.assertEqual(result['fallback_skipped_reason'], 'fallback_time_budget')

    def test_disabled_retry_keeps_quality_gate_active(self):
        result, _, _ = self.run_block([candidates('llllllll', .99)], FallbackBudget('off'))
        self.assertFalse(result['fallback_attempted'])
        self.assertIsNone(result['raw_text'])

    def test_already_processed_page_is_not_processed_twice(self):
        result, _, _ = self.run_block([candidates('faible', .2)], image_variant='contrast_grayscale')
        self.assertFalse(result['fallback_attempted'])
        self.assertEqual(result['fallback_skipped_reason'], 'page_already_preprocessed')

    def test_invalid_confidence_is_error_not_trusted(self):
        values = candidates(); values['fr']['confidence'] = float('nan')
        result, errors, _ = self.run_block([values], FallbackBudget('off'))
        self.assertIsNone(result['raw_text'])
        self.assertTrue(errors)
        self.assertEqual(result['recognition_candidates']['fr']['text'], values['fr']['text'])
        self.assertEqual(result['recognition_candidates']['fr']['invalid_confidence_repr'], 'nan')

    def test_empty_detection_gets_one_contrast_retry(self):
        class Detector:
            def __init__(self): self.calls = 0
            def detect(self, image):
                self.calls += 1
                return ([], []) if self.calls == 1 else ([[[1, 1], [20, 1], [20, 10], [1, 10]]], [.9])
        backend, budget = Detector(), FallbackBudget('preprocess')
        polygons, _, image, history = detect_page(backend, self.image, budget, 100_000)
        self.assertEqual(len(polygons), 1)
        self.assertEqual(backend.calls, 2)
        self.assertEqual(image.shape, self.image.shape)
        self.assertEqual(history['selected_attempt'], 1)
        self.assertTrue(budget.page_attempted)

    def test_detection_error_recovery_and_double_error_history(self):
        class Detector:
            def __init__(self, recover): self.calls, self.recover = 0, recover
            def detect(self, image):
                self.calls += 1
                if self.recover and self.calls == 2: return ([[[1, 1], [20, 1], [20, 10], [1, 10]]], [.9])
                raise RuntimeError('synthetic detector error')
        for recover in (True, False):
            backend = Detector(recover)
            _, _, _, history = detect_page(backend, self.image, FallbackBudget('preprocess'), 100_000)
            self.assertEqual(backend.calls, 2)
            self.assertTrue(history['attempts'][0]['error'])
            self.assertEqual(history['selected_error'] is None, recover)


class RecoveryIntegrationTests(ConversionCase):
    def source_pdf(self):
        p = self.folder/'source.pdf'; p.write_bytes(pdf_bytes(('scan',)))
        return p

    def fake_completed(self, command, **kwargs):
        request = json.loads(Path(command[-1]).read_text(encoding='utf-8'))
        self.request_seen = request
        retry_detection = getattr(self, 'retry_detection', False)
        empty_detection = getattr(self, 'empty_detection', False)
        strong_recognition = getattr(self, 'strong_recognition', False)
        class Models:
            metadata = {'fake': True, 'downloads': False}
            initialization_seconds = 0
            def __init__(self, **kw): self.calls, self.detect_calls = 0, 0
            def detect(self, image):
                self.detect_calls += 1
                if empty_detection or (retry_detection and self.detect_calls == 1): return [], []
                return ([[[10, 10], [200, 10], [200, 40], [10, 40]]], [.9])
            def crop(self, image, polygon): return image[10:40, 10:200].copy()
            def recognize(self, image, language):
                round_number = self.calls // 2
                self.calls += 1
                if strong_recognition: return candidates('texte récupéré', .98)[language]
                return candidates('texte faible' if round_number == 0 else 'texte récupéré', .3 if round_number == 0 else .98)[language]
        process_document(request, backend_factory=Models)
        class Finished:
            returncode = 0
            def poll(self): return 0
        return Finished()

    def test_public_ocr_to_t24_preserves_recovery_and_coordinates(self):
        self.ingestion(pdf_bytes(('scan',)))
        source = self.manifest.parent/self.item['artifact_path']
        with patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=self.fake_completed):
            result = extract_pdf(source, self.folder/'ocr', pages=[1], arabic_spacing='off', fallback_mode='preprocess')
        self.assertEqual(self.request_seen['pages'], [1])
        block = result['pages'][0]['blocks'][0]
        self.assertTrue(block['fallback_used'])
        self.assertEqual(block['raw_text'], 'texte récupéré')
        self.assertIsNone(block['primary_raw_text'])
        converted = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(result['exports']['json'],)))
        self.assertEqual(converted['status'], 'completed_with_review', converted['errors'])
        extracted = converted['blocks'][0]
        self.assertEqual(extracted['bbox'], block['bbox_pdf_points'])
        self.assertTrue(extracted['ocr_recovery']['fallback_used'])
        self.assertEqual(extracted['ocr_recovery']['recognition_attempts'], block['recognition_attempts'])
        self.assertFalse(extracted['human_validated'])
        self.assertEqual(result['pdf_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertNotIn(str(ROOT), json.dumps(json.loads(Path(converted['document_json_path']).read_text(encoding='utf-8'))))

    def test_faint_scan_preprocessed_without_geometry_change(self):
        import pymupdf
        from PIL import Image, ImageDraw
        picture = Image.new('RGB', (200, 200), (255, 255, 255))
        ImageDraw.Draw(picture).rectangle((20, 20, 180, 180), fill=(249, 249, 249))
        import io
        stream = io.BytesIO(); picture.save(stream, format='PNG')
        p = self.folder/'faint.pdf'
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=200, height=200)
            page.insert_image(page.rect, stream=stream.getvalue())
            p.write_bytes(pdf.tobytes())
        with patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=self.fake_completed):
            result = extract_pdf(p, self.folder/'faint_output', pages=[1], arabic_spacing='off')
        page = result['pages'][0]
        self.assertEqual(page['preprocessing']['primary_variant'], 'contrast_for_faint_scan')
        self.assertFalse(page['preprocessing']['parameters']['geometry_changed'])
        self.assertTrue(Path(page['preprocessing']['selected_image']).exists())

    def test_detection_recovery_requires_review_and_keeps_pdf_coordinates(self):
        self.retry_detection, self.strong_recognition = True, True
        with patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=self.fake_completed):
            result = extract_pdf(self.source_pdf(), self.folder/'detection_recovery', pages=[1], arabic_spacing='off')
        page = result['pages'][0]
        self.assertEqual(page['status'], 'needs_review')
        self.assertEqual(page['detection_attempts']['selected_attempt'], 1)
        self.assertEqual(len(page['detection_attempts']['attempts']), 2)
        block = page['blocks'][0]
        self.assertEqual(block['bbox'], [10.0, 10.0, 200.0, 40.0])
        self.assertAlmostEqual(block['bbox_pdf_points'][0], 10 / page['image_size'][0] * page['pdf_rect'][2])
        self.assertTrue(Path(page['preprocessing']['selected_image']).exists())

    def test_empty_both_attempts_remains_incomplete_in_t24(self):
        self.empty_detection = True
        self.ingestion(pdf_bytes(('scan',)))
        source = self.manifest.parent/self.item['artifact_path']
        with patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=self.fake_completed):
            result = extract_pdf(source, self.folder/'empty', pages=[1])
        page = result['pages'][0]
        self.assertEqual(page['status'], 'no_text_detected')
        self.assertEqual(len(page['detection_attempts']['attempts']), 2)
        converted = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(result['exports']['json'],)))
        self.assertEqual(converted['status'], 'partial')
        self.assertFalse(converted['blocks'])

    def test_missing_model_is_fatal_without_retry(self):
        folder = self.folder/'missing_model'; folder.mkdir()
        calls = []
        def missing(**kwargs):
            calls.append(1)
            raise FileNotFoundError('Synthetic local model absent; no download.')
        process_document({'pdf_path': str(self.source_pdf()), 'run_dir': str(folder), 'pages': [1],
                          'dpi': 200, 'max_pixels': 6_000_000, 'cpu_threads': 1, 'arabic_spacing': 'off',
                          'on_error': 'continue', 'fallback_mode': 'preprocess'}, backend_factory=missing)
        self.assertEqual(len(calls), 1)
        self.assertTrue((folder/'fatal_error.json').is_file())
        page = json.loads((folder/'pages/page_001.json').read_text(encoding='utf-8'))
        self.assertEqual(page['status'], 'error')
        self.assertEqual(page['fallback']['blocks_attempted'], 0)

    def test_invalid_options_rejected_before_models(self):
        p = self.source_pdf()
        for kwargs in ({'fallback_mode': 'download'}, {'max_fallback_blocks': 1000},
                       {'max_fallback_blocks': True}, {'fallback_timeout_seconds': float('inf')}):
            with self.assertRaises(ValueError): extract_pdf(p, self.folder/'invalid', **kwargs)
        with self.assertRaises(ValueError): ConversionOptions(ocr_fallback_mode='download').validate()

    def test_t24_adapter_transmits_fallback_limits(self):
        from P2_nlp_extraction.document_conversion.models import Budget, ConversionLimits
        from P2_nlp_extraction.document_conversion.ocr_adapter import recognize
        captured = {}
        def fake(source, **kwargs): captured.update(kwargs); return {'pages': []}
        recognize(self.source_pdf(), [1], self.folder, ConversionOptions(ocr_fallback_mode='off', ocr_max_fallback_blocks=2),
                  ConversionLimits(), Budget(ConversionLimits()), backend=fake)
        self.assertEqual(captured['fallback_mode'], 'off')
        self.assertEqual(captured['max_fallback_blocks'], 2)
        self.assertEqual(captured['pages'], [1])


class ConversionOptionsCompatibilityTests(unittest.TestCase):
    def test_original_positional_and_keyword_options_remain_equivalent(self):
        for extract_tables in (False, True):
            with self.subTest(extract_tables=extract_tables):
                positional = ConversionOptions('never', None, (), 200, 4, extract_tables)
                keyword = ConversionOptions(ocr_mode='never', pdf_pages=None, ocr_results=(),
                                            ocr_dpi=200, ocr_batch_size=4, extract_tables=extract_tables)
                positional.validate()
                keyword.validate()
                self.assertEqual(positional, keyword)
                self.assertIs(positional.extract_tables, extract_tables)
                self.assertEqual(positional.ocr_fallback_mode, 'preprocess')
        self.assertEqual(ConversionOptions('never', None, (), 200, 4),
                         ConversionOptions(ocr_mode='never'))
        explicit = ConversionOptions('auto', None, (), 200, 4, False,
                                     ocr_fallback_mode='off', ocr_max_fallback_blocks=2,
                                     ocr_fallback_timeout_seconds=5)
        explicit.validate()
        self.assertFalse(explicit.extract_tables)
        self.assertEqual(explicit.ocr_fallback_mode, 'off')
        self.assertEqual(explicit.ocr_max_fallback_blocks, 2)
        self.assertEqual(explicit.ocr_fallback_timeout_seconds, 5)


if __name__ == '__main__':
    unittest.main()
