import copy
import json
from pathlib import Path

from table_fixtures import TableCase, HEADERS, MATRIX, table, document, ROOT
from P2_nlp_extraction.table_extraction import extract_tables, TableExtractionLimits, TableExtractionInputError


class ExtractionTests(TableCase):
    def test_split_price_number_header_requires_agreement(self):
        from P2_nlp_extraction.table_extraction.extraction import _price_number_header
        columns = [dict(header_raw=None, candidates=[])]
        grid = dict(page=5, source_reference={'grid_method': 'scan_closed_rectangular_cells_v1'},
                    cell_metadata=[dict(row=0, column=0, ocr_block_ids=['a','b'])])
        readings = {'fr': {'text': 'N°'}, 'ar': {'text': 'No'}}
        ocr = {(5, 'a'): {'raw_text': 'PRIX'}, (5, 'b'): {'raw_text': None, 'recognition_candidates': readings}}
        self.assertEqual(_price_number_header(grid, columns, ocr), 0)
        readings['ar']['text'] = 'HT'
        self.assertIsNone(_price_number_header(grid, columns, ocr))

    def test_simple_ordinary_table_cells_and_order(self):
        item=self.first(document([table([['Couleur','Objet'],['Bleu','Porte']])]))
        self.assertEqual(item['classification'],'ordinary')
        self.assertEqual([[c['value'] for c in r['cells']] for r in item['rows']],[['Couleur','Objet'],['Bleu','Porte']])
        self.assertFalse(item['price_lines'])

    def test_complete_bpu_from_t26(self):
        item=self.first(document(['Bordereau des prix unitaires',table()]),segmented=True)
        self.assertEqual(item['classification'],'bpu')
        self.assertEqual(item['section']['category'],'BPU')
        self.assertEqual(item['price_lines'][0]['fields']['price_number']['value'],'01')
        self.assertEqual(item['price_lines'][0]['arithmetic_check']['status'],'consistent')
        self.assertFalse(item['human_validated'])

    def test_bpu_columns_without_t26_are_only_candidate(self):
        item=self.first()
        self.assertEqual(item['classification'],'bpu_candidate')
        self.assertIsNone(item['section'])

    def test_multiline_bpu_headers_preserve_source_rows(self):
        matrix = [['Désignation', 'Quantité', 'Prix', 'Montant'],
                  ['', '', 'unitaire', 'total'],
                  ['Pose', '2', '10,00', '20,00']]
        item = self.first(document([table(matrix)]))
        self.assertEqual(item['header_row_index'], 1)
        self.assertEqual([row['kind'] for row in item['rows']], ['header_candidate', 'header_candidate', 'data'])
        self.assertEqual(item['price_lines'][0]['arithmetic_check']['status'], 'consistent')

    def test_price_table_is_not_automatically_bpu(self):
        item=self.first(document([table([['Article','Prix'],['A','10,00']])]))
        self.assertEqual(item['classification'],'price_table')
        self.assertFalse(item['price_lines'])
        item=self.first(document([table([['Quantité','Montant'],['2','10,00']])]))
        self.assertEqual(item['classification'],'price_table')
        self.assertFalse(item['price_lines'])

    def test_missing_columns_not_fabricated(self):
        item=self.first(document(['Bordereau des prix unitaires',table([['Désignation','Prix unitaire'],['Travaux','10,20']])]),segmented=True)
        line=item['price_lines'][0]
        self.assertEqual(set(line['fields']),{'designation','unit_price'})
        self.assertIn('quantity',line['missing_fields']);self.assertIsNone(line['arithmetic_check'])

    def test_decimal_comma_grouped_spaces_units_and_zeros_preserved(self):
        matrix=[HEADERS,['0002','Pose','m²','1 000,5','2,00','2 001,00']]
        item=self.first(document([table(matrix)]))
        self.assertEqual(item['price_lines'][0]['fields']['quantity']['value'],'1 000,5')
        self.assertEqual(item['price_lines'][0]['fields']['unit']['value'],'m²')
        self.assertEqual(item['price_lines'][0]['arithmetic_check']['status'],'consistent')

    def test_arabic_headers_text_and_logical_column_order(self):
        matrix=[['رقم الثمن','بيان الأشغال','الوحدة','الكمية','الثمن الوحدوي','المبلغ'],
                ['١','بناء الجدار','متر','2','10,5','21']]
        item=self.first(document([table(matrix,language='ar')]))
        self.assertEqual(item['classification'],'bpu_candidate')
        self.assertEqual(item['price_lines'][0]['fields']['designation']['value'],'بناء الجدار')
        self.assertEqual([c['value'] for c in item['rows'][0]['cells']],matrix[0])

    def test_empty_and_unreadable_cells_distinguished(self):
        item=self.first(document([table([HEADERS,['01','','m³',None,'100,20','']])]))
        self.assertEqual(item['rows'][1]['cells'][1]['status'],'empty')
        self.assertEqual(item['rows'][1]['cells'][3]['status'],'unreadable')
        self.assertIsNone(item['rows'][1]['cells'][3]['value']);self.assertEqual(item['status'],'partial')

    def test_complex_table_is_partial_without_invented_cells(self):
        spec=table();spec['structure_preserved']=False
        item=self.first(document([spec]))
        self.assertEqual(item['status'],'partial');self.assertEqual(item['rows'],[])
        self.assertEqual(item['source_block']['cells'],MATRIX)
        self.assertEqual(self.csv_rows('tables_csv'),[])

    def test_irregular_contours_export_merged_cells_without_crossing_ocr(self):
        grid = dict(type='table', method='ocr', raw_text=None, bbox=[0, 0, 100, 60],
                    structure_preserved=False, source_reference=dict(
                        grid_method='scan_irregular_cell_candidates_v1',
                        candidate_cell_boxes=[[1, 1, 99, 18], [1, 21, 48, 39], [51, 21, 99, 39],
                                              [1, 41, 48, 59], [51, 41, 99, 59]],
                        ocr_block_ids=['title', 'left', 'cross']))
        lines = [dict(raw_text=text, method='ocr', bbox=box, reading_order=index,
                      source_reference=dict(ocr_block_id=key))
                 for index, (key, box, text) in enumerate([
                     ('title', [6, 3, 94, 15], 'Matériels'),
                     ('left', [8, 24, 43, 34], 'Tondeuse'),
                     ('cross', [42, 45, 56, 54], 'Ambigu')], 1)]
        lines.append(dict(raw_text=None, method='ocr', bbox=[58, 24, 90, 34], reading_order=4,
                          source_reference=dict(ocr_block_id='unresolved'),
                          recognition_candidates={'fr': {'text': '02'}, 'ar': {'text': '02?'}}))
        grid['source_reference']['ocr_block_ids'].append('unresolved')
        item = self.first(document([grid, *lines]))
        self.assertEqual(item['status'], 'partial')
        rows = item['rows']
        self.assertEqual([[c['value'] for c in row['cells']] for row in rows],
                         [['Matériels', None], ['Tondeuse', None], [None, None]])
        self.assertEqual(rows[0]['cells'][0]['source']['cell_metadata']['column_span'], 2)
        self.assertEqual(rows[0]['cells'][1]['source']['cell_metadata']['covered_by'], [0, 0])
        self.assertEqual(json.loads(self.csv_rows('tables_csv')[2]['source_reference'])['ocr_block_ids'], ['left'])
        alternatives = json.loads(self.csv_rows('tables_csv')[3]['source_reference'])['ocr_alternatives']
        self.assertEqual({item['text'] for item in alternatives['unresolved'].values()}, {'02', '02?'})
        for cell in rows[2]['cells']:
            self.assertEqual(cell['source']['cell_metadata']['ambiguous_ocr_block_ids'], ['cross'])
        self.assertEqual(item['price_lines'], [])

    def test_ragged_or_bad_matrix_is_partial(self):
        for matrix in ([['A','B'],['C']],[[1,'x']],[],None):
            with self.subTest(matrix=matrix):
                spec=table();spec['cells']=matrix
                item=self.first(document([spec]))
                self.assertEqual(item['status'],'partial');self.assertEqual(item['rows'],[])

    def test_consecutive_pages_are_candidates_not_merged(self):
        result=self.run_document(document(['Bordereau des prix unitaires',table(),table(page=2)]),segmented=True)
        self.assertEqual(len(result['tables']),2)
        self.assertEqual(result['tables'][0]['continuation_candidates'][0]['table_id'],'t000002')
        self.assertEqual(len(result['tables'][0]['price_lines']),1)

    def test_different_sections_or_nonconsecutive_pages_not_joined(self):
        for specs in (['Bordereau des prix unitaires',table(),{'raw_text':'Cahier des prescriptions spéciales','page':2},table(page=2)],
                      [table(),table(page=3)]):
            result=self.run_document(document(specs),segmented=True)
            self.assertTrue(all(not t['continuation_candidates'] for t in result['tables']))

    def test_duplicate_and_ambiguous_columns_not_chosen(self):
        item=self.first(document(['Bordereau des prix unitaires',table([['Désignation','Prix','Prix unitaire','Prix unitaire'],['A','10','10','20']])]),segmented=True)
        self.assertEqual(set(item['price_lines'][0]['fields']),{'designation'})
        self.assertIn('ambiguous_or_duplicate_column_labels',item['warnings'])

    def test_repeated_header_preserved_but_not_a_price_line(self):
        item=self.first(document([table([HEADERS,MATRIX[1],HEADERS,MATRIX[1]])]))
        self.assertEqual(len(item['rows']),4);self.assertEqual(len(item['price_lines']),2)
        self.assertEqual(item['rows'][2]['kind'],'repeated_header_candidate')

    def test_blank_row_not_a_price_line(self):
        item=self.first(document([table([HEADERS,['']*6])]))
        self.assertEqual(len(item['rows']),2);self.assertFalse(item['price_lines'])

    def test_unknown_header_in_bpu_not_inferred(self):
        item=self.first(document(['Bordereau des prix unitaires',table([['A','B'],['C','D']])]),segmented=True)
        self.assertEqual(item['classification'],'bpu');self.assertFalse(item['price_lines'])
        self.assertIsNone(item['header_row_index'])

    def test_arithmetic_discrepancy_warned_not_corrected(self):
        matrix=[HEADERS,['01','A','u','2','10,00','25,00']]
        item=self.first(document([table(matrix)]))
        line=item['price_lines'][0]
        self.assertEqual(line['arithmetic_check']['status'],'mismatch')
        self.assertEqual(line['fields']['amount']['value'],'25,00')
        self.assertIn('arithmetic_difference_observed_not_corrected',line['warnings'])

    def test_currency_or_ambiguous_numbers_not_used_for_arithmetic(self):
        for value in ('1.000,20','10 MAD','illisible','9'*80):
            item=self.first(document([table([HEADERS,['01','A','u','2',value,'25']])]))
            self.assertEqual(item['price_lines'][0]['arithmetic_check']['status'],'not_checked')

    def test_no_tables_is_not_proof_of_absence(self):
        result=self.run_document(document(['Texte sans tableau structuré.']))
        self.assertEqual(result['tables'],[])
        self.assertEqual(self.csv_rows('tables_csv'),[])
        self.assertIn('no_structured_table_blocks_available_not_proof_of_absence',result['warnings'])

    def test_partial_document_and_missing_pages(self):
        result=self.run_document(document([table()],total=28))
        self.assertEqual(result['status'],'partial')
        data=document([],status='failed',total=28);data['errors']=[{'code':'ocr_failed','message':'Synthetic'}]
        result=self.run_document(data)
        self.assertEqual(result['source_errors'],data['errors']);self.assertEqual(result['status'],'partial')

    def test_provenance_source_block_hypotheses_and_cell_metadata(self):
        data=document([table(method='ocr',cell_metadata=[{'row':1,'column':1,'column_span':1,'text':'Béton — خرسانة'}],
                             recognition_candidates=[{'text':'hypothèse'}])])
        item=self.first(data)
        self.assertEqual(item['source_block'],data['blocks'][0])
        source=item['rows'][1]['cells'][1]['source']
        self.assertEqual(source['cell_metadata'],data['blocks'][0]['cell_metadata'][0])
        self.assertIsNone(source['bbox']);self.assertEqual(source['table_bbox'],data['blocks'][0]['bbox'])

    def test_docx_no_page_or_cell_position_invented(self):
        item=self.first(document([table()],docx=True))
        self.assertEqual(item['pages'],[]);self.assertIsNone(item['bbox'])

    def test_ambiguous_title_does_not_claim_bpu_section(self):
        result=self.run_document(document([{'raw_text':'RC / BPU','type':'heading'},table()]),segmented=True)
        self.assertIsNone(result['tables'][0]['section'])
        self.assertEqual(result['tables'][0]['classification'],'bpu_candidate')
        self.assertIn('ambiguous_titles_require_review',result['segmentation_warnings'])

    def test_duplicate_cell_metadata_is_not_arbitrarily_chosen(self):
        entry={'row':1,'column':0,'text':'01'}
        item=self.first(document([table(cell_metadata=[entry,dict(entry,text='02')])]))
        self.assertIsNone(item['rows'][1]['cells'][0]['source']['cell_metadata'])
        self.assertIn('duplicate_cell_metadata_not_assigned',item['warnings'])


class ExportAndInputTests(TableCase):
    def test_json_schemas_and_csv_roundtrip_utf8(self):
        from jsonschema import Draft202012Validator
        matrix=[HEADERS,['01','Texte; "cité"\nعربي','m³','2,5','100,20','250,50']]
        self.first(document([table(matrix)]))
        for name in ('tables','bpu'):
            schema=json.loads((ROOT/f'config/{name}.schema.json').read_text(encoding='utf-8'))
            Draft202012Validator.check_schema(schema)
            data=json.loads(Path(self.result['output_paths'][name+'_json']).read_text(encoding='utf-8'))
            Draft202012Validator(schema).validate(data)
        csv=self.csv_rows('tables_csv')
        self.assertEqual(csv[7]['value'],matrix[1][1])
        self.assertEqual(self.csv_rows('bpu_csv')[0]['unit_price'],'100,20')

    def test_inputs_unchanged_and_unique_runs(self):
        data=document(['Bordereau des prix unitaires',table()]);before=copy.deepcopy(data)
        first=self.run_document(data,segmented=True)
        original=self.path.read_bytes();segoriginal=self.segpath.read_bytes()
        second=extract_tables(self.path,self.segpath,self.folder/'tables')
        self.assertNotEqual(first['run_directory'],second['run_directory'])
        self.assertEqual(original,self.path.read_bytes());self.assertEqual(segoriginal,self.segpath.read_bytes())
        self.assertEqual(data,before)

    def test_mismatched_segmentation_hash_rejected(self):
        self.run_document(document(['Bordereau des prix unitaires',table()]),segmented=True)
        data=json.loads(self.segpath.read_text(encoding='utf-8'));data['source']['conversion_json_sha256']='0'*64
        self.segpath.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(TableExtractionInputError):extract_tables(self.path,self.segpath,self.folder/'bad')
        self.assertFalse((self.folder/'bad').exists())

    def test_forged_segmentation_spans_rejected(self):
        self.run_document(document(['Bordereau des prix unitaires',table()]),segmented=True)
        data=json.loads(self.segpath.read_text(encoding='utf-8'));data['sections'][0]['end_block_index']=500
        self.segpath.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(TableExtractionInputError):extract_tables(self.path,self.segpath,self.folder/'bad')

    def test_external_output_path_rejected_without_creation(self):
        self.run_document(document([table()]))
        with self.assertRaises(TableExtractionInputError):extract_tables(self.path,output_dir=ROOT.parent/'outside')
        with self.assertRaises(TableExtractionInputError):extract_tables(self.path,output_dir=ROOT/'../outside')

    def test_external_input_path_rejected(self):
        with self.assertRaises(TableExtractionInputError):extract_tables(ROOT.parent/'document.json')

    def test_limits_checked_before_exports(self):
        for limit in (TableExtractionLimits(max_input_bytes=10),TableExtractionLimits(max_blocks=1),
                      TableExtractionLimits(max_tables=1),TableExtractionLimits(max_cells=2),
                      TableExtractionLimits(max_output_bytes=10)):
            with self.subTest(limit=limit),self.assertRaises(TableExtractionInputError):
                self.run_document(document([table(),table()]),limits=limit)

    def test_duplicate_ids_or_page_divergence_rejected(self):
        data=document([table(),table()]);data['blocks'][1]['block_id']=data['blocks'][0]['block_id']
        with self.assertRaises(TableExtractionInputError):self.run_document(data)
        data=document([table()]);data['pages'][0]['blocks']=[]
        with self.assertRaises(TableExtractionInputError):self.run_document(data)

    def test_processing_document_rejected(self):
        with self.assertRaises(TableExtractionInputError):self.run_document(document([],status='processing'))

    def test_nonfinite_and_duplicate_json_rejected(self):
        for text in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e999}'):
            path=self.folder/'invalid.json';path.write_text(text,encoding='utf-8')
            with self.assertRaises(TableExtractionInputError):extract_tables(path,self.folder/'missing.json')

    def test_csv_empty_and_null_use_status_to_distinguish(self):
        self.first(document([table([HEADERS,['01','','u',None,'10','']])]))
        rows=self.csv_rows('tables_csv')
        self.assertEqual(rows[7]['value'],'');self.assertEqual(rows[7]['cell_status'],'empty')
        self.assertEqual(rows[9]['value'],'');self.assertEqual(rows[9]['cell_status'],'unreadable')
