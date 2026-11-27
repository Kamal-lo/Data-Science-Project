from conversion_fixtures import ConversionCase, ROOT
from P2_nlp_extraction.table_extraction import extract_tables


class IntegrationTests(ConversionCase):
    def test_recorded_real_dce_cover_does_not_invent_table(self):
        source=ROOT/'outputs/conversion/t24_real_page1_auto_20261119T000047_461540Z/conversion/20261119T000111_255875Z_f225f118/documents/f000001/document.json'
        if not source.exists():self.skipTest('Sortie réelle T24 locale non distribuée.')
        result=extract_tables(source,output_dir=self.folder/'cover')
        self.assertEqual(result['tables'],[])
        self.assertEqual(result['status'],'partial')
