"""Failure diagnosis with fake predictors and a Windows native import check."""
import copy
import hashlib
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from conversion_fixtures import ConversionCase, pdf_bytes
from P2_nlp_extraction.document_conversion import ConversionOptions
from P2_nlp_extraction.ocr_pipeline.api import _native_diagnostics
from P2_nlp_extraction.ocr_pipeline.models import LocalModels, MODEL_NAMES, DETECTION_SETTINGS
from P2_nlp_extraction.ocr_pipeline.resources import memory_sample
from P2_nlp_extraction.ocr_pipeline.worker import process_document


@unittest.skipUnless(os.name == 'nt' and importlib.util.find_spec('paddle'),
                     'Requires the Windows PaddleOCR environment.')
class NativeRuntimeTests(unittest.TestCase):
    def test_libpaddle_import_without_developer_path(self):
        # A developer shell can supply VCOMP140.DLL even when Streamlit cannot.
        with tempfile.TemporaryDirectory() as profile:
            env = dict(os.environ, PATH=str(Path(os.environ['SystemRoot']) / 'System32'),
                       USERPROFILE=profile)
            result = subprocess.run(
                [sys.executable, '-I', '-B', '-c', 'from paddle.base import libpaddle'],
                cwd=profile, env=env, capture_output=True, timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))


class LoadingTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.events = [], []
        self.fail = None
        def factory(**kwargs):
            self.calls.append(kwargs)
            key = next(k for k, n in MODEL_NAMES.items() if n == kwargs['model_name'])
            if key == self.fail: raise MemoryError('synthetic model allocation denied')
            def predict(image):
                return iter([{'dt_polys': [], 'dt_scores': []} if key == 'det' else
                             {'rec_text': 'texte' if key == 'fr' else 'نص', 'rec_score': .95}])
            return predict
        option = lambda **kwargs: SimpleNamespace(copy=lambda: dict(kwargs))
        metadata = {'paths': {k: 'synthetic_local_' + k for k in MODEL_NAMES},
                    'models': [], 'versions': {}, 'downloads': False}
        for target, value in (
            ('preflight', lambda: copy.deepcopy(metadata)), ('configure_cache', lambda: None),
            ('_predictor_components', lambda: (factory, option, lambda **kwargs: None))):
            patched = patch('P2_nlp_extraction.ocr_pipeline.models.' + target, new=value)
            patched.start(); self.addCleanup(patched.stop)

    def backend(self):
        return LocalModels(cpu_threads=2, observer=lambda stage, details: self.events.append((stage, details)))

    def test_detection_loads_only_mobile_detector(self):
        import numpy as np
        backend = self.backend()
        backend.detect(np.zeros((32, 64, 3), dtype=np.uint8))
        self.assertEqual(list(backend.models), ['det'])
        self.assertEqual(backend.metadata['model_load_counts'], {'det':1, 'fr':0, 'ar':0})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]['model_name'], 'PP-OCRv5_mobile_det')
        for name, value in DETECTION_SETTINGS.items(): self.assertEqual(self.calls[0][name], value)
        self.assertEqual([stage for stage, _ in self.events],
                         ['model_load_before','model_load_after','detection_before','detection_after'])

    def test_recognizers_loaded_once_and_reused_on_subsequent_pages(self):
        import numpy as np
        backend = self.backend(); image = np.zeros((32,64,3), dtype=np.uint8)
        for _ in range(3):
            backend.detect(image)
            self.assertEqual(backend.recognize(image,'fr')['text'], 'texte')
            self.assertEqual(backend.recognize(image,'ar')['text'], 'نص')
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(backend.metadata['model_load_counts'], {'det':1,'fr':1,'ar':1})
        self.assertTrue(all(c['device']=='cpu' and c['batch_size']==1 for c in self.calls))
        self.assertEqual(backend.metadata['parameters']['recognizer_loading'], 'lazy_once')

    def test_failed_load_is_not_repeated_per_block(self):
        backend=self.backend(); self.fail='fr'
        with self.assertRaises(MemoryError): backend.recognize(None, 'fr')
        with self.assertRaises(RuntimeError): backend.recognize(None, 'fr')
        self.assertEqual(len(self.calls),2)
        self.assertEqual(backend.metadata['model_load_counts']['fr'],1)
        self.assertEqual(backend.metadata['model_load_events'][-1]['status'],'error')
        self.assertNotIn('fr',backend.models)

    def test_unknown_language_never_loads_any_model(self):
        backend=self.backend()
        with self.assertRaises(ValueError): backend.recognize(None,'unknown')
        self.assertEqual(len(self.calls),1)

    def test_small_detector_profile_is_scoped_and_legacy_profile_unchanged(self):
        import numpy as np
        image = np.zeros((2339,1654,3), dtype=np.uint8)
        backend = LocalModels(cpu_threads=2, detector_max_side=1280)
        backend.detect(image)
        self.assertEqual(image.shape, (2339,1654,3))
        self.assertEqual(self.calls[0]['limit_type'],'max')
        self.assertEqual(self.calls[0]['limit_side_len'],1280)
        self.assertEqual(self.calls[0]['max_side_limit'],1280)
        self.assertEqual(backend.metadata['parameters']['detection']['limit_side_len'],1280)
        self.assertEqual(DETECTION_SETTINGS['limit_type'],'min')
        self.assertEqual(backend.metadata['model_load_counts'],{'det':1,'fr':0,'ar':0})

    def test_invalid_detector_size_rejected(self):
        for value in (True, 0, 4096, 1280.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LocalModels(detector_max_side=value)

    def test_installed_resize_geometry_without_loading_paddle(self):
        # Exercise the installed resize class alone, without importing PaddleX,
        # constructing a predictor or loading any model.
        import ast
        import cv2
        import numpy as np
        from P2_nlp_extraction.scripts.ocr_common import ROOT
        source = ROOT / '.venv/Lib/site-packages/paddlex/inference/models/text_detection/processors.py'
        if not source.exists():
            self.skipTest('Local PaddleX source not installed on this machine.')
        tree=ast.parse(source.read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=='DetResizeForTest')
        node.decorator_list = []
        from typing import Union
        namespace=dict(np=np,cv2=cv2,Union=Union)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        image=np.zeros((2339,1654,3),dtype=np.uint8)
        resize=namespace['DetResizeForTest'](limit_side_len=1280,limit_type='max',max_side_limit=1280)
        resized,shape=resize.resize(image,1280,'max',1280)
        self.assertEqual(resized.shape[:2],(1280,896))
        self.assertEqual(list(shape[:2]),[2339,1654])
        self.assertAlmostEqual(shape[2],1280/2339)
        self.assertAlmostEqual(shape[3],896/1654)
        self.assertEqual(image.shape,(2339,1654,3))


class NativeDiagnosisTests(unittest.TestCase):
    def test_signed_and_unsigned_access_violation_codes(self):
        for code in (-1073741819,3221225477):
            diagnostic=_native_diagnostics(code,'')
            self.assertTrue(diagnostic['access_violation_reported'])
            self.assertEqual(diagnostic['final_exit_code'],code)
            self.assertEqual(diagnostic['memory_crash_causality'],'not_established')

    def test_supervisor_exit_code_does_not_hide_faulthandler_evidence(self):
        d=_native_diagnostics(1,'Windows fatal exception: access violation',supervisor_terminated=True)
        self.assertEqual(d['evidence'],['faulthandler_log'])
        self.assertTrue(d['supervisor_terminated'])
        self.assertIsNone(d['exit_code_before_supervisor_termination'])

    def test_no_native_crash_invented_from_memory_stop(self):
        d=_native_diagnostics(1,'',supervisor_terminated=True)
        self.assertFalse(d['access_violation_reported'])

    def test_exit_observed_before_termination_is_preserved(self):
        d=_native_diagnostics(1,'',supervisor_terminated=True,observed_exit_code=-1073741819)
        self.assertEqual(d['evidence'],['windows_exception_exit_code'])
        self.assertEqual(d['exit_code_before_supervisor_termination'],-1073741819)

    def test_memory_sample_reports_metrics_without_claiming_total_rss_limit(self):
        sample=memory_sample('test', model_key='det')
        self.assertGreater(sample['rss_bytes'],0)
        self.assertIn('private_bytes',sample)
        self.assertEqual(sample['model_key'],'det')
        self.assertGreater(sample['total_physical_bytes'],0)


class FailureProvenanceTests(ConversionCase):
    def cache(self, *, blocks=False, status='error'):
        self.ingestion(pdf_bytes(('scan',)))
        path=self.mock_ocr()
        data=json.loads(path.read_text(encoding='utf-8'))
        data.update(status='failed', resource_policy={'memory_limit_bytes':1610612736},
                    attempts=[{'native_diagnostics':{'access_violation_reported':True},
                               'resources':{'memory_limit_hit':True}}],
                    errors=[{'stage':'native','message':'simulated access violation'}])
        page=data['pages'][0]
        page.update(status=status, errors=[{'stage':'worker','message':'memory_limit'}],
                    warnings=['synthetic_warning_preserved'],
                    memory_events=[{'stage':'detection_before','private_bytes':1234}])
        if not blocks: page['blocks']=[]
        path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        self.raw=data
        return path

    def test_empty_failure_keeps_source_hash_warnings_and_runtime_provenance(self):
        path=self.cache()
        result=self.convert(options=ConversionOptions(ocr_mode='reuse_only',ocr_results=(str(path),)))
        self.assertEqual(result['status'],'partial')
        page=result['pages'][0];provenance=page['ocr_provenance']
        self.assertEqual(provenance['ocr_json_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(provenance['ocr_run_id'],self.raw['run_id'])
        self.assertEqual(provenance['ocr_runtime']['attempts'],self.raw['attempts'])
        self.assertEqual(provenance['memory_events'],self.raw['pages'][0]['memory_events'])
        self.assertIn('synthetic_warning_preserved',page['warnings'])
        self.assertEqual(page['status'],'ocr_incomplete')
        self.assertFalse(result['blocks'])
        self.assertNotIn(str(self.folder),json.dumps(json.loads(Path(result['document_json_path']).read_text(encoding='utf-8'))))

    def test_error_page_retains_valid_partial_blocks_as_unvalidated(self):
        path=self.cache(blocks=True)
        result=self.convert(options=ConversionOptions(ocr_mode='reuse_only',ocr_results=(str(path),)))
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['pages'][0]['status'],'ocr_incomplete')
        self.assertEqual(result['blocks'][0]['raw_text'],'نص عربي')
        self.assertEqual(result['blocks'][0]['bbox'],self.raw['pages'][0]['blocks'][0]['bbox_pdf_points'])
        self.assertFalse(result['blocks'][0]['human_validated'])
        self.assertIn('recognition_candidates',result['blocks'][0])
        self.assertTrue(result['pages'][0]['ocr_provenance'])

    def test_no_text_detection_keeps_provenance_too(self):
        path=self.cache(status='no_text_detected')
        result=self.convert(options=ConversionOptions(ocr_mode='reuse_only',ocr_results=(str(path),)))
        self.assertEqual(result['status'],'partial')
        self.assertTrue(result['pages'][0]['ocr_provenance'])

    def test_native_failure_after_render_keeps_geometry_checkpoint(self):
        from test_automatic_pipeline import FakeModels
        class SimulatedNativeAbort(BaseException): pass
        class Backend(FakeModels):
            def detect(self,image): raise SimulatedNativeAbort()
        source=self.folder/'scan.pdf';source.write_bytes(pdf_bytes(('scan',)))
        folder=self.folder/'native_checkpoint'
        request={'pdf_path':str(source),'run_dir':str(folder),'pages':[1],'dpi':200,
                 'max_pixels':2000000,'cpu_threads':2,'arabic_spacing':'off','on_error':'continue'}
        with self.assertRaises(SimulatedNativeAbort): process_document(request,backend_factory=Backend)
        page=json.loads((folder/'pages/page_001.json').read_text(encoding='utf-8'))
        self.assertEqual(page['dpi'],200)
        self.assertEqual(len(page['pdf_rect']),4)
        self.assertTrue(page['image_size'])
        self.assertTrue(any(e['stage']=='primary_detection_before' for e in page['memory_events']))
