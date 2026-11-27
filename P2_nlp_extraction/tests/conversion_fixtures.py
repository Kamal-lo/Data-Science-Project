"""Documents T24 synthétiques ; aucun OCR ni document confidentiel."""
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from P2_nlp_extraction.scripts.ocr_common import ROOT
from P2_nlp_extraction.document_ingestion import IngestionLimits
from P2_nlp_extraction.document_ingestion.worker import process_request


def pdf_bytes(kinds=('native',), rotation=0, table=False):
    import pymupdf
    with pymupdf.open() as pdf:
        for kind in kinds:
            page = pdf.new_page(width=400, height=500)
            if kind in ('native', 'hybrid'):
                page.insert_text((30, 45 if kind == 'native' else 470), 'Document de consultation', fontsize=18 if kind == 'native' else 9)
                if kind == 'native':
                    page.insert_text((30, 90), 'Date : 19/11/2026. Montant : 12000 MAD.', fontsize=11)
                    page.insert_text((30, 120), '- Fournitures et travaux.', fontsize=11)
            if kind in ('scan', 'hybrid'):
                with pymupdf.open() as drawing:
                    leaf = drawing.new_page(width=340, height=350)
                    leaf.insert_text((20, 40), 'Image de texte non natif', fontsize=18)
                    image = leaf.get_pixmap().tobytes('png')
                page.insert_image(pymupdf.Rect(20, 20, 380, 420), stream=image)
            if kind == 'vector':
                page.draw_line((20, 20), (150, 150))
            if table:
                for x in (30, 150, 290):
                    page.draw_line((x, 180), (x, 260))
                for y in (180, 220, 260):
                    page.draw_line((30, y), (290, y))
                for x, y, text in ((40, 205, 'Article'), (160, 205, 'Prix'), (40, 245, 'Travaux'), (160, 245, '12000')):
                    page.insert_text((x, y), text, fontsize=10)
            page.set_rotation(rotation)
        return pdf.tobytes()


def docx_bytes(complex_table=False):
    from docx import Document
    document = Document()
    document.add_heading('Marché public — أشغال', 1)
    document.add_paragraph('Français : délai de 12 mois, montant 12 000 MAD.')
    document.add_paragraph('Attestation administrative', style='List Bullet')
    document.add_paragraph('Première pièce', style='List Number')
    table = document.add_table(rows=2, cols=2)
    for cell, text in zip([c for r in table.rows for c in r.cells], ['Article', 'Prix', 'Travaux', '12000']):
        cell.text = text
    if complex_table:
        table.cell(0, 0).merge(table.cell(0, 1))
    document.add_page_break()
    document.add_paragraph('Après saut explicite — pas de numéro de page inventé.')
    document.sections[0].header.paragraphs[0].text = 'En-tête contractuel'
    stream = io.BytesIO(); document.save(stream)
    return stream.getvalue()


def zip_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return stream.getvalue()


class ConversionCase(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.cache/t24_tests'; parent.mkdir(exist_ok=True, parents=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.counter = 0

    def ingestion(self, data=None, name='document.pdf'):
        self.counter += 1
        source = self.folder / f'source_{self.counter}' / name
        source.parent.mkdir()
        source.write_bytes(data if data is not None else pdf_bytes())
        run = self.folder / f'ingestion_{self.counter}'; run.mkdir()
        result = process_request({'source_path': str(source), 'source_name': source.name,
                                  'run_directory': str(run), 'limits': asdict(IngestionLimits()), 'dce_id': None})
        self.assertIn(result['status'], ('completed', 'completed_with_issues'))
        self.manifest = run / 'manifest.json'
        self.manifest_data = result
        self.item = next(f for f in result['files'] if f['eligible_for_t24'])
        return self.manifest

    def change_manifest(self, transform):
        data = json.loads(self.manifest.read_text(encoding='utf-8'))
        transform(data)
        self.manifest.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def convert(self, *, options=None, limits=None, file_id=None):
        from P2_nlp_extraction.document_conversion import convert_document, ConversionOptions
        result = convert_document(self.manifest, file_id or self.item['file_id'], self.folder / 'converted',
                                  options=options or ConversionOptions(ocr_mode='never'), limits=limits)
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / 'config/conversion.schema.json').read_text(encoding='utf-8'))
        persisted = json.loads(Path(result['document_json_path']).read_text(encoding='utf-8'))
        Draft202012Validator(schema).validate(persisted)
        self.assertEqual(persisted['status'], result['status'])
        return result

    def mock_ocr(self, pages=(1,), *, raw_text='نص عربي', ambiguous=False):
        import pymupdf
        artifact = self.manifest.parent / self.item['artifact_path']
        records = []
        with pymupdf.open(artifact) as pdf:
            for number in pages:
                page = pdf[number - 1]
                records.append({'page': number, 'dpi': 200, 'status': 'needs_review',
                                'warnings': [], 'errors': [], 'timings': {'fixture_seconds': 0},
                                'blocks': [{'block_id': 'ocr_1', 'raw_text': None if ambiguous else raw_text,
                                            'language': 'ar', 'direction': 'rtl',
                                            'bbox_pdf_points': [30, 25, min(350, page.rect.width), 60],
                                            'recognition_candidates': {'ar': {'text': raw_text, 'confidence': .8}, 'fr': {'text': 'nxs', 'confidence': .2}},
                                            'needs_review': True, 'warnings': [],
                                            'arabic_spacing_proposal': {'proposed_text': 'نص عربي', 'human_validated': False}}]})
        cache = self.folder / f'ocr_fixture_{self.counter}.json'
        cache.write_text(json.dumps({'schema_version': 'p2.automatic_ocr.v1', 'run_id': 'synthetic_ocr_not_real',
                                     'pdf_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
                                     'selected_pages': list(pages), 'pages': records,
                                     'source_pdf': 'IGNORED_DO_NOT_FOLLOW', 'image': 'IGNORED_DO_NOT_FOLLOW'}, ensure_ascii=False), encoding='utf-8')
        return cache
