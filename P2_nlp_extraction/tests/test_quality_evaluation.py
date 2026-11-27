import hashlib
import json
from pathlib import Path

from quality_fixtures import QualityCase, ROOT
from P2_nlp_extraction.quality_evaluation import evaluate_quality, EvaluationLimits, EvaluationInputError
from P2_nlp_extraction.tools.audit_p2 import approve_reference, draft_references


class OCRValidationTests(QualityCase):
    def test_reference_drafts_are_empty_and_seal_the_reviewed_files(self):
        self.ocr_fixture(reference='أ', language='ar')
        self.segment_fixture()
        ocr = self.folder / 'ocr.json'
        drafts = draft_references(self.folder / 'drafts', [1], 'ar', ocr, self.segpath)
        draft = drafts / 'ocr-draft.json'
        transcript = drafts / 'page-1-ar.txt'
        self.assertEqual(transcript.read_bytes(), b'')
        with self.assertRaisesRegex(ValueError, 'Transcription vide'):
            approve_reference(draft, 'Relecteur de test')
        with self.assertRaisesRegex(ValueError, 'périmètre exhaustif'):
            approve_reference(drafts / 'sections-draft.json', 'Relecteur de test')
        transcript.write_text('أ', encoding='utf-8')
        sealed = approve_reference(draft, 'Relecteur de test')
        self.assertNotEqual(sealed, draft)
        transcript.write_text('ب', encoding='utf-8')
        result = evaluate_quality(ocr, sealed, output_dir=self.folder/'review')
        record = next(record for record in result['ocr_metrics']['records'] if record['language'] == 'ar')
        self.assertIsNone(record['metrics'])
        self.assertIn('reference_hash_mismatch', record['warnings'])
    def test_processing_page_never_scored_even_with_compatible_oracle(self):
        self.ocr_fixture()
        self.ocr['pages'][0]['status']='processing'
        result=self.save_ocr()['ocr_metrics']
        record=result['records'][0]
        self.assertEqual(record['status'],'not_evaluated')
        self.assertIsNone(record['metrics'])
        self.assertIn('ocr_page_not_finalized',record['warnings'])
        self.assertEqual(record['reference_text_original'],'Bonjour')
        self.assertEqual(record['hypothesis_text_original'],'Bonjour')
        self.assertIsNone(result['aggregates']['fr']['metrics'])
        self.assertEqual(self.ocr['pages'][0]['status'],'processing')

    def test_finalized_page_states_can_be_scored(self):
        self.ocr_fixture()
        for status in ('ok','needs_review','no_text_detected'):
            with self.subTest(status=status):
                self.ocr['pages'][0]['status']=status
                self.ocr['pages'][0]['blocks'][0]['raw_text']='' if status=='no_text_detected' else 'Bonjour'
                record=self.save_ocr()['ocr_metrics']['records'][0]
                self.assertEqual(record['status'],'evaluated')
                self.assertEqual(record['metrics']['cer'],1 if status=='no_text_detected' else 0)

    def test_unfinished_or_unknown_document_and_page_states_not_scored(self):
        for document_status,page_status in (('processing','ok'),('completed','processing'),
                                            ('completed','completed'),('completed',None),(None,'ok')):
            with self.subTest(document=document_status,page=page_status):
                self.ocr_fixture()
                self.ocr['status']=document_status
                self.ocr['pages'][0]['status']=page_status
                record=self.save_ocr()['ocr_metrics']['records'][0]
                self.assertIsNone(record['metrics'])
                self.assertEqual(record['status'],'not_evaluated')

    def test_partial_document_finalized_pages_only_weighted_totals(self):
        self.ocr_fixture(reference='a',hypothesis='b')
        item=json.loads(json.dumps(self.manifest['records'][0]));item['page']=2
        raw=b'abcdefghij';path=self.folder/'second.txt';path.write_bytes(raw)
        item['approval']['reference_file']=path.relative_to(ROOT).as_posix()
        item['approval']['reference_sha256']=hashlib.sha256(raw).hexdigest()
        self.manifest['records'].append(item)
        page=json.loads(json.dumps(self.ocr['pages'][0]));page.update(page=2,status='processing')
        page['blocks'][0].update(block_id='p002_b0000',raw_text='abcdefghij')
        self.ocr['pages'].append(page);self.ocr['status']='partial'
        result=self.save_ocr()['ocr_metrics']
        aggregate=result['aggregates']['fr']
        self.assertEqual(aggregate['status'],'partial')
        self.assertEqual((aggregate['evaluated_pages'],aggregate['requested_pages']),(1,2))
        self.assertEqual(aggregate['metrics']['reference_characters'],1)
        self.assertEqual(aggregate['metrics']['cer_percent'],100)
        second=next(r for r in result['records'] if r['page']==2 and r['language']=='fr')
        self.assertIsNone(second['metrics'])
        self.assertEqual(second['reference_text_original'],'abcdefghij')
        self.assertEqual(second['hypothesis_text_original'],'abcdefghij')
        page['status']='ok'
        aggregate=self.save_ocr()['ocr_metrics']['aggregates']['fr']
        self.assertEqual(aggregate['evaluated_pages'],2)
        self.assertEqual(aggregate['metrics']['reference_characters'],11)
        self.assertAlmostEqual(aggregate['metrics']['cer_percent'],100/11)
        self.assertEqual(aggregate['metrics']['word_metrics']['reference_words'], 2)
        self.assertEqual(aggregate['metrics']['word_metrics']['wer_percent'], 50)

    def test_finalized_page_still_requires_reference_validation(self):
        self.ocr_fixture(kind='real')
        self.ocr['pages'][0]['status']='ok'
        record=self.save_ocr()['ocr_metrics']['records'][0]
        self.assertIsNone(record['metrics'])
        self.assertIn('reference_not_human_validated',record['warnings'])
        result=evaluate_quality(self.folder/'ocr.json',output_dir=self.folder/'no_reference')
        self.assertTrue(all(r['metrics'] is None for r in result['ocr_metrics']['records']))

    def test_synthetic_oracle_explicitly_not_human(self):
        r=self.ocr_fixture()['ocr_metrics']['records'][0]
        self.assertEqual(r['metrics']['cer'],0);self.assertEqual(r['dataset_kind'],'synthetic')
        self.assertFalse(r['reference_validation']['human_validated'])
        self.assertTrue(r['reference_validation']['synthetic_oracle'])

    def test_unvalidated_real_reference_not_scored(self):
        r=self.ocr_fixture(kind='real')['ocr_metrics']['records'][0]
        self.assertIsNone(r['metrics']);self.assertIn('reference_not_human_validated',r['warnings'])

    def test_no_reference_not_scored(self):
        self.ocr_fixture()
        r=evaluate_quality(self.folder/'ocr.json',output_dir=self.folder/'no_ref')
        self.assertTrue(all(x['metrics'] is None for x in r['ocr_metrics']['records']))

    def test_missing_or_changed_reference_artifact_not_scored(self):
        self.ocr_fixture()
        self.manifest['records'][0]['approval']['reference_file']='data/missing.txt'
        self.assertIsNone(self.save_ocr()['ocr_metrics']['records'][0]['metrics'])
        self.manifest['records'][0]['approval']['reference_file']=(self.folder/'reference.txt').relative_to(ROOT).as_posix()
        (self.folder/'reference.txt').write_text('Changed',encoding='utf-8')
        self.assertIn('reference_hash_mismatch',self.save_ocr()['ocr_metrics']['records'][0]['warnings'])

    def test_empty_reference_not_zero_cer(self):
        self.assertIsNone(self.ocr_fixture(reference='')['ocr_metrics']['records'][0]['metrics'])

    def test_scope_and_document_hash_mismatch_block_scores(self):
        self.ocr_fixture()
        self.manifest['records'][0]['approval']['scope_sha256']='0'*64
        self.assertIsNone(self.save_ocr()['ocr_metrics']['records'][0]['metrics'])
        self.ocr_fixture();self.ocr['pdf_sha256']='0'*64
        self.assertIsNone(self.save_ocr()['ocr_metrics']['records'][0]['metrics'])

    def test_geometry_boundary_crossing_and_failed_page_not_scored(self):
        for change in ('geometry','boundary','failure','unresolved'):
            self.ocr_fixture()
            page=self.ocr['pages'][0]
            if change=='geometry':page['dpi']=150
            elif change=='boundary':page['blocks'][0]['bbox']=[-5,10,90,90]
            elif change=='failure':page.update(status='error',errors=[{'code':'memory_limit'}])
            else:page['blocks'][0]['raw_text']=None
            with self.subTest(change=change):self.assertIsNone(self.save_ocr()['ocr_metrics']['records'][0]['metrics'])

    def test_arabic_evaluation_separate_and_original_texts_retained(self):
        r=self.ocr_fixture(reference='عَقد',hypothesis='عقد',language='ar')['ocr_metrics']
        self.assertEqual(r['records'][0]['reference_text_original'],'عَقد')
        self.assertEqual(r['aggregates']['ar']['metrics']['deletions'],1)
        self.assertIsNone(r['aggregates']['fr']['metrics'])

    def test_aggregation_uses_error_totals_not_average(self):
        self.ocr_fixture(reference='a',hypothesis='b')
        item=json.loads(json.dumps(self.manifest['records'][0]));item['page']=2
        raw=b'abcdefghij';path=self.folder/'second.txt';path.write_bytes(raw)
        item['approval']['reference_file']=path.relative_to(ROOT).as_posix()
        item['approval']['reference_sha256']=hashlib.sha256(raw).hexdigest()
        self.manifest['records'].append(item)
        page=json.loads(json.dumps(self.ocr['pages'][0]));page['page']=2;page['blocks'][0]['raw_text']='abcdefghij'
        self.ocr['pages'].append(page)
        r=self.save_ocr()['ocr_metrics']['aggregates']['fr']['metrics']
        self.assertEqual(r['reference_characters'],11);self.assertAlmostEqual(r['cer_percent'],100/11)


class SectionValidationTests(QualityCase):
    def test_annotated_article_boundaries_are_scored_separately(self):
        self.segment_fixture(['Règlement de consultation', 'Article 1 : objet', 'Texte'])
        ids = self.annotations['scope']['block_ids']
        self.annotations['sections'] = [dict(annotation_id='rc', category='RC',
                                             start_block_id=ids[0], end_block_id=ids[2])]
        self.annotations['scope']['hierarchy'] = [
            dict(kind='article', start_block_id=ids[1], end_block_id=ids[2])]
        result = self.save_sections()['segmentation_metrics']
        self.assertEqual(result['hierarchy_metrics']['article']['f1'], 1.0)
        self.assertIsNone(result['hierarchy_metrics']['subsection']['f1'])
        self.annotations['scope']['hierarchy'][0]['end_block_id'] = ids[1]
        result = self.save_sections()['segmentation_metrics']
        self.assertEqual(result['hierarchy_metrics']['article']['f1'], 0.0)

    def test_correct_sections_precision_recall_f1(self):
        metric=self.segment_fixture()['segmentation_metrics']['metrics']
        self.assertEqual(metric['labeled_exact']['f1'],1)
        self.assertEqual(metric['category_on_exact_spans']['accuracy'],1)
        self.assertEqual(metric['boundary_exact_accuracy'],1)

    def test_wrong_category_counts_fp_fn_and_category_error(self):
        self.segment_fixture();self.annotations['sections'][1]['category']='BPU'
        r=self.save_sections()['segmentation_metrics']['metrics']
        self.assertEqual(r['labeled_exact']['false_positives'],1)
        self.assertEqual(r['labeled_exact']['false_negatives'],1)
        self.assertEqual(r['labeled_exact']['f1'],.5)
        self.assertEqual(r['boundary_exact']['f1'],1)
        self.assertEqual(r['category_on_exact_spans']['accuracy'],.5)

    def test_wrong_boundary_not_exact_match(self):
        self.segment_fixture();self.annotations['sections'][0]['end_block_id']='f000001_b000001'
        r=self.save_sections()['segmentation_metrics']['metrics']
        self.assertEqual(r['labeled_exact']['f1'],.5)
        self.assertEqual(r['boundary_exact_accuracy'],.5)

    def test_missing_human_annotations_not_evaluated(self):
        self.segment_fixture()
        r=evaluate_quality(segmentation_json_path=self.segpath,output_dir=self.folder/'no_anns')['segmentation_metrics']
        self.assertEqual(r['status'],'not_evaluated');self.assertIsNone(r['metrics'])

    def test_unvalidated_real_annotations_not_evaluated(self):
        self.segment_fixture();self.annotations['dataset_kind']='real'
        r=self.save_sections()['segmentation_metrics'];self.assertIsNone(r['metrics'])

    def test_partial_document_scored_only_in_explicit_scope(self):
        r=self.segment_fixture(total=28)['segmentation_metrics']
        self.assertEqual(r['status'],'evaluated');self.assertIn('partial_document_no_full_dce_claim',r['warnings'])
        self.annotations['scope']['block_ids'].append('unprocessed_page_block')
        self.assertIsNone(self.save_sections()['segmentation_metrics']['metrics'])

    def test_non_exhaustive_annotation_not_scored(self):
        self.segment_fixture();self.annotations['scope']['exhaustive']=False
        self.assertIsNone(self.save_sections()['segmentation_metrics']['metrics'])

    def test_modified_or_mismatched_annotation_not_scored(self):
        self.segment_fixture();self.annotations['sections'][0]['category']='BPU'
        self.assertIsNone(self.save_sections(rehash=False)['segmentation_metrics']['metrics'])
        self.annotations['conversion_json_sha256']='0'*64
        self.assertIsNone(self.save_sections()['segmentation_metrics']['metrics'])

    def test_section_crossing_annotation_scope_not_cropped(self):
        self.segment_fixture();self.annotations['scope']['block_ids']=self.annotations['scope']['block_ids'][1:]
        self.annotations['sections']=self.annotations['sections'][1:]
        r=self.save_sections()['segmentation_metrics']
        self.assertIn('predicted_section_crosses_annotation_scope',r['warnings']);self.assertIsNone(r['metrics'])

    def test_empty_section_sets_do_not_mean_perfect_accuracy(self):
        r=self.segment_fixture(specs=['Préambule sans section'])['segmentation_metrics']['metrics']
        self.assertIsNone(r['labeled_exact']['precision']);self.assertIsNone(r['labeled_exact']['f1'])

    def test_only_false_positives_against_exhaustive_empty_annotations(self):
        self.segment_fixture();self.annotations['sections']=[]
        r=self.save_sections()['segmentation_metrics']['metrics']['labeled_exact']
        self.assertEqual(r['false_positives'],2);self.assertEqual(r['false_negatives'],0)
        self.assertEqual(r['f1'],0);self.assertIsNone(r['recall'])

    def test_missing_section_only_false_negative(self):
        self.segment_fixture(specs=['Titre non reconnu','Texte du document'])
        self.annotations['sections']=[dict(annotation_id='a0',category='RC',
                                          start_block_id='f000001_b000001',end_block_id='f000001_b000002')]
        r=self.save_sections()['segmentation_metrics']['metrics']['labeled_exact']
        self.assertEqual(r['false_negatives'],1);self.assertEqual(r['recall'],0)
        self.assertIsNone(r['precision']);self.assertEqual(r['f1'],0)


class ContractTests(QualityCase):
    def test_schemas_original_files_and_unique_exports(self):
        from jsonschema import Draft202012Validator
        result=self.ocr_fixture();before=(self.folder/'ocr.json').read_bytes()
        again=self.save_ocr();self.assertNotEqual(result['run_directory'],again['run_directory'])
        self.assertEqual(before,(self.folder/'ocr.json').read_bytes())
        for name in ('ocr_metrics','segmentation_metrics'):
            schema=json.loads((ROOT/f'config/{name}.schema.json').read_text(encoding='utf-8'))
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(json.loads(Path(result['output_paths'][name+'.json']).read_text(encoding='utf-8')))
        self.assertIn('Non évalué',Path(result['output_paths']['evaluation_report.md']).read_text(encoding='utf-8'))

    def test_output_path_limits_and_bad_json(self):
        with self.assertRaises(EvaluationInputError):evaluate_quality(output_dir=ROOT.parent/'outside')
        with self.assertRaises(EvaluationInputError):evaluate_quality(output_dir=self.folder,limits=EvaluationLimits(max_output_bytes=1))
        path=self.folder/'bad.json';path.write_text('{"x":1,"x":2}',encoding='utf-8')
        with self.assertRaises(EvaluationInputError):evaluate_quality(ocr_json_path=path,output_dir=self.folder)

    def test_alignment_budget_means_not_evaluated(self):
        self.ocr_fixture()
        result=self.save_ocr(limits=EvaluationLimits(max_alignment_cells=1))
        self.assertIn('alignment_budget_exceeded',result['ocr_metrics']['records'][0]['warnings'])
