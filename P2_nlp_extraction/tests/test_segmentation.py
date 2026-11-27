import copy
import json
from pathlib import Path

from segmentation_fixtures import SegmentationCase, document, ROOT
from P2_nlp_extraction.document_segmentation import SegmentationInputError, SegmentationLimits, segment_document
from P2_nlp_extraction.document_segmentation.rules import TITLES


class DetectionTests(SegmentationCase):
    def test_masked_table_title_not_promoted_or_rendered_twice(self):
        title='Cahier des prescriptions spéciales'
        for markers in ({'render':False}, {'warnings':['represented_in_table']},
                        {'render':False,'warnings':['represented_in_table']}):
            with self.subTest(markers=markers):
                data=document(['Règlement de consultation',
                    {'raw_text':None,'type':'table','cells':[[title,'Valeur']],
                     'structure_preserved':True}, dict(raw_text=title,**markers)])
                original=copy.deepcopy(data)
                result=self.run_document(data)
                self.assertEqual([s['category'] for s in result['sections']],['RC'])
                self.assertFalse(result['candidates'])
                md=Path(result['markdown_path']).read_text(encoding='utf-8')
                self.assertEqual(md.count(title),1)
                self.assertIn('| '+title+' | Valeur |',md)
                self.assertEqual(result['blocks'],original['blocks'])
                self.assertEqual(data,original)
        irregular = document(['Règlement de consultation',
                              dict(raw_text=title, warnings=['ambiguous_table_cell'])])
        result = self.run_document(irregular)
        self.assertEqual([s['category'] for s in result['sections']], ['RC'])
        self.assertIn(title, Path(result['markdown_path']).read_text(encoding='utf-8'))

    def test_real_titles_outside_tables_remain_detected(self):
        titles=[aliases[0] for aliases in TITLES.values()]
        specs=[]
        for title in titles:
            specs.extend([{'raw_text':title,'render':False,'warnings':['represented_in_table']},
                          {'raw_text':title,'type':'heading','heading_level':1},'Texte de section'])
        result=self.run_document(document(specs))
        self.assertEqual([s['category'] for s in result['sections']],list(TITLES))
        md=Path(result['markdown_path']).read_text(encoding='utf-8')
        for title in titles:self.assertEqual(md.count(title),1)

    def test_masked_articles_and_toc_do_not_change_structure(self):
        data=document(['Règlement de consultation',
                       {'raw_text':'Article 99 : Faux article','render':False},
                       {'raw_text':'Sommaire','warnings':['represented_in_table']},
                       'Cahier des prescriptions spéciales','Article 1 : Objet'])
        result=self.run_document(data)
        self.assertEqual([s['category'] for s in result['sections']],['RC','CPS'])
        self.assertFalse(result['sections'][0]['children'])
        self.assertEqual(result['sections'][1]['children'][0]['number'],'1')
        self.assertEqual(result['blocks'],data['blocks'])

    def test_masked_multiline_title_is_not_joined(self):
        data=document([{'raw_text':'CAHIER DES PRESCRIPTIONS','type':'heading'},
                       {'raw_text':'SPECIALES','type':'heading','warnings':['represented_in_table']}])
        result=self.run_document(data)
        self.assertFalse(result['sections'])
        self.assertNotIn('SPECIALES',Path(result['markdown_path']).read_text(encoding='utf-8'))
        self.assertEqual(result['blocks'],data['blocks'])

    def test_five_categories_and_all_registered_variants(self):
        for category, aliases in TITLES.items():
            for alias in aliases:
                with self.subTest(category=category,alias=alias):
                    result=self.run_document(document([alias,'Corps du document.']))
                    self.assertEqual([s['category'] for s in result['sections']],[category])

    def test_case_accents_punctuation_and_numbered_title(self):
        result=self.run_document(document(['II - CAHIER DES PRESCRIPTIONS SPECIALES (CPS)']))
        self.assertEqual(result['sections'][0]['category'],'CPS')

    def test_multiple_sections_original_order_and_preamble(self):
        result=self.run_document(document(['Préambule','Règlement de consultation','Texte RC',
                          'Cahier des prescriptions spéciales','Texte CPS','Bordereau des prix unitaires','Texte BPU']))
        self.assertEqual([s['category'] for s in result['sections']],['RC','CPS','BPU'])
        self.assertEqual(result['unassigned_block_ids'],['f000001_b000001'])
        self.assertEqual([len(s['source_block_ids']) for s in result['sections']],[2,2,2])

    def test_articles_numbered_subsections_and_nested_spans(self):
        result=self.run_document(document(['Cahier des prescriptions spéciales','1.1 Dispositions générales',
                                  'Article 1 : Objet','Texte objet','Article II — Durée','Douze mois.']))
        subsection=result['sections'][0]['children'][0]
        self.assertEqual(subsection['kind'],'subsection')
        self.assertEqual([a['number'] for a in subsection['children']],['1','II'])
        self.assertEqual(subsection['children'][0]['source_block_ids'],['f000001_b000003','f000001_b000004'])
        self.assertEqual(result['sections'][0]['source_block_ids'],[b['block_id'] for b in result['blocks']])

    def test_multipage_section(self):
        result=self.run_document(document(['Cahier des prescriptions spéciales',{'raw_text':'Suite','page':2}]))
        self.assertEqual(result['sections'][0]['pages'],[1,2])
        self.assertTrue(result['sections'][0]['extent_complete'])

    def test_prose_mentions_are_not_titles(self):
        result=self.run_document(document(['Le CPS et ses dispositions sont applicables.',
                                          'Conformément au règlement de consultation, fournir une attestation.']))
        self.assertEqual(result['sections'],[])

    def test_bare_acronym_requires_heading_evidence(self):
        result=self.run_document(document(['CPS']))
        self.assertFalse(result['sections']);self.assertTrue(result['candidates'])
        result=self.run_document(document([{'raw_text':'C.P.S.','type':'heading','heading_level':1}]))
        self.assertEqual(result['sections'][0]['category'],'CPS')

    def test_compound_title_ambiguous(self):
        result=self.run_document(document([{'raw_text':'RC / CPS','type':'heading'}]))
        self.assertFalse(result['sections'])
        self.assertEqual(set(result['candidates'][0]['category_candidates']),{'RC','CPS'})

    def test_toc_and_dotted_references_do_not_create_sections(self):
        for texts in (['Sommaire','Règlement de consultation','Cahier des prescriptions spéciales'],
                      ['Cahier des prescriptions spéciales .... 12']):
            result=self.run_document(document(texts))
            self.assertFalse(result['sections']);self.assertTrue(result['candidates'])

    def test_header_and_table_title_are_not_boundaries(self):
        for extras in ({'role':'header'},{'type':'table'}):
            result=self.run_document(document([dict(raw_text='Cahier des prescriptions spéciales',**extras)]))
            self.assertFalse(result['sections'])

    def test_repeated_title_is_ambiguous_continuation(self):
        result=self.run_document(document(['Cahier des prescriptions spéciales',
                             {'raw_text':'Cahier des prescriptions spéciales','page':2}]))
        self.assertEqual(len(result['sections']),1)
        self.assertEqual(len(result['candidates']),1)

    def test_two_line_ocr_title_geometry(self):
        data=document([{'raw_text':'CAHIER DES PRESCRIPTIONS','method':'ocr','bbox':[50,100,350,120]},
                       {'raw_text':'SPECIALES','method':'ocr','bbox':[140,125,260,145]}])
        result=self.run_document(data)
        section=result['sections'][0]
        self.assertEqual(section['title_raw'],'CAHIER DES PRESCRIPTIONS SPECIALES')
        self.assertEqual(len(section['title_block_ids']),2)
        self.assertEqual(result['blocks'],data['blocks'])

    def test_split_title_different_pages_or_columns_not_joined(self):
        for extra in ({'page':2},{'bbox':[400,125,500,145]}):
            result=self.run_document(document([{'raw_text':'CAHIER DES PRESCRIPTIONS','bbox':[50,100,350,120]},
                                               dict(raw_text='SPECIALES',**extra)]))
            self.assertFalse(result['sections'])

    def test_arabic_articles_raw_hypotheses_and_coordinates_preserved(self):
        data=document([{'raw_text':'دفتر الشروط الخاصة','language':'ar','method':'ocr'},
                       {'raw_text':'المادة ١ : موضوع العقد','language':'ar','method':'ocr',
                        'recognition_candidates':[{'text':'موضوعالعقد'}],
                        'arabic_spacing_proposal':'موضوع العقد'},
                       {'raw_text':'Texte français — نص عربي','language':'mixed'}])
        result=self.run_document(data)
        self.assertEqual(result['blocks'],data['blocks'])
        self.assertEqual(result['sections'][0]['children'][0]['number'],'١')
        self.assertIn('دفتر الشروط الخاصة',Path(result['markdown_path']).read_text(encoding='utf-8'))

    def test_possible_article_in_prose_needs_review(self):
        result=self.run_document(document(['Cahier des prescriptions spéciales','Article 5 prévoit la remise des pièces.']))
        self.assertFalse(result['sections'][0]['children']);self.assertTrue(result['candidates'])

    def test_docx_has_no_invented_page_numbers(self):
        result=self.run_document(document(['Règlement de consultation','Article premier : Objet'],docx=True))
        self.assertEqual(result['sections'][0]['pages'],[])
        self.assertTrue(all(b['bbox'] is None for b in result['blocks']))

    def test_partial_coverage_and_failed_empty_document(self):
        result=self.run_document(document(['Cahier des prescriptions spéciales'],total=28))
        self.assertEqual(result['status'],'partial');self.assertFalse(result['sections'][0]['extent_complete'])
        data=document([],status='failed',total=28)
        data['errors']=[{'code':'ocr_failed','message':'Synthetic failure'}]
        data['warnings']=['original_warning']
        result=self.run_document(data)
        self.assertEqual(result['sections'],[]);self.assertEqual(result['source_errors'],data['errors'])
        self.assertEqual(result['source_warnings'],data['warnings'])

    def test_huge_source_page_count_is_not_allocated(self):
        result=self.run_document(document(['Règlement de consultation'],total=10**12))
        self.assertEqual(result['status'],'partial')

    def test_null_unresolved_and_complex_table_not_invented(self):
        result=self.run_document(document(['Cahier des prescriptions spéciales',
                            {'raw_text':None,'type':'unresolved','language':'und'},
                            {'raw_text':None,'type':'table','structure_preserved':False}]))
        self.assertEqual(len(result['blocks']),3)
        md=Path(result['markdown_path']).read_text(encoding='utf-8')
        self.assertIn('structure non restituée',md);self.assertIn('sans texte reconnu',md)


class ContractTests(SegmentationCase):
    def test_ocr_structure_groups_and_provenance_retained(self):
        data=document([{'raw_text':'CAHIER DES PRESCRIPTIONS','method':'ocr'},
                       {'raw_text':'SPECIALES','method':'ocr'}])
        group=dict(group_id='f000001_p0001_s000001',type='heading',method='ocr',page=1,
                   source_block_ids=[b['block_id'] for b in data['blocks']],
                   raw_texts=[b['raw_text'] for b in data['blocks']],text='CAHIER DES PRESCRIPTIONS SPECIALES',
                   bbox=[20,30,380,80],language='fr',direction='ltr',heading_level=1,
                   join_policy='space_between_source_blocks',human_validated=False,needs_review=True,
                   warnings=[],markdown_lines=None,inference=dict(version='p2.ocr_structure.v1',
                   rule='aligned_adjacent_lines',evidence={'test':True}))
        data['pages'][0]['structure']=[group]
        result=self.run_document(data)
        self.assertEqual(result['sections'][0]['category'],'CPS')
        self.assertEqual(result['pages'][0]['structure'],[group])
        group['raw_texts'][0]='Texte différent'
        with self.assertRaises(SegmentationInputError):self.run_document(data)

    def test_page_failure_and_inconsistent_coverage_remain_partial(self):
        data=document(['Règlement de consultation'])
        data['pages'][0]['errors']=[{'code':'partial_page','message':'Synthetic'}]
        self.assertEqual(self.run_document(data)['status'],'partial')
        data=document([{'raw_text':'Règlement de consultation','page':2}],total=1)
        data['coverage']['processed_pages']=[1]
        self.assertEqual(self.run_document(data)['status'],'partial')

    def test_schema_persistence_no_input_mutation_unique_runs(self):
        from jsonschema import Draft202012Validator
        data=document(['Règlement de consultation','Article 1 : Objet'])
        original=copy.deepcopy(data)
        first=self.run_document(data)
        before=self.path.read_bytes()
        second=segment_document(self.path,self.folder/'results')
        self.assertNotEqual(first['run_directory'],second['run_directory'])
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(data,original)
        persisted=json.loads(Path(first['sections_json_path']).read_text(encoding='utf-8'))
        schema=json.loads((ROOT/'config/segmentation.schema.json').read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema);Draft202012Validator(schema).validate(persisted)
        self.assertFalse(persisted['human_validated'])
        self.assertFalse(persisted['sections'][0]['confidence']['calibrated'])

    def test_markdown_only_promotes_matching_mapped_heading(self):
        data=document([{'raw_text':'CPS','markdown_lines':[1,1]}])
        result=self.run_document(data,markdown='# CPS\n')
        self.assertEqual(result['sections'][0]['category'],'CPS')
        result=self.run_document(data,markdown='# RC\n')
        self.assertFalse(result['sections']);self.assertIn('markdown_heading_text_mismatch',result['warnings'])

    def test_duplicate_ids_and_divergent_page_blocks_rejected(self):
        data=document(['Règlement de consultation','Texte'])
        data['blocks'][1]['block_id']=data['blocks'][0]['block_id']
        with self.assertRaises(SegmentationInputError):self.run_document(data)
        data=document(['Règlement de consultation'])
        data['pages'][0]['blocks']=[]
        with self.assertRaises(SegmentationInputError):self.run_document(data)

    def test_limits_and_unfinished_conversion(self):
        for limits in (SegmentationLimits(max_input_bytes=10),SegmentationLimits(max_blocks=1),
                       SegmentationLimits(max_output_bytes=10)):
            with self.subTest(limits=limits),self.assertRaises(SegmentationInputError):
                self.run_document(document(['Règlement de consultation','Texte']),limits=limits)
        with self.assertRaises(SegmentationInputError):self.run_document(document([],status='processing'))

    def test_external_paths_and_duplicate_json_keys_rejected(self):
        with self.assertRaises(SegmentationInputError):segment_document(ROOT.parent/'outside.json')
        self.path=self.folder/'document.json';self.path.write_text('{"x":1,"x":2}',encoding='utf-8')
        with self.assertRaises(SegmentationInputError):segment_document(self.path)

    def test_unsafe_markdown_escaped_without_changing_raw_json(self):
        data=document(['Règlement de consultation','<script>alert(1)</script> # CPS'])
        result=self.run_document(data)
        self.assertEqual(result['blocks'],data['blocks'])
        self.assertNotIn('<script>',Path(result['markdown_path']).read_text(encoding='utf-8'))
