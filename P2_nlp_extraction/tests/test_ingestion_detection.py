"""Détection par contenu et éligibilité T24, sans OCR."""
from ingestion_fixtures import IngestionCase, docx_bytes, pdf_bytes, zip_bytes


class DetectionTests(IngestionCase):
    def test_pdf_without_extension_and_false_docx_extension(self):
        for name in ('sans_extension', 'faux.docx'):
            with self.subTest(name=name):
                result = self.direct(pdf_bytes(), name)
                item = result['files'][0]
                self.assertEqual(item['detected_type'], 'pdf')
                self.assertTrue(item['eligible_for_t24'])
                self.assertIn('extension_mismatch', item['warnings'])

    def test_real_docx_disguised_as_pdf(self):
        result = self.direct(docx_bytes(), 'document.pdf')
        item = result['files'][0]
        self.assertEqual(item['detected_type'], 'docx')
        self.assertTrue(item['eligible_for_t24'])
        self.assertIn('extension_mismatch', item['warnings'])

    def test_fake_pdf_and_empty_file_are_not_eligible(self):
        for data in (b'not a PDF', b'', b'%PDF-1.7\ninvalid'):
            result = self.direct(data, 'faux.pdf')
            self.assertFalse(result['eligible_for_t24'])
            self.assertNotEqual(result['files'][0]['status'], 'ready')

    def test_encrypted_pdf_is_detected_but_blocked(self):
        result = self.direct(pdf_bytes(encrypted=True), 'protected.pdf')
        item = result['files'][0]
        self.assertEqual(item['detected_type'], 'pdf')
        self.assertEqual(item['reason'], 'password_required')
        self.assertFalse(item['eligible_for_t24'])

    def test_repaired_pdf_is_not_automatically_eligible(self):
        data = pdf_bytes()
        result = self.direct(data[:data.index(b'xref')], 'damaged.pdf')
        item = result['files'][0]
        self.assertFalse(item['eligible_for_t24'])
        self.assertIn(item['status'], ('blocked', 'invalid'))

    def test_incomplete_office_container_not_docx(self):
        result = self.direct(zip_bytes([('word/document.xml', '<x/>')]), 'broken.docx')
        self.assertEqual(result['files'][0]['status'], 'invalid')
        self.assertFalse(result['eligible_for_t24'])

    def test_docm_and_hidden_macros_not_eligible(self):
        result = self.direct(docx_bytes(main_type='application/vnd.ms-word.document.macroEnabled.main+xml'), 'macro.docm')
        self.assertEqual(result['files'][0]['detected_type'], 'docm')
        self.assertFalse(result['eligible_for_t24'])
        self.assert_rejected(self.direct(docx_bytes(extra=[('word/vbaProject.bin', b'macro')]), 'hidden.docx'), 'macro_content_detected')

    def test_malformed_xml_and_wrong_word_body(self):
        for main in ('<broken>', '<x/>',
                     '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/><w:body/></w:document>'):
            result = self.direct(docx_bytes(main=main), 'invalid.docx')
            self.assertEqual(result['files'][0]['status'], 'invalid')
            self.assertFalse(result['eligible_for_t24'])

    def test_external_main_relationship_not_followed(self):
        rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="https://example.invalid/document.xml" TargetMode="External"/></Relationships>'
        result = self.direct(docx_bytes(relationships=rels), 'external.docx')
        self.assertFalse(result['eligible_for_t24'])
        self.assertEqual(result['files'][0]['status'], 'invalid')

    def test_docx_internal_crc_is_checked(self):
        data = bytearray(docx_bytes(extra=[('word/media/test.bin', b'PAYLOAD')]))
        pos = data.index(b'PAYLOAD'); data[pos] ^= 1
        self.assert_rejected(self.direct(bytes(data), 'bad.docx'), 'corrupt_zip')

    def test_unknown_regular_files_preserved_without_t24(self):
        result = self.direct(zip_bytes([('prix.csv', 'designation,prix\nobjet,10'), ('image.bin', b'unknown')]))
        self.assertEqual(result['status'], 'completed_with_issues')
        self.assertTrue(all(f['artifact_path'] and not f['eligible_for_t24'] for f in result['files']))

    def test_ordinary_zip_with_word_named_folder_is_not_docx(self):
        result = self.direct(zip_bytes([('word/CPS.pdf', pdf_bytes())]), 'ordinary.docx')
        self.assertEqual(result['source']['detected_type'], 'zip')
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['files'][0]['eligible_for_t24'])
