import copy
import json
from pathlib import Path
import unittest

from conversion_fixtures import ConversionCase, pdf_bytes
from P2_nlp_extraction.document_conversion import ConversionOptions
from P2_nlp_extraction.document_conversion.layout import order_blocks
from P2_nlp_extraction.document_conversion.markdown import render
from P2_nlp_extraction.document_conversion.models import new_block
from P2_nlp_extraction.document_conversion.ocr_structure import structure_page
from P2_nlp_extraction.scripts.ocr_common import ROOT


def block(text, box, lang='fr', **extras):
    b = new_block('unresolved' if text is None else 'paragraph', text, 'ocr', page=1, bbox=box,
                  source_reference={'ocr_block_id': 'original'},
                  recognition_candidates={lang: {'text': text, 'confidence': .9}})
    b.update(language=lang, direction='rtl' if lang == 'ar' else 'ltr', needs_review=True)
    b.update(extras)
    return b


def body(lang='fr'):
    texts = ["Passé en application de l'article 8, de l'alinéa 1 du",
             "paragraphe 3 de l'article 19 et des dispositions du",
             "décret du 08 mats 2023 relatif aux marchés publics."]
    if lang == 'ar':
        texts = ['يتعلق هذا العقد بالخدمات المنصوص عليها في دفتر الشروط',
                 'وتلتزم الجهة المعنية بتنفيذ جميع الخدمات وفق الشروط',
                 'وتظل البيانات الأصلية محفوظة دون تعديل في هذا الملف.']
    return [block(t, [60, 450 + 15 * i, 540, 462 + 15 * i], lang) for i, t in enumerate(texts)]


def main_title(lang='fr'):
    texts = ['CAHIER DES PRESCRIPTIONS', 'SPECIALES'] if lang == 'fr' else ['دفتر الشروط', 'الخاصة بالعقد']
    return [block(texts[0], [120, 150, 480, 174], lang), block(texts[1], [220, 178, 380, 201], lang)]


def page_for(blocks):
    for index, b in enumerate(blocks, 1):
        b['block_id'] = f'f000001_b{index:06d}'
    return {'page': 1, 'width': 600, 'height': 840, 'blocks': blocks, 'status': 'completed_with_review',
            'routing': {}, 'warnings': [], 'errors': []}


class StructureTests(unittest.TestCase):
    def groups(self, blocks):
        self.page = page_for(blocks)
        self.page['structure'] = structure_page(self.page, 'f000001')
        return self.page['structure']

    def test_multiline_french_heading_and_lower_subheading(self):
        secondary = [block('SOUS TITRE DE LA CONSULTATION', [150, 260, 450, 277]),
                     block('DISPOSITIONS GENERALES', [180, 280, 420, 297])]
        groups = self.groups(main_title() + secondary + body())
        headings = [g for g in groups if g['type'] == 'heading']
        self.assertEqual([g['heading_level'] for g in headings], [1, 2])
        self.assertEqual(headings[0]['text'], 'CAHIER DES PRESCRIPTIONS SPECIALES')
        self.assertEqual(len(headings[0]['source_block_ids']), 2)
        self.assertEqual(len(headings[1]['source_block_ids']), 2)

    def test_arabic_multiline_heading_and_rtl_paragraph(self):
        groups = self.groups(main_title('ar') + body('ar'))
        self.assertEqual(groups[0]['type'], 'heading')
        self.assertEqual(groups[0]['heading_level'], 1)
        self.assertEqual(groups[0]['text'], 'دفتر الشروط الخاصة بالعقد')
        self.assertEqual(groups[1]['direction'], 'rtl')
        self.assertEqual(len(groups[1]['source_block_ids']), 3)

    def test_clear_french_paragraph_keeps_ocr_error(self):
        groups = self.groups(body())
        self.assertEqual(len(groups), 1)
        self.assertIn('08 mats 2023', groups[0]['text'])
        self.assertEqual(groups[0]['raw_texts'], [b['raw_text'] for b in self.page['blocks']])

    def test_arabic_paragraph_uses_right_edge_alignment(self):
        sources = body('ar')
        sources[0]['bbox'][0] = 220
        sources[1]['bbox'][0] = 120
        groups = self.groups(sources)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['direction'], 'rtl')
        self.assertEqual(groups[0]['text'], ' '.join(b['raw_text'] for b in sources))

    def test_sources_hypotheses_and_warnings_unchanged(self):
        sources = main_title() + body()
        sources[-1]['warnings'] = ['latin_recognizers_disagree']
        before = copy.deepcopy(sources)
        groups = self.groups(sources)
        for b, original in zip(sources, before):
            for key in ('raw_text', 'text', 'bbox', 'recognition_candidates', 'warnings', 'source_reference', 'type'):
                self.assertEqual(b[key], original[key])
        self.assertIn('latin_recognizers_disagree', groups[-1]['warnings'])
        self.assertTrue(all(g['human_validated'] is False for g in groups))

    def test_no_heading_without_reference_body(self):
        groups = self.groups(main_title())
        self.assertFalse(any(g['type'] == 'heading' for g in groups))

    def test_equal_dominant_titles_do_not_invent_root(self):
        one, two = main_title(), main_title()
        for b in two:
            b['bbox'][1] += 100; b['bbox'][3] += 100
        groups = self.groups(one + two + body())
        self.assertFalse(any(g['type'] == 'heading' for g in groups))

    def test_missing_coordinates_preserved_without_inference(self):
        sources = body()
        sources[1]['bbox'] = None
        self.assertEqual(len(self.groups(sources)), 3)

    def test_columns_do_not_merge(self):
        sources = body()[:2]
        sources[0]['bbox'] = [20, 50, 260, 62]
        sources[1]['bbox'] = [320, 65, 560, 77]
        self.assertEqual(len(self.groups(sources)), 2)

    def test_column_warning_blocks_uncertain_merges(self):
        sources = body()[:2]
        sources[0]['warnings'] = ['possible_columns_reading_order_ambiguous']
        self.assertEqual(len(self.groups(sources)), 2)

    def test_sections_and_sentence_end_remain_separate(self):
        for change in ('gap', 'punctuation', 'list'):
            with self.subTest(change=change):
                sources = body()[:2]
                if change == 'gap': sources[1]['bbox'] = [60, 490, 540, 502]
                elif change == 'punctuation': sources[0]['raw_text'] += '.'
                else: sources[1]['raw_text'] = '1. ' + sources[1]['raw_text']
                self.assertEqual(len(self.groups(sources)), 2)

    def test_french_arabic_switch_and_mixed_script_remain_separate(self):
        for lang in ('ar', 'mixed'):
            with self.subTest(lang=lang):
                sources = body()[:2]
                sources[1]['language'] = lang
                self.assertEqual(len(self.groups(sources)), 2)

    def test_rtl_same_row_order_and_tifinagh_ambiguity_preserved(self):
        left = block('المعهدالعاليللقضاء', [20, 20, 180, 38], 'ar')
        right = block('المملكةالمغربية', [420, 20, 580, 38], 'ar')
        sources = order_blocks([left, right]) + [block(None, [20, 42, 180, 56], 'und', direction='und')]
        groups = self.groups(sources)
        self.assertEqual(groups[0]['text'], 'المملكةالمغربية')
        self.assertEqual(groups[1]['text'], 'المعهدالعاليللقضاء')
        self.assertEqual(groups[2]['type'], 'unresolved')
        self.assertIsNone(groups[2]['text'])
        self.assertEqual(groups[2]['direction'], 'und')

    def test_arabic_spacing_proposal_is_not_applied(self):
        source = block('المملكةالمغربية', [420, 20, 580, 38], 'ar',
                       arabic_spacing_proposal={'proposed_text': 'المملكة المغربية', 'human_validated': False})
        groups = self.groups([source])
        self.assertEqual(groups[0]['text'], 'المملكةالمغربية')
        self.assertEqual(source['arabic_spacing_proposal']['proposed_text'], 'المملكة المغربية')

    def test_unreadable_stamp_is_not_invented(self):
        groups = self.groups([block('aroc', [500, 600, 535, 630]), block(None, [500, 640, 530, 660], 'und')])
        self.assertEqual(groups[0]['text'], 'aroc')
        self.assertIsNone(groups[1]['text'])

    def test_native_block_interrupts_ocr_grouping(self):
        sources = body()
        sources[1]['method'] = 'native_pdf'
        groups = self.groups(sources)
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(len(g['source_block_ids']) == 1 for g in groups))

    def test_no_cross_page_merge(self):
        sources = body()[:2]
        sources[1]['page'] = 2
        self.assertEqual(len(self.groups(sources)), 2)

    def test_idempotence_and_markdown_source_ranges(self):
        groups = self.groups(main_title() + body())
        first = copy.deepcopy(groups)
        self.assertEqual(structure_page(self.page, 'f000001'), first)
        md = render({'status': 'completed_with_review', 'pages': [self.page], 'blocks': self.page['blocks']})
        self.assertEqual(md.count('# CAHIER DES PRESCRIPTIONS SPECIALES'), 1)
        self.assertEqual(md.count('08 mats 2023'), 1)
        mapping = {b['block_id']: b for b in self.page['blocks']}
        for group in groups:
            self.assertTrue(group['markdown_lines'])
            for bid in group['source_block_ids']:
                self.assertEqual(mapping[bid]['markdown_lines'], group['markdown_lines'])
                self.assertEqual(mapping[bid]['structure_group_id'], group['group_id'])

    def test_schema_rejects_invalid_structures(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / 'config/conversion.schema.json').read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator({'$ref': '#/$defs/ocr_structure', '$defs': schema['$defs']})
        group = self.groups(main_title() + body())[0]
        validator.validate(group)
        for key, bad in [('heading_level', 4), ('human_validated', True), ('source_block_ids', []), ('raw_texts', [123])]:
            invalid = {**group, key: bad}
            self.assertTrue(list(validator.iter_errors(invalid)), key)


class StructureIntegrationTests(ConversionCase):
    def test_public_api_with_simulated_ocr_has_traceable_markdown_groups(self):
        self.ingestion(pdf_bytes(('scan',)))
        cache = self.mock_ocr()
        data = json.loads(cache.read_text(encoding='utf-8'))
        sources = main_title() + body()
        for b in sources:
            b['bbox'] = [x * (2 / 3 if i % 2 == 0 else .6) for i, x in enumerate(b['bbox'])]
            b['bbox_pdf_points'] = b['bbox']
        data['pages'][0]['blocks'] = sources
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        result = self.convert(options=ConversionOptions(ocr_mode='reuse_only', ocr_results=(str(cache),)))
        self.assertEqual(result['status'], 'completed_with_review', result['errors'])
        self.assertEqual(len(result['blocks']), 5)
        groups = result['pages'][0]['structure']
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]['type'], 'heading')
        self.assertEqual(groups[1]['type'], 'paragraph')
        ids = [bid for g in groups for bid in g['source_block_ids']]
        self.assertEqual(ids, [b['block_id'] for b in result['blocks']])
        md = Path(result['markdown_path']).read_text(encoding='utf-8')
        self.assertIn('# CAHIER DES PRESCRIPTIONS SPECIALES', md)
        self.assertEqual(md.count('08 mats 2023'), 1)


if __name__ == '__main__':
    unittest.main()
