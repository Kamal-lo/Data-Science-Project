import json
from pathlib import Path

from conversion_fixtures import ConversionCase, docx_bytes, ROOT
from P2_nlp_extraction.document_segmentation import segment_document
from segmentation_fixtures import SegmentationCase


class T24IntegrationTests(ConversionCase):
    def test_recorded_real_cps_cover_without_new_ocr(self):
        source=ROOT/'outputs/conversion/t24_real_page1_auto_20261119T000047_461540Z/conversion/20261119T000111_255875Z_f225f118/documents/f000001/document.json'
        if not source.exists():self.skipTest('Résultat T24 réel local non distribué.')
        result=segment_document(source,self.folder/'real_cover')
        self.assertEqual([s['category'] for s in result['sections']],['CPS'])
        self.assertEqual(len(result['sections'][0]['title_block_ids']),2)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['blocks'],json.loads(source.read_text(encoding='utf-8'))['blocks'])

    def test_real_t23_t24_docx_contract_without_ocr(self):
        self.ingestion(docx_bytes(),'document.docx')
        converted=self.convert()
        before=Path(converted['document_json_path']).read_bytes()
        result=segment_document(converted['document_json_path'],self.folder/'segmented')
        self.assertEqual(result['source']['conversion_source']['file_id'],self.item['file_id'])
        self.assertEqual(result['blocks'],json.loads(before)['blocks'])
        self.assertEqual(Path(converted['document_json_path']).read_bytes(),before)
        self.assertTrue(Path(result['markdown_path']).exists())
class NativeTableRegressionTests(SegmentationCase):
    def test_native_pdf_table_fragments_and_t27_preserved(self):
        import pymupdf
        from P2_nlp_extraction.document_ingestion import ingest_path
        from P2_nlp_extraction.document_conversion import convert_document, ConversionOptions
        from P2_nlp_extraction.table_extraction import extract_tables
        source=self.folder/'table_title.pdf'
        with pymupdf.open() as pdf:
            page=pdf.new_page(width=600,height=800)
            page.insert_text((40,50),'Reglement de consultation',fontsize=18)
            for x in (40,450,550):page.draw_line((x,100),(x,200))
            for y in (100,150,200):page.draw_line((40,y),(550,y))
            page.insert_text((48,125),'Cahier des prescriptions speciales',fontsize=10)
            page.insert_text((48,175),'Mention dans une cellule',fontsize=10)
            page.insert_text((470,175),'1',fontsize=10)
            pdf.save(source)
        ingested=ingest_path(source,self.folder/'ingestion')
        item=next(f for f in ingested['files'] if f['eligible_for_t24'])
        converted=convert_document(ingested['manifest_path'],item['file_id'],self.folder/'conversion',
                                   options=ConversionOptions(ocr_mode='never'))
        path=Path(converted['document_json_path']);before=path.read_bytes();data=json.loads(before)
        hidden=[b for b in data['blocks'] if b.get('render') is False]
        self.assertTrue(hidden)
        result=segment_document(path,self.folder/'segmented')
        self.assertEqual([s['category'] for s in result['sections']],['RC'])
        self.assertEqual(result['blocks'],data['blocks'])
        md=Path(result['markdown_path']).read_text(encoding='utf-8')
        self.assertEqual(md.count('Cahier des prescriptions speciales'),1)
        self.assertEqual(md.count('Mention dans une cellule'),1)
        tables=extract_tables(path,result['sections_json_path'],self.folder/'tables')
        self.assertEqual(len(tables['tables']),1)
        values=[[c['value'] for c in row['cells']] for row in tables['tables'][0]['rows']]
        self.assertEqual(values,[['Cahier des prescriptions speciales',''],['Mention dans une cellule','1']])
        self.assertEqual(path.read_bytes(),before)
