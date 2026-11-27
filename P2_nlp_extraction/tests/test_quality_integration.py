import json

from quality_fixtures import QualityCase, ROOT
from P2_nlp_extraction.quality_evaluation import evaluate_quality


class RecordedIntegrationTests(QualityCase):
    def test_processing_page_with_existing_human_validated_reference_not_scored(self):
        source=ROOT/'outputs/ocr/automatic_sample/20261118T221046_740048Z_de048b93/document.json'
        if not source.exists():self.skipTest('Sortie OCR réelle locale non distribuée.')
        manifest=ROOT/'data/ground_truth/pages_1_2/manifest.json'
        original=source.read_bytes();reference_before=manifest.read_bytes()
        data=json.loads(original)
        next(p for p in data['pages'] if p['page']==1)['status']='processing'
        data['status']='partial'
        copied=self.write('processing_copy.json',data)
        result=evaluate_quality(copied,manifest,output_dir=self.folder/'processing_human_reference')
        record=next(r for r in result['ocr_metrics']['records'] if r['page']==1 and r['language']=='fr')
        self.assertTrue(record['reference_validation']['human_validated'])
        self.assertEqual(record['status'],'not_evaluated')
        self.assertIsNone(record['metrics'])
        self.assertIn('ocr_page_not_finalized',record['warnings'])
        self.assertTrue(record['reference_text_original'])
        self.assertTrue(record['hypothesis_text_original'])
        self.assertEqual(source.read_bytes(),original)
        self.assertEqual(manifest.read_bytes(),reference_before)

    def test_human_french_manifest_recorded_ocr_and_t26(self):
        source=ROOT/'outputs/ocr/automatic_sample/20261118T221046_740048Z_de048b93/document.json'
        segments=list((ROOT/'outputs/segmentation/t26_validation_20261119T184403_836904Z/real_cover').rglob('sections.json'))
        if not source.exists() or not segments:self.skipTest('Sorties réelles locales non distribuées.')
        manifest=ROOT/'data/ground_truth/pages_1_2/manifest.json'
        original=manifest.read_bytes();segoriginal=segments[0].read_bytes()
        result=evaluate_quality(source,manifest,segments[0],output_dir=self.folder/'recorded')
        records={(r['page'],r['language']):r for r in result['ocr_metrics']['records']}
        self.assertTrue(records[1,'fr']['reference_validation']['human_validated'])
        self.assertEqual(records[1,'fr']['metrics']['total_errors'],8)
        self.assertEqual(records[1,'fr']['metrics']['reference_characters'],554)
        self.assertIsNone(records[2,'fr']['metrics'])
        self.assertIsNone(records[1,'ar']['metrics'])
        self.assertIsNone(result['segmentation_metrics']['metrics'])
        self.assertEqual(original,manifest.read_bytes());self.assertEqual(segoriginal,segments[0].read_bytes())

    def test_t25_memory_failure_is_not_quality_score(self):
        source=ROOT/'outputs/ocr/t25_progressive_off_20261119T115005_621902Z/ocr/20261119T115039_488456Z_48876475/document.json'
        if not source.exists():self.skipTest('Échec T25 réel local non distribué.')
        result=evaluate_quality(source,ROOT/'data/ground_truth/pages_1_2/manifest.json',output_dir=self.folder/'failed')
        record=next(r for r in result['ocr_metrics']['records'] if r['page']==1 and r['language']=='fr')
        self.assertIn('ocr_page_failed',record['warnings']);self.assertIsNone(record['metrics'])
