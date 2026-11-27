"""Small T24 contracts, without PDF processing or OCR."""
import json
from pathlib import Path
import unittest
import tempfile

from P2_nlp_extraction.document_segmentation import segment_document

ROOT = Path(__file__).resolve().parents[1]


def temporary_folder(case):
    """Un dossier privé par test, nettoyé sans toucher aux anciens résultats."""
    parent = ROOT / 'outputs/.tests'
    parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(dir=parent)
    case.addCleanup(temporary.cleanup)
    return Path(temporary.name)


def document(specs, *, status='completed', total=None, docx=False):
    blocks = []
    for index, spec in enumerate(specs, 1):
        spec = {'raw_text': spec} if isinstance(spec, str) else dict(spec)
        text = spec.pop('raw_text')
        block = dict(block_id=f'f000001_b{index:06d}', type='paragraph', raw_text=text,
                     text=text, page=None if docx else 1, bbox=None if docx else [20, index*30, 380, index*30+20],
                     method='docx_xml' if docx else 'native_pdf', source_reference={'fixture_index': index},
                     human_validated=False, needs_review=False, warnings=[], language='fr', markdown_lines=None)
        block.update(spec); blocks.append(block)
    numbers = list(dict.fromkeys(b['page'] for b in blocks if b['page'] is not None))
    return dict(schema_version='p2.conversion_document.v1', document_id='f000001', status=status,
                human_validated=False, source=dict(ingestion_run_id='synthetic', file_id='f000001',
                manifest_path='not-followed/manifest.json', manifest_sha256='0'*64,
                artifact_path='not-followed/document.docx' if docx else 'not-followed/document.pdf',
                sha256='1'*64, size_bytes=1, detected_type='docx' if docx else 'pdf'),
                coordinate_system='synthetic', pages=[dict(page=p, status=status, routing={},
                blocks=[b for b in blocks if b['page']==p], warnings=[], errors=[]) for p in numbers],
                blocks=blocks, sections=[], coverage=dict(source_page_count=total if total is not None else len(numbers),
                requested_pages=numbers, processed_pages=numbers), warnings=[], errors=[],
                outputs={'markdown':'document.md','json':'document.json'}, versions={}, options={}, execution_seconds=0)


class SegmentationCase(unittest.TestCase):
    def setUp(self):
        self.folder=temporary_folder(self)

    def run_document(self, data, markdown=None, **kwargs):
        path=self.folder/'document.json'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        if markdown is not None:
            (self.folder/'document.md').write_text(markdown, encoding='utf-8')
        self.path=path
        return segment_document(path,self.folder/'results',**kwargs)
