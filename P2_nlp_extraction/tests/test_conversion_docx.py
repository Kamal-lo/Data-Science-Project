from pathlib import Path
import unittest

from conversion_fixtures import ConversionCase, docx_bytes
from P2_nlp_extraction.document_conversion import ConversionLimits, ConversionOptions


class DOCXTests(ConversionCase):
    def test_docx_structure_unicode_and_no_invented_pages(self):
        self.ingestion(docx_bytes(), 'cahier.docx')
        result = self.convert()
        self.assertEqual(result['status'], 'completed_with_review', result['errors'])
        self.assertFalse(result['pages'])
        self.assertTrue(all(b['page'] is None and b['bbox'] is None and b['method'] == 'docx_xml' for b in result['blocks']))
        self.assertEqual(result['blocks'][0]['type'], 'heading')
        self.assertIn('أشغال', result['blocks'][0]['raw_text'])
        self.assertTrue(any(b['type'] == 'list_item' for b in result['blocks']))
        table = next(b for b in result['blocks'] if b['type'] == 'table')
        self.assertEqual(table['cells'], [['Article', 'Prix'], ['Travaux', '12000']])
        self.assertTrue(table['structure_preserved'])
        self.assertTrue(any(b.get('role') == 'header' for b in result['blocks']))
        text = Path(result['markdown_path']).read_text(encoding='utf-8')
        self.assertIn('Français', text)
        self.assertIn('| Article | Prix |', text)
        self.assertNotIn('Page physique', text)
        self.assertIn('word_numbering_not_reconstructed', [w for b in result['blocks'] for w in b['warnings']])

    def test_merged_table_does_not_claim_structure(self):
        self.ingestion(docx_bytes(complex_table=True), 'fusion.docx')
        result = self.convert()
        self.assertFalse(result['errors'], result['errors'])
        table = next(b for b in result['blocks'] if b['type'] == 'table')
        self.assertFalse(table['structure_preserved'])
        self.assertEqual(table['cell_metadata'][0]['column_span'], 2)
        self.assertIn('structure non restituée', Path(result['markdown_path']).read_text(encoding='utf-8'))

    def test_docx_expansion_limit(self):
        self.ingestion(docx_bytes(), 'document.docx')
        result = self.convert(limits=ConversionLimits(max_docx_expanded_bytes=1000))
        self.assertIn(result['status'], ('failed', 'rejected'))
        self.assertTrue(result['errors'])

    def test_docx_xml_total_limit(self):
        self.ingestion(docx_bytes(), 'document.docx')
        result = self.convert(limits=ConversionLimits(max_xml_total_bytes=100))
        self.assertEqual(result['errors'][0]['code'], 'docx_xml_limit')

    def test_docx_pdf_page_selection_refused(self):
        self.ingestion(docx_bytes(), 'document.docx')
        result = self.convert(options=ConversionOptions(ocr_mode='never', pdf_pages=(1,)))
        self.assertEqual(result['errors'][0]['code'], 'docx_pages_unavailable')


if __name__ == '__main__':
    unittest.main()
