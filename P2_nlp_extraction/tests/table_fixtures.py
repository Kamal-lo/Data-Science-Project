import json
from pathlib import Path
import unittest

from segmentation_fixtures import document, ROOT, temporary_folder
from P2_nlp_extraction.document_segmentation import segment_document
from P2_nlp_extraction.table_extraction import extract_tables

HEADERS=['N° de prix','Désignation','Unité','Quantité','Prix unitaire','Montant']
MATRIX=[HEADERS,['01','Béton — خرسانة','m³','2,5','100,20','250,50']]


def table(matrix=None, **kwargs):
    matrix=MATRIX if matrix is None else matrix
    return dict(raw_text='Source de tableau, non reconstruite.',type='table',cells=matrix,
                structure_preserved=True,**kwargs)


class TableCase(unittest.TestCase):
    def setUp(self):
        self.folder=temporary_folder(self)

    def run_document(self,data,segmented=False,**kwargs):
        self.path=self.folder/'document.json'
        self.path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        self.segpath=None
        if segmented:
            result=segment_document(self.path,self.folder/'segmentation')
            self.segpath=Path(result['sections_json_path'])
        self.result=extract_tables(self.path,self.segpath,self.folder/'tables',**kwargs)
        return self.result

    def first(self,data=None,**kwargs):
        return self.run_document(data or document([table()]),**kwargs)['tables'][0]

    def csv_rows(self,name):
        import csv
        with Path(self.result['output_paths'][name]).open(encoding='utf-8-sig',newline='') as stream:
            return list(csv.DictReader(stream,delimiter=';'))
