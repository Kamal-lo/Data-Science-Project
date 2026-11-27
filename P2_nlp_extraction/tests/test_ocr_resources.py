"""Real Windows process limits tested with tiny synthetic PDFs and fake engines."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import uuid
from unittest.mock import patch
from types import SimpleNamespace

from conversion_fixtures import ConversionCase, pdf_bytes
from P2_nlp_extraction.ocr_pipeline import extract_pdf
from P2_nlp_extraction.ocr_pipeline.resources import ResourceProtectionError, WindowsJob, join_job
from P2_nlp_extraction.document_conversion import ConversionOptions


@unittest.skipUnless(os.name == 'nt', 'Windows Job Object integration requires Windows')
class ProcessResourceTests(ConversionCase):
    def run_scenario(self, scenario, *, pages=1, fallback_timeout=1.5):
        self.ingestion(pdf_bytes(tuple('scan' for _ in range(pages))))
        source = self.manifest.parent/self.item['artifact_path']
        original_popen = subprocess.Popen
        def fake_engine(command, **kwargs):
            command = list(command)
            command[command.index('P2_nlp_extraction.ocr_pipeline.worker')] = 'P2_nlp_extraction.tests.resource_worker_fixture'
            return original_popen(command, **kwargs)
        with patch.dict(os.environ, {'P2_TEST_RESOURCE_SCENARIO': scenario}), \
                patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=fake_engine):
            result = extract_pdf(source, self.folder/'ocr', pages=list(range(1, pages+1)),
                                 fallback_timeout_seconds=fallback_timeout, arabic_spacing='off',
                                 max_worker_memory_bytes=384*1024**2, timeout_seconds=40,
                                 initialization_timeout_seconds=15, page_timeout_seconds=15)
        self.result, self.run_dir = result, Path(result['run_directory'])
        return result

    def assert_tree_gone(self):
        import psutil
        for filename in ('fixture_process.json', 'fixture_child.json'):
            p = self.run_dir/filename
            if p.exists():
                pid = json.loads(p.read_text())['pid']
                until = time.monotonic()+3
                while psutil.pid_exists(pid) and time.monotonic()<until: time.sleep(.02)
                self.assertFalse(psutil.pid_exists(pid), f'Orphan process {pid}')

    def test_normal_fallback_under_hard_memory_guard(self):
        result = self.run_scenario('normal')
        self.assertEqual(result['status'], 'completed_with_review')
        block = result['pages'][0]['blocks'][0]
        self.assertTrue(block['fallback_used'])
        self.assertEqual(block['raw_text'], 'recovered text')
        self.assertEqual(len(block['recognition_attempts']), 2)
        resources = result['attempts'][0]['resources']
        self.assertGreater(resources['peak_job_memory_bytes'], 0)
        self.assertFalse(resources['memory_limit_hit'])
        self.assert_tree_gone()

    def test_blocked_native_attempt_is_terminated_and_primary_retained(self):
        started = time.monotonic()
        result = self.run_scenario('blocked')
        self.assertLess(time.monotonic()-started, 25)
        self.assertEqual(result['attempts'][0]['interruption'], 'fallback_timeout')
        page = result['pages'][0]
        self.assertEqual(page['status'], 'needs_review')
        self.assertEqual(result['status'], 'partial')
        block = page['blocks'][0]
        self.assertEqual(block['recognition_attempts'][0]['result']['recognition_candidates']['fr']['text'], 'weak primary')
        self.assertIsNone(block['recognition_attempts'][1]['result'])
        self.assertEqual(page['fallback_interruption']['interruption'], 'fallback_timeout')
        saved = json.loads(Path(result['exports']['json']).read_text(encoding='utf-8'))
        self.assertEqual(saved['pages'][0]['fallback_interruption'], page['fallback_interruption'])
        self.assert_tree_gone()

    def test_memory_allocation_is_denied_and_diagnosed(self):
        result = self.run_scenario('memory', fallback_timeout=5)
        self.assertEqual(result['attempts'][0]['interruption'], 'memory_limit')
        resources = result['attempts'][0]['resources']
        self.assertTrue(resources['memory_limit_hit'])
        # Windows peak accounting may include the rejected charge. The allocation
        # return value, not that peak counter, demonstrates rejection.
        self.assertEqual(resources['limit_bytes'], 384*1024**2)
        self.assertTrue(result['pages'][0]['blocks'][0]['recognition_attempts'])
        self.assert_tree_gone()

    def test_descendant_killed_and_unrelated_process_preserved(self):
        unrelated = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(60)'])
        try:
            self.run_scenario('descendant')
            self.assertTrue((self.run_dir/'fixture_child.json').exists())
            self.assert_tree_gone()
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.kill(); unrelated.wait(timeout=5)

    def test_memory_cap_inherited_by_child(self):
        result = self.run_scenario('child_memory', fallback_timeout=6)
        self.assertEqual(result['attempts'][0]['interruption'], 'memory_limit')
        self.assertTrue(result['attempts'][0]['resources']['memory_limit_hit'])
        self.assertTrue((self.run_dir/'fixture_child.json').exists())
        self.assert_tree_gone()

    def test_kernel_refuses_allocation_before_supervisor_termination(self):
        name, limit = 'Local\\p2_mem_test_' + uuid.uuid4().hex, 384*1024**2
        code = ('from pathlib import Path; '
                'from P2_nlp_extraction.ocr_pipeline.resources import join_job; '
                'from P2_nlp_extraction.tests.resource_worker_fixture import memory_probe; '
                'import sys; join_job(sys.argv[1]); memory_probe(int(sys.argv[2]),Path(sys.argv[3]))')
        with WindowsJob(name, limit) as job:
            process = subprocess.Popen([sys.executable, '-B', '-c', code, name, str(limit), str(self.folder)])
            try:
                self.assertEqual(process.wait(timeout=15), 0)
                self.assertTrue(json.loads((self.folder/'allocation.json').read_text())['denied'])
                self.assertTrue(job.snapshot()['memory_limit_hit'])
            finally:
                if process.poll() is None: job.terminate(); process.wait(timeout=5)

    def test_timeout_does_not_restart_completed_or_unrequested_pages(self):
        result = self.run_scenario('first_page_blocked', pages=2)
        self.assertEqual([p['page'] for p in result['pages']], [1, 2])
        self.assertTrue(result['pages'][0]['errors'])
        self.assertEqual(result['pages'][1]['status'], 'needs_review')
        self.assertEqual(len(result['attempts']), 2)
        self.assertEqual(json.loads((self.run_dir/'request_2.json').read_text())['pages'], [2])

    def test_guard_failure_exports_diagnostics_without_starting_worker(self):
        p = self.folder/'source.pdf'; p.write_bytes(pdf_bytes(('scan',)))
        with patch('P2_nlp_extraction.ocr_pipeline.api.WindowsJob', side_effect=ResourceProtectionError('synthetic job failure')), \
                patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen') as launch:
            result = extract_pdf(p, self.folder/'guard_failure', pages=[1])
        launch.assert_not_called()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'][0]['stage'], 'resource_guard')
        self.assertTrue((Path(result['run_directory'])/'resource_guard_failure.json').exists())

    def test_memory_notification_at_exit_marks_completed_checkpoint_partial(self):
        from test_automatic_pipeline import FakeModels
        from P2_nlp_extraction.ocr_pipeline.worker import process_document
        p = self.folder/'source.pdf'; p.write_bytes(pdf_bytes(('scan',)))
        def immediate(command, **kwargs):
            request = json.loads(Path(command[-1]).read_text())
            process_document(request, backend_factory=FakeModels)
            return SimpleNamespace(returncode=0, poll=lambda: 0)
        with patch('P2_nlp_extraction.ocr_pipeline.api.subprocess.Popen', side_effect=immediate), \
                patch.object(WindowsJob, 'snapshot', return_value={'memory_limit_hit': True}):
            result = extract_pdf(p, self.folder/'exit_race', pages=[1], arabic_spacing='off')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['errors'][0]['type'], 'memory_limit')
        self.assertTrue(result['pages'][0]['blocks'])

    def test_late_completed_result_is_not_selected_if_supervisor_has_not_polled(self):
        from test_ocr_recovery import SequenceRecognizer, candidates
        from P2_nlp_extraction.ocr_pipeline.worker import process_document
        clock = [0.0]
        class Models(SequenceRecognizer):
            metadata = {'synthetic': True}
            initialization_seconds = 0
            def __init__(self, **kwargs):
                super().__init__([candidates('weak', .2), candidates('late result', .98)])
            def detect(self, image): return ([[[10,10],[200,10],[200,40],[10,40]]], [.9])
            def crop(self, image, polygon): return image[10:40,10:200].copy()
            def recognize(self, image, language):
                if len(self.calls) >= 2: clock[0] += 1
                return super().recognize(image, language)
        source = self.folder/'late.pdf'; source.write_bytes(pdf_bytes(('scan',)))
        folder = self.folder/'late_result'
        request = {'pdf_path':str(source),'run_dir':str(folder),'pages':[1],'dpi':200,
                   'max_pixels':2000000,'cpu_threads':1,'arabic_spacing':'off','on_error':'continue',
                   'fallback_mode':'preprocess','fallback_timeout_seconds':.1}
        with patch('P2_nlp_extraction.ocr_pipeline.worker.monotonic', side_effect=lambda: clock[0]):
            process_document(request, backend_factory=Models)
        page = json.loads((folder/'pages/page_001.json').read_text(encoding='utf-8'))
        self.assertEqual(page['fallback_interruption']['outcome'], 'late_result_not_selected')
        self.assertEqual(page['status'], 'needs_review')
        self.assertFalse(page['blocks'][0]['fallback_used'])
        self.assertTrue(page['blocks'][0]['fallback_attempted'])
        self.assertIsNone(page['blocks'][0]['raw_text'])
        self.assertEqual(page['blocks'][0]['recognition_attempts'][1]['result']['raw_text'], 'late result')

    def test_interrupted_result_accepted_by_t24_with_provenance(self):
        result = self.run_scenario('blocked')
        converted = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(result['exports']['json'],)))
        self.assertIn(converted['status'], ('partial', 'completed_with_review'))
        block = converted['blocks'][0]
        self.assertEqual(block['bbox'], result['pages'][0]['blocks'][0]['bbox_pdf_points'])
        self.assertEqual(len(block['ocr_recovery']['recognition_attempts']), 2)
        self.assertFalse(block['human_validated'])
        self.assertTrue(Path(converted['markdown_path']).is_file())

    def test_invalid_job_membership_fails_before_inference(self):
        with self.assertRaises(ResourceProtectionError): join_job('Local\\nonexistent_p2_job_123456')

    def test_bad_memory_limit_rejected(self):
        for value in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError): WindowsJob('Local\\unused', value)


class PortableProtectionTests(unittest.TestCase):
    def test_unsupported_platform_fails_closed(self):
        with patch('P2_nlp_extraction.ocr_pipeline.resources.os.name', 'posix'):
            with self.assertRaises(ResourceProtectionError): WindowsJob('unused', 1024)
