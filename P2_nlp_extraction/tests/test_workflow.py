"""T09/T35/T95 : composants réels sur petites fixtures ; aucun moteur OCR réel."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from conversion_fixtures import pdf_bytes, docx_bytes, zip_bytes
from segmentation_fixtures import ROOT, temporary_folder
from P2_nlp_extraction import pipeline
from P2_nlp_extraction.document_conversion import ConversionLimits, ConversionOptions
from P2_nlp_extraction.document_ingestion import IngestionLimits
from P2_nlp_extraction.storage import store_document, resolve_document, output_path
from P2_nlp_extraction.app import process_upload, download_bytes


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = temporary_folder(self)
        self.source = self.folder / 'DCE français عربي.pdf'
        self.source.write_bytes(pdf_bytes(table=True))

    def run_pipeline(self, source=None, **kwargs):
        # Toute activation accidentelle de PaddleOCR ferait échouer le test.
        with patch('P2_nlp_extraction.ocr_pipeline.extract_pdf', side_effect=AssertionError('OCR réel interdit')):
            return pipeline.run_pipeline(source or self.source, self.folder / 'runs', **kwargs)

    def test_storage_identity_unicode_deduplication_and_portable_contract(self):
        first = store_document(self.source, directory=self.folder / 'library')
        second = store_document(self.source, directory=self.folder / 'library')
        self.assertEqual(first, second)
        self.assertEqual(first['original_name'], self.source.name)
        self.assertFalse(Path(first['artifact_path']).is_absolute())
        self.assertEqual(resolve_document(first).read_bytes(), self.source.read_bytes())
        self.assertEqual(len(list((self.folder / 'library').rglob('*.pdf'))), 1)

    def test_storage_size_limit_cleans_only_owned_temporary(self):
        marker = self.folder / 'library/keep.txt'
        marker.parent.mkdir();marker.write_text('keep',encoding='utf-8')
        with self.assertRaises(ValueError):
            store_document(self.source, directory=marker.parent, max_bytes=8)
        self.assertEqual([p.name for p in marker.parent.iterdir()], ['keep.txt'])

    def test_storage_tampering_and_untrusted_paths_rejected(self):
        record = store_document(self.source, directory=self.folder / 'library')
        modified = dict(record, artifact_path='../README.md')
        with self.assertRaises(ValueError):resolve_document(modified)
        modified = dict(record, sha256='0'*64)
        with self.assertRaises(ValueError):resolve_document(modified)
        target = resolve_document(record);target.write_bytes(b'changed')
        with self.assertRaises(ValueError):resolve_document(record)
        with self.assertRaises(ValueError):store_document(self.source,directory=self.folder/'library')

    def test_new_outputs_cannot_overwrite_code_or_other_modules(self):
        for path in (ROOT/'pipeline.py', ROOT/'data', ROOT.parent/'P5_frontend_interface'):
            with self.subTest(path=path), self.assertRaises(ValueError):output_path(path)

    def test_native_pdf_complete_pipeline_exports_and_resumable_job(self):
        events=[]
        job=self.run_pipeline(progress=events.append)
        self.assertEqual(job['status'],'completed_with_review')
        self.assertEqual(job['integrations']['team_backend'],'not_connected')
        self.assertEqual(len(job['documents']),1)
        document=job['documents'][0]
        self.assertEqual(document['source']['original_name'],self.source.name)
        self.assertEqual(set(document['outputs']),{'document_json','document_md','sections_json','sections_md',
                                                   'tables_json','tables_csv','bpu_json','bpu_csv'})
        self.assertEqual(pipeline.load_job(job['job_path']),job)
        self.assertEqual(events[-1]['status'],job['status'])
        self.assertTrue(any(e['status']=='processing' for e in events))
        tables=json.loads(download_bytes(document['outputs']['tables_json']))
        self.assertEqual(len(tables['tables']),1)
        values=[[c['value'] for c in r['cells']] for r in tables['tables'][0]['rows']]
        self.assertEqual(values,[['Article','Prix'],['Travaux','12000']])
        self.assertEqual(document['quality'][0]['ocr_status'],{'fr':'not_evaluated','ar':'not_evaluated'})

    def test_real_docx_parser_and_bpu_end_to_end(self):
        from docx import Document
        source=self.folder/'BPU.docx'
        document=Document();document.add_heading('Bordereau des prix unitaires',1)
        table=document.add_table(rows=2,cols=6)
        matrix=[['N° de prix','Désignation','Unité','Quantité','Prix unitaire','Montant'],
                ['01','Béton — خرسانة','m³','2,5','100,20','250,50']]
        for row,values in zip(table.rows,matrix):
            for cell,value in zip(row.cells,values):cell.text=value
        document.save(source)
        job=self.run_pipeline(source)
        item=job['documents'][0]
        bpu=json.loads(download_bytes(item['outputs']['bpu_json']))
        self.assertEqual(len(bpu['tables']),1)
        self.assertEqual(bpu['tables'][0]['classification'],'bpu')
        self.assertEqual(bpu['tables'][0]['source_block']['method'],'docx_xml')
        self.assertEqual(len(bpu['tables'][0]['price_lines']),1)
        self.assertEqual(bpu['tables'][0]['price_lines'][0]['fields']['amount']['value'],'250,50')
        self.assertIn('خرسانة',download_bytes(item['outputs']['bpu_csv']).decode('utf-8-sig'))

    def test_zip_with_pdf_and_docx_uses_real_components(self):
        source=self.folder/'lot.zip'
        scan = pdf_bytes(kinds=('scan',))
        cache = self.folder/'scan-ocr.json'
        cache.write_text(json.dumps({
            'schema_version': 'p2.automatic_ocr.v1', 'pdf_sha256': hashlib.sha256(scan).hexdigest(),
            'selected_pages': [1], 'pages': [{'page': 1, 'dpi': 200, 'status': 'needs_review',
                'blocks': [{'block_id': 'ocr_1', 'raw_text': 'نص عربي', 'language': 'ar',
                            'bbox_pdf_points': [30, 25, 120, 60]}]}],
        }), encoding='utf-8')
        source.write_bytes(zip_bytes([('lot/DCE.pdf',pdf_bytes()),('pièces/عقد.docx',docx_bytes()),
                                      ('lot/scan.pdf', scan),
                                      ('notes.txt', b'Format non pris en charge')]))
        checkpoints = []
        job=self.run_pipeline(source, options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)),
                              progress=checkpoints.append)
        self.assertEqual(len(job['documents']),3)
        self.assertEqual({d['source']['detected_type'] for d in job['documents']},{'pdf','docx'})
        self.assertTrue(all(d['outputs']['document_json'] for d in job['documents']))
        self.assertEqual(job['status'], 'partial')
        self.assertTrue(any('notes.txt' in warning for warning in job['warnings']))
        checkpoint = next(event for event in checkpoints if event['status'] == 'processing' and
                          any(entry.get('finished') and entry['status'].startswith('completed')
                              for entry in event['documents']))
        interrupted_path = self.folder / 'job.json'
        interrupted_path.write_text(json.dumps(checkpoint), encoding='utf-8')
        with patch.object(pipeline, 'convert_ingestion', wraps=pipeline.convert_ingestion) as convert:
            recovered = pipeline.resume_job(interrupted_path)
        skipped = {entry['document_id'] for entry in recovered['documents']
                   if entry['member_id'] in recovered['resume']['reused']}
        self.assertTrue(skipped)
        converted = {file_id for call in convert.call_args_list for file_id in call.kwargs['file_ids']}
        self.assertFalse(skipped & converted)
        resumed = pipeline.resume_job(job['job_path'])
        self.assertEqual(resumed['status'], 'partial')
        self.assertIn('resumed_from:'+job['job_path'], resumed['warnings'])
        self.assertTrue(resumed['resume']['reused'])
        self.assertEqual(pipeline.load_job(resumed['job_path']), resumed)
        self.assertEqual(pipeline.load_delivery(resumed['job_path']), resumed)
        for member in resumed['documents']:
            original = pipeline.resolve_member_source(resumed['job_path'], member['member_id'])
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), member['source']['sha256'])
        with self.assertRaises(ValueError):
            pipeline.resolve_member_source(resumed['job_path'], 'unknown')
        tampered = copy.deepcopy(resumed)
        tampered['documents'][0]['member_id'] = '0' * 64
        invalid_delivery = self.folder / 'tampered' / 'job.json'
        invalid_delivery.parent.mkdir()
        invalid_delivery.write_text(json.dumps(tampered), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Identité du membre'):
            pipeline.load_delivery(invalid_delivery)
        swapped = copy.deepcopy(resumed)
        first, second = swapped['documents'][:2]
        first['outputs']['tables_json'] = second['outputs']['tables_json']
        invalid_delivery.write_text(json.dumps(swapped), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'export dérivé'):
            pipeline.load_delivery(invalid_delivery)
        swapped = copy.deepcopy(resumed)
        first, second = swapped['documents'][:2]
        first['outputs']['tables_csv'] = second['outputs']['bpu_csv']
        invalid_delivery.write_text(json.dumps(swapped), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'CSV ne correspond pas'):
            pipeline.load_delivery(invalid_delivery)
        old_exports = {d['member_id']: d['outputs'] for d in job['documents']}
        for document in resumed['documents']:
            conversion = json.loads(download_bytes(document['outputs']['document_json']))
            has_ocr = any(block['method'] == 'ocr' for block in conversion['blocks'])
            self.assertEqual(has_ocr, document['source']['relative_path'] == 'lot/scan.pdf')
            self.assertFalse(conversion['errors'])
            if document['member_id'] in resumed['resume']['reused']:
                self.assertEqual(document['outputs'], old_exports[document['member_id']])
        replacement = self.folder / 'revision.zip'
        replacement.write_bytes(zip_bytes([('lot/DCE.pdf', pdf_bytes(table=True)),
                                           ('nouveau.docx', docx_bytes())]))
        revised = pipeline.resume_job(job['job_path'], source_path=replacement)
        self.assertEqual(revised['resume']['changes'], {
            'added': ['nouveau.docx'], 'modified': ['lot/DCE.pdf'],
            'removed': ['lot/scan.pdf', 'notes.txt', 'pièces/عقد.docx'],
        })

    def test_partial_scan_never_claims_success_or_metric(self):
        self.source.write_bytes(pdf_bytes(kinds=('scan',)))
        job=self.run_pipeline(options=ConversionOptions(ocr_mode='never',pdf_pages=(1,)))
        self.assertEqual(job['status'],'partial')
        conversion=json.loads(download_bytes(job['documents'][0]['outputs']['document_json']))
        self.assertEqual(conversion['coverage']['processed_pages'],[1])
        self.assertTrue(conversion['errors'])
        self.assertTrue(all(v=='not_evaluated' for v in job['documents'][0]['quality'][0]['ocr_status'].values()))

    def test_all_conversions_failed_is_failed_not_success(self):
        source=self.folder/'document.docx';source.write_bytes(docx_bytes())
        job=self.run_pipeline(source,options=ConversionOptions(ocr_mode='never',pdf_pages=(1,)))
        self.assertEqual(job['status'],'failed')
        self.assertTrue(job['documents'])
        self.assertEqual(job['documents'][0]['status'],'failed')
        conversion=json.loads(download_bytes(job['documents'][0]['outputs']['document_json']))
        self.assertIn('docx_pages_unavailable',[e['code'] for e in conversion['errors']])

    def test_recorded_real_page_one_reused_without_loading_models(self):
        from contextlib import chdir
        cached=ROOT/'outputs/ocr/automatic_sample/20261118T221046_740048Z_de048b93/document.json'
        source=ROOT/'data/pdf/test_dce.pdf'
        if not cached.exists() or not source.exists():self.skipTest('Données réelles locales non distribuées.')
        cache_path = cached.relative_to(ROOT).as_posix()
        with chdir(self.folder):
            job=self.run_pipeline(source,options=ConversionOptions(ocr_mode='reuse_only',pdf_pages=(1,),
                                                                   ocr_results=(cache_path,)),
                                  reference_manifest_path=ROOT/'data/ground_truth/pages_1_2/manifest.json')
        self.assertEqual(job['options']['ocr_results'], [cache_path])
        document=job['documents'][0]
        conversion=json.loads(download_bytes(document['outputs']['document_json']))
        self.assertEqual(conversion['coverage']['processed_pages'],[1])
        self.assertEqual(len(conversion['blocks']),17)
        self.assertTrue(any(b['language']=='ar' for b in conversion['blocks']))
        self.assertTrue(any(b['language']=='fr' for b in conversion['blocks']))
        metrics=json.loads(download_bytes(document['quality'][0]['outputs']['ocr_metrics.json']))
        record=next(r for r in metrics['records'] if r['page']==1 and r['language']=='fr')
        self.assertEqual(record['metrics']['total_errors'],8)
        self.assertEqual(record['metrics']['reference_characters'],554)
        self.assertEqual(job['status'],'partial')

    def test_corrupt_input_and_missing_source_preserve_failed_job(self):
        for contents in (b'not a PDF',None):
            if contents is None:self.source.unlink()
            else:self.source.write_bytes(contents)
            job=self.run_pipeline()
            self.assertEqual(job['status'],'failed')
            self.assertTrue(any(s['status'] in ('failed','rejected','completed_with_issues') or s['errors'] for s in job['steps'])
                            or 'ingestion_no_eligible_document' in job['warnings'])
            self.assertEqual(pipeline.load_job(job['job_path']),job)

    def test_downstream_error_preserves_conversion_and_other_exports(self):
        with patch.object(pipeline,'segment_document',side_effect=ValueError('synthetic failure')):
            job=self.run_pipeline()
        self.assertEqual(job['status'],'partial')
        self.assertIn('document_json',job['documents'][0]['outputs'])
        self.assertIn('tables_json',job['documents'][0]['outputs'])
        self.assertTrue(any(s['errors'] for s in job['steps']))

    def test_progress_callback_cannot_mutate_job_or_prevent_completion(self):
        def progress(job):
            job['documents'].clear()
            raise RuntimeError('UI disconnected')
        job=self.run_pipeline(progress=progress)
        self.assertEqual(len(job['documents']),1)
        self.assertIn('progress_callback_failed',job['warnings'])

    def test_parallel_job_refused_and_lock_released_after_bad_source(self):
        with pipeline._RUN_LOCK:
            with self.assertRaises(RuntimeError):self.run_pipeline()
        job=self.run_pipeline(self.folder/'missing.pdf')
        self.assertEqual(job['status'],'failed')
        self.assertFalse(pipeline._RUN_LOCK.locked())

    def test_final_callback_failure_is_persisted_and_does_not_hide_results(self):
        def progress(job):
            if job['status']!='processing':raise RuntimeError('Final UI callback failed')
        job=self.run_pipeline(progress=progress)
        self.assertIn('progress_callback_failed',job['warnings'])
        self.assertEqual(pipeline.load_job(job['job_path']),job)
        self.assertTrue(job['documents'][0]['outputs'])

    def test_download_refuses_changed_export_or_path_escape(self):
        path=self.folder/'export.md';path.write_text('Original',encoding='utf-8')
        entry=pipeline._exports({'md':path})['md']
        self.assertEqual(download_bytes(entry),b'Original')
        path.write_text('Changed!',encoding='utf-8')
        with self.assertRaises(ValueError):download_bytes(entry)
        with self.assertRaises(ValueError):download_bytes(dict(entry,path='../README.md'))

    def test_upload_controller_rejects_unsafe_name_empty_or_large_input(self):
        for name in ('../DCE.pdf','C:\\DCE.pdf','a/b.pdf','NUL.pdf'):
            with self.subTest(name=name),self.assertRaises(Exception):process_upload(name,b'x')
        with self.assertRaises(ValueError):process_upload('DCE.pdf',b'')
        with patch('P2_nlp_extraction.app.MAX_UPLOAD_BYTES',8):
            with self.assertRaises(ValueError):process_upload('DCE.pdf',b'x'*9)

    def test_upload_controller_calls_the_real_pipeline_without_ocr(self):
        original=pipeline.run_pipeline
        def run(source,**options):return original(source,self.folder/'runs',**options)
        with patch('P2_nlp_extraction.app.run_pipeline',side_effect=run), \
             patch('P2_nlp_extraction.ocr_pipeline.extract_pdf',side_effect=AssertionError('OCR interdit')):
            job=process_upload('DCE.pdf',self.source.read_bytes(),pages=(1,))
        self.assertEqual(job['options']['ocr_mode'],'never')
        self.assertEqual(job['options']['pdf_pages'],[1])
        self.assertEqual(job['status'],'completed_with_review')

    def test_streamlit_screen_and_results_without_ocr(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:self.skipTest('Interface Streamlit facultative non installée.')
        app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value,'P2 — Traitement des documents DCE')
        self.assertEqual(app.selectbox[0].value, 'auto')
        job=self.run_pipeline()
        app.session_state['p2_job']=copy.deepcopy(job)
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(app.table)
        self.assertTrue(all('<!--' not in element.value and '<br>' not in element.value
                            for element in app.markdown))
        self.assertEqual([metric.label for metric in app.metric],
                         ['Cellules des tableaux', 'Lignes de prix BPU'])
        self.assertIn('#### Sections détectées', [element.value for element in app.markdown])
        self.assertEqual([tab.label for tab in app.tabs],
                         ['Texte', 'Sections', 'Tableaux et BPU', 'Téléchargements'])
        next(box for box in app.selectbox if box.label == 'Export à télécharger').select('bpu_csv').run()
        self.assertFalse(app.exception)
        self.assertTrue(app.get('download_button'))
        app.selectbox[0].select('reuse_only')
        next(field for field in app.text_input if field.label.startswith('JSON OCR')).set_value('cache.json')
        next(field for field in app.text_input if field.label.startswith('Reprendre')).set_value(job['job_path'])
        app.run()
        with patch.object(pipeline, 'load_job', return_value=job), \
             patch.object(pipeline, 'resume_job', return_value=job) as resume:
            next(button for button in app.button if button.label == 'Reprendre le traitement').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(resume.call_args.kwargs['options'].ocr_results, ('cache.json',))
        partial = copy.deepcopy(job)
        partial['status'] = 'partial'
        partial['documents'][0]['outputs'].pop('document_md')
        app.session_state['p2_job'] = partial
        app.run()
        self.assertFalse(app.exception)
        self.assertIn('Aucun texte exporté pour ce document.', [entry.value for entry in app.info])

    def test_ocr_paths_from_untrusted_provenance_rejected(self):
        document={'pages':[{'ocr_provenance':{'ocr_json':'../README.md','ocr_json_sha256':'0'*64}}]}
        with self.assertRaises(ValueError):
            pipeline._quality_inputs(document,self.folder,())

    def test_job_loader_rejects_wrong_file_and_malformed_contract(self):
        path=self.folder/'job.json';path.write_text('{}',encoding='utf-8')
        with self.assertRaises(Exception):pipeline.load_job(path)
        with self.assertRaises(ValueError):pipeline.load_job(ROOT/'README.md')


    def test_page_progress_is_persisted_and_schema_valid(self):
        events=[]
        job=self.run_pipeline(progress=events.append)
        self.assertTrue(any(e.get('page_progress') for e in events))
        self.assertEqual(job['page_progress']['f000001']['pages'][0]['status'],'completed')
        self.assertEqual(pipeline.load_job(job['job_path']),job)
        self.assertIn('not_evaluated', [s['status'] for s in job['steps'] if ':quality:' in s['name']])

    def test_resume_uses_stored_source_and_keeps_previous_run(self):
        job=self.run_pipeline(ingestion_limits=IngestionLimits(max_source_bytes=1024**2),
                              conversion_limits=ConversionLimits(max_source_bytes=1024**2))
        self.source.write_bytes(b'original upload no longer available')
        resumed=pipeline.resume_job(job['job_path'])
        self.assertEqual(resumed['source']['sha256'],job['source']['sha256'])
        self.assertEqual(resumed['status'],'completed_with_review')
        self.assertEqual(resumed['settings'], job['settings'])
        self.assertIn('resumed_from:'+job['job_path'],resumed['warnings'])
        self.assertEqual(pipeline.load_job(job['job_path']),job)

    def test_partial_ocr_metrics_are_not_marked_not_evaluated(self):
        job = {'steps': [], 'warnings': []}
        quality = {
            'ocr_metrics': {'aggregates': {
                'fr': {'status': 'partial'}, 'ar': {'status': 'not_evaluated'}}},
            'segmentation_metrics': {'status': 'not_evaluated'},
        }
        pipeline._step(job, self.folder, None, 'quality', lambda: quality)
        self.assertEqual(job['steps'][0]['status'], 'partial')

    def test_resume_recovers_current_cache_without_superseded_input(self):
        from dataclasses import asdict
        from P2_nlp_extraction.scripts.ocr_common import sha256
        old_cache = self.folder / 'old_ocr.json'
        old_cache.write_text('{}', encoding='utf-8')
        current_cache = self.folder / 'ocr_batch_0000.json'
        current_cache.write_text('{"pages": [{"page": 1}]}', encoding='utf-8')
        options = ConversionOptions(ocr_mode='auto', ocr_results=(str(old_cache),))
        document_path = self.folder / 'document.json'
        document_path.write_text(json.dumps({
            'options': asdict(options),
            'pages': [{'page': 1, 'ocr_provenance': {
                'ocr_json': current_cache.relative_to(ROOT).as_posix(),
                'ocr_json_sha256': sha256(current_cache)}}],
        }), encoding='utf-8')
        previous = {
            'source': store_document(self.source, directory=self.folder / 'library'),
            'options': asdict(options),
            'documents': [{'outputs': pipeline._exports({'document_json': document_path})}],
            'job_path': (self.folder / 'job.json').relative_to(ROOT).as_posix(),
        }
        def run(source, output_dir, **kwargs):
            return {'warnings': [], 'job_path': previous['job_path']}
        with patch.object(pipeline, 'load_job', return_value=previous), \
             patch.object(pipeline, 'run_pipeline', side_effect=run) as execute:
            pipeline.resume_job(previous['job_path'])
            self.assertEqual(execute.call_args.kwargs['options'].ocr_results, (str(current_cache),))

            # Explicit caches replace automatic recovery, even if the old run
            # still has a different current result in its provenance.
            pipeline.resume_job(previous['job_path'], options=options)
            self.assertEqual(execute.call_args.kwargs['options'].ocr_results, (str(old_cache),))

            # Changing the fallback budget invalidates the recovered cache.
            changed = ConversionOptions(ocr_mode='auto', ocr_max_fallback_blocks=1)
            pipeline.resume_job(previous['job_path'], options=changed)
            self.assertEqual(execute.call_args.kwargs['options'].ocr_results, ())

    def test_resume_keeps_only_current_pages_from_overlapping_ocr_batches(self):
        from dataclasses import asdict
        from P2_nlp_extraction.scripts.ocr_common import sha256
        old = self.folder / 'old.json'
        new = self.folder / 'retry.json'
        old.write_text(json.dumps({'selected_pages': [1, 2], 'pages': [
            {'page': 1, 'status': 'needs_review'}, {'page': 2, 'status': 'error'}]}), encoding='utf-8')
        new.write_text(json.dumps({'selected_pages': [2], 'pages': [
            {'page': 2, 'status': 'needs_review'}]}), encoding='utf-8')
        options = ConversionOptions(ocr_mode='auto', ocr_results=(str(old),))
        document = {'options': asdict(options), 'pages': [
            {'page': number, 'ocr_provenance': {
                'ocr_json': cache.relative_to(ROOT).as_posix(), 'ocr_json_sha256': sha256(cache)}}
            for number, cache in ((1, old), (2, new))]}
        document_path = self.folder / 'document.json'
        document_path.write_text(json.dumps(document), encoding='utf-8')
        # Keep any new cache snapshots inside this test's owned directory.
        run = self.folder / 'runs' / 'previous'
        run.mkdir(parents=True)
        previous = {
            'source': store_document(self.source, directory=self.folder / 'library'),
            'options': asdict(options),
            'documents': [{'outputs': pipeline._exports({'document_json': document_path})}],
            'job_path': (run / 'job.json').relative_to(ROOT).as_posix(),
        }
        with patch.object(pipeline, 'load_job', return_value=previous), \
             patch.object(pipeline, 'run_pipeline', return_value={
                 'warnings': [], 'job_path': previous['job_path']}) as execute:
            pipeline.resume_job(previous['job_path'])
        pages = []
        for cache in execute.call_args.kwargs['options'].ocr_results:
            raw = json.loads(Path(cache).read_text(encoding='utf-8'))
            self.assertEqual(raw['selected_pages'], [page['page'] for page in raw['pages']])
            pages.extend(raw['pages'])
        self.assertEqual(sorted(page['page'] for page in pages), [1, 2])
        self.assertTrue(all(page['status'] == 'needs_review' for page in pages))
        self.assertEqual(json.loads(old.read_text(encoding='utf-8'))['pages'][1]['status'], 'error')

    def test_ui_auto_refuses_low_ram_before_pipeline(self):
        from types import SimpleNamespace
        from P2_nlp_extraction.app import upload_options
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=2*1024**3-1)):
            with self.assertRaises(ValueError): upload_options((1,),mode='auto')

    def test_ui_auto_explicit_profile_under_simulated_sufficient_ram(self):
        from types import SimpleNamespace
        from P2_nlp_extraction.app import upload_options
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=2*1024**3)):
            options=upload_options((2, 3),mode='auto')
            self.assertIsNone(upload_options(None,mode='auto').pdf_pages)
        self.assertEqual(options.pdf_pages,(2, 3))
        self.assertEqual(options.ocr_detector_max_side,1280)
        self.assertEqual(options.ocr_dpi,200)
        self.assertEqual(options.ocr_batch_size,4)
        self.assertEqual(options.ocr_fallback_mode,'preprocess')
