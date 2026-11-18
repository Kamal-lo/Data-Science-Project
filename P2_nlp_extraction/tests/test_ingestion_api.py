"""Intégration T23 avec de vrais workers et documents synthétiques, sans OCR."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from ingestion_fixtures import IngestionCase, docx_bytes, pdf_bytes, zip_bytes
from P2_nlp_extraction.document_ingestion import ingest_path, IngestionLimits
from P2_nlp_extraction.scripts.ocr_common import ROOT


class APITests(IngestionCase):
    def test_real_worker_zip_unicode_manifest_and_t24_contract(self):
        data=zip_bytes([('Lot 1/',b''),('Lot 1/Cahier français.bin',pdf_bytes()),
                        ('Lot 1/دفتر الشروط.docx',docx_bytes()),('prix.csv','nom,prix'),
                        ('annexe.zip',zip_bytes([('hidden.txt','not expanded')]))])
        source=self.source(data,'marché.zip')
        result=ingest_path(source,self.folder/'outputs',dce_id='DCE-TEST')
        self.assertEqual(result['status'],'completed_with_issues')
        self.assertTrue(result['eligible_for_t24'])
        self.assertEqual(len(result['files']),5)
        ready=[f for f in result['files'] if f['eligible_for_t24']]
        self.assertEqual({f['detected_type'] for f in ready},{'pdf','docx'})
        run=Path(result['run_directory'])
        for item in result['files']:
            artifact=run/item['artifact_path']
            self.assertTrue(artifact.exists())
            if artifact.is_file():
                self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(),item['sha256'])
        self.assertTrue((run/'files/Lot 1/دفتر الشروط.docx').is_file())
        manifest=json.loads(Path(result['manifest_path']).read_text(encoding='utf-8'))
        self.assertEqual(manifest['schema_version'],'p2.ingestion.v1')
        self.assertNotIn(str(self.folder),json.dumps(manifest,ensure_ascii=False))
        self.assertEqual(source.read_bytes(),data)
        self.assertNotIn('paddle',sys.modules)
        schema=json.loads((ROOT/'config/ingestion_manifest.schema.json').read_text(encoding='utf-8'))
        self.assertTrue(set(schema['required'])<=manifest.keys())

    def test_individual_pdf_docx_and_unique_runs(self):
        for name,data in (('document.pdf',pdf_bytes()),('document.docx',docx_bytes())):
            with self.subTest(name=name):
                source=self.source(data,name)
                first=ingest_path(source,self.folder/'output')
                second=ingest_path(source,self.folder/'output')
                self.assertEqual(first['status'],'completed')
                self.assertTrue(first['files'][0]['eligible_for_t24'])
                self.assertNotEqual(first['run_directory'],second['run_directory'])
                self.assertEqual((Path(first['run_directory'])/'files'/name).read_bytes(),data)

    def test_bad_parameters_and_source_do_not_create_outputs(self):
        source=self.source(b'x','input.bin');out=self.folder/'not_created'
        for limits in (IngestionLimits(timeout_seconds=-1),IngestionLimits(max_entries=True),
                       IngestionLimits(max_compression_ratio=float('nan'))):
            with self.assertRaises(ValueError):ingest_path(source,out,limits=limits)
        with self.assertRaises(ValueError):ingest_path(source,ROOT.parent/'forbidden_t23')
        with self.assertRaises(FileNotFoundError):ingest_path(self.folder/'absent',out)
        with self.assertRaises(ValueError):ingest_path(self.folder,out)
        self.assertFalse(out.exists())

    def test_source_size_refusal_has_manifest(self):
        result=ingest_path(self.source(b'x'*20,'source.bin'),self.folder/'out',limits=IngestionLimits(max_source_bytes=10))
        self.assert_rejected(result,'source_size_limit')
        self.assertTrue(Path(result['manifest_path']).is_file())

    def test_real_worker_timeout_is_reported(self):
        result=ingest_path(self.source(pdf_bytes(),'doc.pdf'),self.folder/'out',limits=IngestionLimits(timeout_seconds=.001))
        self.assert_rejected(result,'timeout')

    def test_real_worker_memory_watchdog_is_reported(self):
        result=ingest_path(self.source(pdf_bytes(),'doc.pdf'),self.folder/'out',limits=IngestionLimits(max_worker_memory_bytes=1))
        self.assert_rejected(result,'memory_limit')

    def test_empty_zip_and_corrupt_zip_real_worker(self):
        result=ingest_path(self.source(zip_bytes([])),self.folder/'empty')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['files'],[])
        result=ingest_path(self.source(b'PK\x03\x04invalid','broken.zip'),self.folder/'broken')
        self.assert_rejected(result,'corrupt_zip')

    def test_streamed_zip_data_descriptor(self):
        class NonSeekable:
            def __init__(self):self.data=bytearray()
            def write(self,data):self.data.extend(data);return len(data)
            def flush(self):pass
        sink=NonSeekable()
        with zipfile.ZipFile(sink,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('document.pdf',pdf_bytes())
        result=ingest_path(self.source(bytes(sink.data)),self.folder/'streamed')
        self.assertEqual(result['status'],'completed')
        self.assertTrue(result['eligible_for_t24'])
