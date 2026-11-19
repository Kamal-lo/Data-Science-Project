import json
from pathlib import Path
import unittest

from conversion_fixtures import ConversionCase, pdf_bytes
from P2_nlp_extraction.document_conversion import ConversionInputError, ConversionLimits, ConversionOptions
from P2_nlp_extraction.document_conversion.manifest_validation import validate_manifest, load_json


class ManifestTests(ConversionCase):
    def test_completed_only(self):
        self.ingestion()
        self.change_manifest(lambda m: m.update(status='processing', eligible_for_t24=False))
        with self.assertRaises(ConversionInputError):
            self.convert()

    def test_not_eligible_selected_file(self):
        self.ingestion()
        self.change_manifest(lambda m: m['files'][0].update(eligible_for_t24=False))
        with self.assertRaises(ConversionInputError):
            self.convert()

    def test_unknown_file_id(self):
        self.ingestion()
        with self.assertRaises(ConversionInputError):
            self.convert(file_id='f999999')

    def test_traversal_absolute_and_noncanonical_paths(self):
        self.ingestion()
        original = self.manifest.read_text(encoding='utf-8')
        for unsafe in ('../document.pdf', 'C:/private/document.pdf', '/tmp/document.pdf', 'a/../document.pdf', 'a\\document.pdf'):
            with self.subTest(path=unsafe):
                self.manifest.write_text(original, encoding='utf-8')
                self.change_manifest(lambda m: m['files'][0].update(relative_path=unsafe, artifact_path='files/' + unsafe))
                with self.assertRaises(ConversionInputError):
                    self.convert()

    def test_manifest_parent_identity(self):
        self.ingestion()
        self.change_manifest(lambda m: m.update(run_id='forged'))
        with self.assertRaises(ConversionInputError):
            self.convert()

    def test_duplicate_file_ids(self):
        self.ingestion()
        self.change_manifest(lambda m: m['files'].append(m['files'][0].copy()))
        with self.assertRaises(ConversionInputError):
            self.convert()

    def test_duplicate_json_keys(self):
        path = self.folder / 'duplicate.json'; path.write_text('{"a":1,"a":2}')
        with self.assertRaises(ConversionInputError):
            load_json(path, 1024)

    def test_modified_artifact_rejected(self):
        self.ingestion()
        (self.manifest.parent / self.item['artifact_path']).write_bytes(pdf_bytes(('native', 'native')))
        result = self.convert()
        self.assertEqual(result['status'], 'rejected')
        self.assertFalse(result['blocks'])
        self.assertIn(result['errors'][0]['code'], ('source_size_mismatch', 'source_integrity_mismatch'))

    def test_wrong_hash_rejected(self):
        self.ingestion()
        self.change_manifest(lambda m: m['files'][0].update(sha256='0' * 64))
        result = self.convert()
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['errors'][0]['code'], 'source_integrity_mismatch')

    def test_wrong_real_type_rejected(self):
        self.ingestion()
        self.change_manifest(lambda m: m['files'][0].update(detected_type='docx'))
        self.assertEqual(self.convert()['errors'][0]['code'], 'source_type_mismatch')

    def test_manifest_size_limit(self):
        self.ingestion()
        with self.assertRaises(ConversionInputError):
            validate_manifest(self.manifest, ConversionLimits(max_manifest_bytes=10))

    def test_limits_and_options_reject_invalid_values(self):
        for limits in (ConversionLimits(max_pages=0), ConversionLimits(timeout_seconds=float('nan')), ConversionLimits(max_blocks=True)):
            with self.assertRaises(ValueError):
                limits.validate()
        for options in (ConversionOptions(ocr_mode='guess'), ConversionOptions(pdf_pages=(1, 1)), ConversionOptions(ocr_dpi=100)):
            with self.assertRaises(ValueError):
                options.validate()


if __name__ == '__main__':
    unittest.main()
