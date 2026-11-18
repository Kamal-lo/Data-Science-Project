"""Tests techniques sans OCR réel, fixtures temporaires sous P2/.cache."""
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from P2_nlp_extraction.ocr_pipeline import extract_pdf, OCRPipelineError
from P2_nlp_extraction.ocr_pipeline.routing import route, script_stats
from P2_nlp_extraction.ocr_pipeline.layout import detections, reading_order
from P2_nlp_extraction.ocr_pipeline.spacing import propose, segments
from P2_nlp_extraction.ocr_pipeline.worker import process_document
from P2_nlp_extraction.ocr_pipeline.api import _export, _failure
from P2_nlp_extraction.ocr_pipeline.models import DETECTION_SETTINGS, MODEL_NAMES
from P2_nlp_extraction.scripts.ocr_common import ROOT


def candidates(fr='texte français', fs=.95, ar='', ars=.1):
    return {'fr': {'text': fr, 'confidence': fs}, 'ar': {'text': ar, 'confidence': ars}}


class FakeModels:
    metadata = {'fake': True}
    initialization_seconds = 0
    def __init__(self, **kwargs):
        pass
    def detect(self, image):
        return [[[10, 10], [100, 10], [100, 35], [10, 35]]], [.9]
    def crop(self, image, polygon):
        return image[10:35, 10:100]
    def recognize(self, image, language):
        return candidates()[language]


class AutomaticPipelineTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT/'.cache/ocr_pipeline_tests'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def test_model_inventory_is_tracked_configuration_for_active_models(self):
        from pathlib import PurePosixPath
        inventory = json.loads((ROOT/'config/model_inventory.json').read_text(encoding='utf-8'))
        self.assertEqual(len(inventory), 9)
        expected = {(model, filename) for model in MODEL_NAMES.values()
                    for filename in ('inference.json', 'inference.yml', 'inference.pdiparams')}
        actual = set()
        for item in inventory:
            path = PurePosixPath(item['path'])
            self.assertFalse(path.is_absolute())
            self.assertNotIn('\\', item['path'])
            self.assertNotIn('..', path.parts)
            actual.add((path.parent.name, path.name))
            self.assertEqual(len(bytes.fromhex(item['sha256'])), 32)
        self.assertEqual(actual, expected)

    def make_pdf(self, blank=False):
        import pymupdf
        path = self.folder/'synthetic.pdf'
        with pymupdf.open() as pdf:
            for number in (1, 2):
                page = pdf.new_page(width=200, height=200)
                if not blank:
                    page.insert_text((20, 30), f'Synthetic test page {number}')
            pdf.save(path)
        return path

    def request(self, pdf, **kwargs):
        return dict(pdf_path=str(pdf), run_dir=str(self.folder), pages=[1, 2], dpi=200,
                    cpu_threads=4, max_pixels=1_000_000, arabic_spacing='off', on_error='continue', **kwargs)

    def test_clear_scripts_and_conflicting_candidates(self):
        self.assertEqual(route(candidates())['language'], 'fr')
        self.assertEqual(route(candidates(fr='noise', fs=.2, ar='المملكة المغربية', ars=.95))['language'], 'ar')
        ambiguous = route(candidates(ar='المملكة المغربية', ars=.95))
        self.assertEqual(ambiguous['language'], 'und')
        self.assertIsNone(ambiguous['raw_text'])
        self.assertTrue(ambiguous['needs_review'])
        self.assertEqual(len(ambiguous['recognition_candidates']), 2)

    def test_mobile_detector_matches_working_pipeline_defaults(self):
        self.assertEqual(MODEL_NAMES['det'], 'PP-OCRv5_mobile_det')
        self.assertEqual(DETECTION_SETTINGS['limit_side_len'], 64)
        self.assertEqual(DETECTION_SETTINGS['limit_type'], 'min')
        self.assertEqual(DETECTION_SETTINGS['unclip_ratio'], 1.5)

    def test_neutral_mixed_and_other_scripts_not_forced_to_arabic(self):
        neutral = route(candidates(fr='2024', ar='2024', ars=.9))
        self.assertEqual(neutral['language'], 'und')
        self.assertEqual(neutral['raw_text'], '2024')
        self.assertEqual(script_stats('ⵜⴰⵎⴰⵣⵉⵖⵜ')['script'], 'mixed_or_other')
        self.assertEqual(route(candidates(fr='', fs=0, ar='عربي ABC', ars=.9))['language'], 'mixed')

    def test_recognition_failure_is_explicit(self):
        value = candidates()
        value['ar']['error'] = 'synthetic error'
        result = route(value)
        self.assertIn('recognizer_error', result['warnings'])
        self.assertTrue(result['needs_review'])

    def test_dedup_preserves_other_positions_and_overlap_conflicts(self):
        poly = [[0, 0], [100, 0], [100, 20], [0, 20]]
        second = [[200, 0], [300, 0], [300, 20], [200, 20]]
        kept, duplicates, _ = detections([poly, poly, second], [.9]*3, 400, 400)
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(duplicates), 1)
        with self.assertRaises(ValueError):
            detections([[[0, 0]]*4], [.9], 400, 400)

    def test_rtl_and_mixed_rows_are_explicit(self):
        blocks = [{'language': 'ar', 'bbox': [20, 10, 100, 30], 'raw_text': 'المعهد', 'needs_review': False, 'warnings': []},
                  {'language': 'ar', 'bbox': [200, 10, 300, 30], 'raw_text': 'المملكة', 'needs_review': False, 'warnings': []}]
        ordered, warnings = reading_order(blocks)
        self.assertEqual(ordered[0]['raw_text'], 'المملكة')
        self.assertEqual(ordered[0]['direction'], 'rtl')
        blocks[0]['language'] = 'fr'
        self.assertTrue(any(w['code'] == 'ambiguous_mixed_row' for w in reading_order(blocks)[1]))

    def test_spaces_never_change_letters(self):
        self.assertTrue(propose('المملكةالمغربية', ['المملكة', 'المغربية'])['accepted'])
        self.assertFalse(propose('المملكةالمغربية', ['المملكة', 'المغربيه'])['accepted'])
        from PIL import Image
        self.assertEqual(segments(Image.new('L', (100, 30), 255))['status'], 'no_ink')

    def test_multipage_processing_and_exports_with_fake_models(self):
        process_document(self.request(self.make_pdf()), backend_factory=FakeModels)
        pages = [json.loads((self.folder/'pages'/f'page_{p:03d}.json').read_text(encoding='utf-8')) for p in (1, 2)]
        self.assertTrue(all(p['detected_block_count'] == 1 for p in pages))
        self.assertTrue(all(p['blocks'][0]['language'] == 'fr' for p in pages))
        self.assertIn('bbox_pdf_points', pages[0]['blocks'][0])
        result = {'pages': pages}
        _export(self.folder, result)
        self.assertIn('texte français', (self.folder/'document_raw.txt').read_text(encoding='utf-8'))
        self.assertEqual(json.loads((self.folder/'document.json').read_text(encoding='utf-8'))['pages'][1]['page'], 2)

    def test_blank_pdf_does_not_load_models(self):
        def forbidden(**kwargs):
            raise AssertionError('must not load models for blank fixture')
        process_document(self.request(self.make_pdf(blank=True)), backend_factory=forbidden)
        for p in (1, 2):
            result = json.loads((self.folder/'pages'/f'page_{p:03d}.json').read_text())
            self.assertEqual(result['status'], 'near_blank')
            self.assertEqual(result['blocks'], [])

    def test_page_errors_continue_and_do_not_become_empty_pages(self):
        class Broken(FakeModels):
            def detect(self, image):
                raise RuntimeError('synthetic detector failure')
        process_document(self.request(self.make_pdf()), backend_factory=Broken)
        for p in (1, 2):
            result = json.loads((self.folder/'pages'/f'page_{p:03d}.json').read_text())
            self.assertEqual(result['status'], 'error')
            self.assertTrue(result['errors'])

    def test_input_validation_and_output_confinement_without_models(self):
        pdf = self.make_pdf()
        for pages in ([0], [3], [1, 1], []):
            with self.assertRaises(ValueError):
                extract_pdf(pdf, self.folder/'output', pages=pages)
        with self.assertRaises(ValueError):
            extract_pdf(pdf, ROOT.parent/'forbidden', pages=[1])
        with self.assertRaises(ValueError):
            extract_pdf(pdf, self.folder, timeout_seconds=float('nan'))

    def test_error_result_retains_partial_blocks(self):
        record = _failure(1, 'timeout', {'page': 1, 'blocks': [{'raw_text': 'partial'}]})
        self.assertEqual(record['blocks'][0]['raw_text'], 'partial')
        self.assertEqual(record['status'], 'error')
        exc = OCRPipelineError('failure', {'pages': [record]})
        self.assertTrue(exc.result['pages'][0]['errors'])

    def fake_completed_process(self, command, **kwargs):
        request = json.loads(Path(command[-1]).read_text(encoding='utf-8'))
        process_document(request, backend_factory=FakeModels)
        class Finished:
            returncode = 0
            def poll(self):
                return self.returncode
        return Finished()

    def test_public_api_exports_without_loading_models_in_caller(self):
        with patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=self.fake_completed_process):
            result = extract_pdf(self.make_pdf(), self.folder/'api_output', pages=[1, 2], arabic_spacing='off')
        self.assertEqual([p['page'] for p in result['pages']], [1, 2])
        self.assertTrue(Path(result['exports']['json']).is_file())
        self.assertIn('texte français', Path(result['exports']['raw_txt']).read_text(encoding='utf-8'))

    def test_native_failure_preserves_first_page_and_continues_with_next(self):
        calls = []
        def run(command, **kwargs):
            request = json.loads(Path(command[-1]).read_text(encoding='utf-8'))
            calls.append(request['pages'])
            if len(calls) > 1:
                return self.fake_completed_process(command, **kwargs)
            folder = Path(request['run_dir'])
            (folder/'progress.json').write_text(json.dumps({'phase': 'page', 'page': 1}))
            class Crashed:
                returncode = -11
                def poll(self):
                    return self.returncode
            return Crashed()
        with patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=run):
            result = extract_pdf(self.make_pdf(), self.folder/'native_output', pages=[1, 2])
        self.assertEqual(calls, [[1, 2], [2]])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([p['status'] for p in result['pages']], ['error', 'ok'])

    def test_page_timeout_is_bounded_and_next_page_can_complete(self):
        calls = []
        class Hanging:
            returncode = None
            def poll(self):
                return self.returncode
        hanging = Hanging()
        def run(command, **kwargs):
            request = json.loads(Path(command[-1]).read_text(encoding='utf-8'))
            calls.append(request['pages'])
            if len(calls) > 1:
                return self.fake_completed_process(command, **kwargs)
            (Path(request['run_dir'])/'progress.json').write_text(json.dumps({'phase': 'page', 'page': 1}))
            return hanging
        def stop(process):
            process.returncode = -1
        with patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=run), \
                patch('P2_nlp_extraction.ocr_pipeline.api._stop', side_effect=stop) as stopped:
            result = extract_pdf(self.make_pdf(), self.folder/'timeout_output', pages=[1, 2], page_timeout_seconds=.001)
        self.assertTrue(stopped.called)
        self.assertEqual(result['attempts'][0]['interruption'], 'page_timeout')
        self.assertEqual(result['pages'][1]['status'], 'ok')

    def test_raise_mode_exports_errors_before_raising(self):
        class Broken(FakeModels):
            def detect(self, image):
                raise RuntimeError('synthetic error for raise mode')
        def run(command, **kwargs):
            request = json.loads(Path(command[-1]).read_text(encoding='utf-8'))
            process_document(request, backend_factory=Broken)
            class Finished:
                returncode = 0
                def poll(self):
                    return self.returncode
            return Finished()
        with patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=run):
            with self.assertRaises(OCRPipelineError) as raised:
                extract_pdf(self.make_pdf(), self.folder/'raise_output', pages=[1, 2], on_error='raise')
        self.assertTrue(Path(raised.exception.result['exports']['json']).is_file())
        self.assertTrue(raised.exception.result['pages'][0]['errors'])


if __name__ == '__main__':
    unittest.main()
