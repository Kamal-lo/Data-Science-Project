import hashlib
import json
from pathlib import Path
import unittest

from segmentation_fixtures import ROOT, document, temporary_folder
from P2_nlp_extraction.document_segmentation import segment_document
from P2_nlp_extraction.quality_evaluation import evaluate_quality
from P2_nlp_extraction.quality_evaluation.references import scope_hash


class QualityCase(unittest.TestCase):
    def setUp(self):
        self.folder=temporary_folder(self)

    def write(self,name,value):
        path=self.folder/name
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        return path

    def ocr_fixture(self,reference='Bonjour',hypothesis=None,language='fr',kind='synthetic'):
        scope=dict(image_size=[100,100],dpi=200,regions=[dict(name='text',bbox=[0,0,100,100])])
        path=self.folder/'reference.txt';raw=reference.encode('utf-8');path.write_bytes(raw)
        approval=dict(human_reviewed=False,scope_confirmed=True,reviewer=None,approved_at=None,
                      reference_sha256=hashlib.sha256(raw).hexdigest(),scope_sha256=scope_hash(scope),
                      reference_file=path.relative_to(ROOT).as_posix())
        self.manifest=dict(schema_version='p2.ocr_references.v1',dataset_kind=kind,document_sha256='1'*64,
                           records=[dict(page=1,language=language,scope=scope,approval=approval)])
        self.ocr=dict(schema_version='p2.automatic_ocr.v1',pdf_sha256='1'*64,status='completed_with_review',
                      pages=[dict(page=1,status='needs_review',errors=[],image_size=[100,100],dpi=200,
                                  blocks=[dict(block_id='p001_b0000',bbox=[10,10,90,90],language=language,
                                               raw_text=reference if hypothesis is None else hypothesis)])])
        return self.save_ocr()

    def save_ocr(self,**options):
        return evaluate_quality(self.write('ocr.json',self.ocr),self.write('references.json',self.manifest),
                                output_dir=self.folder/'evaluated',dataset_kind=self.manifest['dataset_kind'],**options)

    def segment_fixture(self,specs=None,total=None):
        source=self.write('conversion.json',document(specs or ['Règlement de consultation','Corps RC',
                          'Cahier des prescriptions spéciales','Corps CPS'],total=total))
        result=segment_document(source,self.folder/'segmentation')
        self.segpath=Path(result['sections_json_path'])
        self.segmentation=json.loads(self.segpath.read_text(encoding='utf-8'))
        scope=dict(block_ids=[b['block_id'] for b in result['blocks']],exhaustive=True)
        # Independent synthetic oracle for the fixed input, never copied from predictions.
        refs=[] if specs is not None else [
            dict(annotation_id='a0',category='RC',start_block_id='f000001_b000001',end_block_id='f000001_b000002'),
            dict(annotation_id='a1',category='CPS',start_block_id='f000001_b000003',end_block_id='f000001_b000004')]
        self.annotations=dict(schema_version='p2.section_annotations.v1',dataset_kind='synthetic',
                              conversion_json_sha256=result['source']['conversion_json_sha256'],
                              approval=dict(human_reviewed=False,scope_confirmed=True,reviewer=None,approved_at=None,
                                            scope_sha256=scope_hash(scope),reference_sha256=scope_hash(refs)),
                              scope=scope,sections=refs)
        return self.save_sections()

    def save_sections(self,rehash=True):
        if rehash:
            self.annotations['approval']['scope_sha256']=scope_hash(self.annotations['scope'])
            self.annotations['approval']['reference_sha256']=scope_hash(self.annotations['sections'])
        return evaluate_quality(segmentation_json_path=self.segpath,
                                section_annotations_path=self.write('annotations.json',self.annotations),
                                output_dir=self.folder/'evaluated',dataset_kind=self.annotations['dataset_kind'])
